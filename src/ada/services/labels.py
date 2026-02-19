"""Label service — file metadata tagging on dCache.

Labels are simple string tags attached to files. Directories cannot
have labels (dCache restriction).
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
    from ada.core.api import DcacheAPI

logger = logging.getLogger("ada.services.labels")


class LabelService:
    """Label management for dCache files."""

    def __init__(self, api: DcacheAPI, namespace: Optional[NamespaceService] = None) -> None:
        self._api = api
        self._namespace = namespace

    def _get_namespace(self) -> NamespaceService:
        if self._namespace is None:
            self._namespace = NamespaceService(self._api)
        return self._namespace

    def set(self, path: str, label: str) -> str:
        """Attach a label to a file.

        Args:
            path: File path (must be a regular file, not a directory).
            label: Label string to attach.

        Returns:
            Status message.

        Raises:
            AdaPathError: If the path is a directory.
        """
        self._ensure_file(path)
        encoded = encode_path(path)
        self._api.post(
            f"namespace/{encoded}/labels/{label}",
            content_type="application/json",
        )
        return f"Label '{label}' set on '{path}'"

    def list(self, path: str, label: Optional[str] = None) -> list[str]:
        """List labels attached to a file.

        Args:
            path: File path.
            label: If specified, check if this specific label exists.

        Returns:
            List of label strings.
        """
        self._ensure_file(path)
        encoded = encode_path(path)
        if label:
            # Check specific label
            data = self._api.get(f"namespace/{encoded}/labels/{label}")
            if data:
                return [label]
            return []
        data = self._api.get(
            f"namespace/{encoded}", params={"labels": "true"}
        )
        return data.get("labels", [])

    def remove(self, path: str, label: str = "", all_labels: bool = False) -> str:
        """Remove a label from a file.

        Args:
            path: File path.
            label: Specific label to remove.
            all_labels: If True, remove all labels.

        Returns:
            Status message.
        """
        self._ensure_file(path)
        encoded = encode_path(path)

        if all_labels:
            labels = self.list(path)
            for lbl in labels:
                self._api.delete(f"namespace/{encoded}/labels/{lbl}")
            return f"All labels removed from '{path}'"

        if not label:
            raise AdaValidationError("Specify a label to remove, or use all_labels=True")

        self._api.delete(f"namespace/{encoded}/labels/{label}")
        return f"Label '{label}' removed from '{path}'"

    def find(
        self,
        path: str,
        regex: str,
        recursive: bool = False,
    ) -> list[tuple[str, list[str]]]:
        """Find files with labels matching a regex pattern.

        Args:
            path: Directory to search.
            regex: Regular expression to match against labels.
            recursive: If True, search subdirectories.

        Returns:
            List of (file_path, matching_labels) tuples.
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
