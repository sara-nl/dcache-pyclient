"""Label service: tagging files on dCache.

Labels are simple string tags attached to files, to group and find
them. Directories cannot have labels (dCache restriction).

Labels are not private: every user of the same dCache instance can see
a label, together with the names of the files that have it.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional

from ada.exceptions import AdaPathError, AdaValidationError
from ada.models import FileType
from ada.utils import encode_path
from ada.services.namespace import NamespaceService

if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.services.labels")


class LabelService:
    """Label management for dCache files.

    Args:
        api: Client for the dCache REST API.
        namespace: Namespace service to check path types with. Created
            when needed if not given.
    """

    def __init__(self, api: DcacheAPI, namespace: Optional[NamespaceService] = None) -> None:
        self._api = api
        self._namespace = namespace

    def _get_namespace(self) -> NamespaceService:
        if self._namespace is None:
            self._namespace = NamespaceService(self._api)
        return self._namespace

    def set(self, path: str, label: str) -> str:
        """Attach a label to a file.

        Warning:
            Labels are not private: every user of the same dCache
            instance can see a label, together with the names of the
            files that have it. Don't label files whose names are
            confidential, and don't put confidential information in a
            label.

        Args:
            path: dCache path of a file.
            label: The label to attach.

        Returns:
            A message saying that the label was set.

        Raises:
            AdaPathError: If the path is a directory.
        """
        self._ensure_file(path)
        encoded = encode_path(path)
        self._api.post(
            f"namespace/{encoded}", json={"action": "set-label", "label": label}
        )
        return f"Label '{label}' set on '{path}'"

    def list(self, path: str, label: Optional[str] = None) -> list[str]:
        """List the labels of a file, or check for one label.

        Args:
            path: dCache path of a file.
            label: If given, only check whether the file has this label.

        Returns:
            The file's labels. If ``label`` is given, ``[label]`` if the
            file has it, otherwise an empty list.

        Raises:
            AdaPathError: If the path is a directory.
        """
        self._ensure_file(path)
        encoded = encode_path(path)
        data = self._api.get(f"namespace/{encoded}", params={"labels": "true"})
        labels = data.get("labels", [])
        if label:
            return [label] if label in labels else []
        return labels

    def remove(self, path: str, label: str = "", all_labels: bool = False) -> str:
        """Remove one label, or all labels, from a file.

        Args:
            path: dCache path of a file.
            label: The label to remove.
            all_labels: Remove all labels instead.

        Returns:
            A message saying which labels were removed, or that there
            were none.

        Raises:
            AdaPathError: If the path is a directory.
            AdaValidationError: If neither ``label`` nor ``all_labels``
                is given.
        """
        self._ensure_file(path)
        encoded = encode_path(path)

        if all_labels:
            labels = self.list(path)
            if not labels:
                return "No labels to remove."
            for lbl in labels:
                self._api.post(
                    f"namespace/{encoded}", json={"action": "rm-label", "label": lbl}
                )
            return f"All labels removed from '{path}': {', '.join(labels)}"

        if not label:
            raise AdaValidationError("Specify a label to remove, or use all_labels=True")

        self._api.post(
            f"namespace/{encoded}", json={"action": "rm-label", "label": label}
        )
        return f"Label '{label}' removed from '{path}'"

    def find(
        self,
        path: str,
        regex: str,
        recursive: bool = False,
    ) -> list[tuple[str, list[str]]]:
        """Find files in a directory with labels that match a pattern.

        Args:
            path: dCache path of the directory to search.
            regex: Regular expression (Python syntax). A label matches
                when the pattern is found anywhere in it.
            recursive: Also search subdirectories.

        Returns:
            A tuple for each file with matching labels, with the file
            path and the list of matching labels.

        Raises:
            AdaPathError: If the path is a file.
            re.error: If the regular expression is invalid.
        """
        ns = self._get_namespace()

        file_type = ns.get_file_type(path)
        if file_type != FileType.DIR:
            raise AdaPathError(
                f"'{path}' is a file. Please specify a directory to search."
            )

        pattern = re.compile(regex)
        results: list[tuple[str, list[str]]] = []

        self._find_labels_in_dir(path, pattern, recursive, results)
        return results

    def _find_labels_in_dir(
        self,
        path: str,
        pattern: re.Pattern,  # type: ignore[type-arg]
        recursive: bool,
        results: list[tuple[str, list[str]]],
    ) -> None:
        """Recursively search for files with matching labels."""
        base = path.rstrip("/")

        # Get files and their labels
        data = self._api.get(
            f"namespace/{encode_path(path)}",
            params={"children": "true", "labels": "true"},
        )

        for child in data.get("children", []):
            child_path = f"{base}/{child['fileName']}"
            if child["fileType"] == "REGULAR":
                labels = child.get("labels", [])
                matching = [lbl for lbl in labels if pattern.search(lbl)]
                if matching:
                    results.append((child_path, matching))
            elif child["fileType"] == "DIR" and recursive:
                self._find_labels_in_dir(child_path, pattern, recursive, results)

    def _ensure_file(self, path: str) -> None:
        """Verify the path is a regular file, not a directory."""
        ns = self._get_namespace()
        try:
            ft = ns.get_file_type(path)
            if ft == FileType.DIR:
                raise AdaPathError(
                    f"'{path}' is a directory. Labels can only be set on files."
                )
        except AdaPathError:
            raise
        except Exception:
            pass  # Let the API call handle non-existent paths
