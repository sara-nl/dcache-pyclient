"""Extended attributes service: key-value metadata on dCache files.

Extended attributes (xattr) are key-value pairs that can be attached
to files for custom metadata. Directories cannot have them.
"""

from __future__ import annotations

import logging
from pathlib import Path as PathLib
import re
from typing import TYPE_CHECKING, Optional

from ada.exceptions import AdaPathError, AdaValidationError
from ada.models import FileType
from ada.utils import encode_path, to_json
from ada.services.namespace import NamespaceService

if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.services.xattr")


class XattrService:
    """Extended attribute management for dCache files.

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

    def set(self, path: str, attributes: dict[str, str] | str) -> str:
        """Set extended attributes on a file.

        Existing attributes with the same keys are overwritten.

        Args:
            path: dCache path of a file.
            attributes: The attributes, as a dict, or as a string in one
                of the formats accepted by :func:`ada.utils.to_json`.

        Returns:
            A message saying that the attributes were set.

        Raises:
            AdaPathError: If the path is a directory.
            AdaValidationError: If the string can't be parsed.
        """
        if isinstance(attributes, str):
            attributes = to_json(attributes)

        self._ensure_file(path)
        encoded = encode_path(path)
        self._api.post(
            f"namespace/{encoded}",
            json={"action": "set-xattr", "attributes": attributes},
        )
        return f"Extended attributes set on '{path}'"

    def set_from_file(self, path: str, attr_file: str) -> str:
        """Set extended attributes on a file, read from a local file.

        Args:
            path: dCache path of a file.
            attr_file: Local file with the attributes, in one of the
                formats accepted by :func:`ada.utils.to_json`.

        Returns:
            A message saying that the attributes were set.

        Raises:
            AdaPathError: If the path is a directory.
            AdaValidationError: If the content can't be parsed.
            FileNotFoundError: If ``attr_file`` does not exist.
        """
        content = PathLib(attr_file).read_text(encoding="utf-8").strip()
        return self.set(path, content)

    def list(self, path: str, key: Optional[str] = None) -> dict[str, str]:
        """List the extended attributes of a file, or get one of them.

        Args:
            path: dCache path of a file.
            key: If given, only get this attribute.

        Returns:
            The attributes as a dict. If ``key`` is given, a dict with
            only that attribute, or an empty dict if the file doesn't
            have it.

        Raises:
            AdaPathError: If the path is a directory.
        """
        self._ensure_file(path)
        encoded = encode_path(path)
        data = self._api.get(
            f"namespace/{encoded}", params={"xattr": "true"}
        )
        xattrs = data.get("extendedAttributes", {})

        if key:
            if key in xattrs:
                return {key: xattrs[key]}
            return {}
        return xattrs

    def remove(self, path: str, key: str = "", all_keys: bool = False) -> str:
        """Remove one extended attribute, or all of them, from a file.

        Args:
            path: dCache path of a file.
            key: Key of the attribute to remove.
            all_keys: Remove all extended attributes instead.

        Returns:
            A message saying which attributes were removed, or that
            there were none.

        Raises:
            AdaPathError: If the path is a directory.
            AdaValidationError: If neither ``key`` nor ``all_keys`` is
                given.
        """
        self._ensure_file(path)
        encoded = encode_path(path)

        if all_keys:
            names = list(self.list(path))
            if not names:
                return "No attributes to remove."
            self._api.post(
                f"namespace/{encoded}", json={"action": "rm-xattr", "names": names}
            )
            return f"All extended attributes removed from '{path}': {', '.join(names)}"

        if not key:
            raise AdaValidationError(
                "Specify an attribute key to remove, or use all_keys=True."
            )

        self._api.post(
            f"namespace/{encoded}", json={"action": "rm-xattr", "names": [key]}
        )
        return f"Extended attribute '{key}' removed from '{path}'"

    def find(
        self,
        path: str,
        key: str,
        regex: str,
        recursive: bool = False,
        all_keys: bool = False,
    ) -> list[tuple[str, dict[str, str]]]:
        """Find files in a directory with attribute values that match a pattern.

        Args:
            path: dCache path of the directory to search.
            key: Key of the attribute whose value is matched. Ignored if
                ``all_keys`` is True.
            regex: Regular expression (Python syntax). A value matches
                when the pattern is found anywhere in it.
            recursive: Also search subdirectories.
            all_keys: Match the values of all attributes, not only
                ``key``.

        Returns:
            A tuple for each file with matching attributes, with the
            file path and a dict of the matching attributes.

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
        results: list[tuple[str, dict[str, str]]] = []

        self._find_xattr_in_dir(path, key, pattern, recursive, all_keys, results)
        return results

    def _find_xattr_in_dir(
        self,
        path: str,
        key: str,
        pattern: re.Pattern,  # type: ignore[type-arg]
        recursive: bool,
        all_keys: bool,
        results: list[tuple[str, dict[str, str]]],
    ) -> None:
        """Recursively search for files with matching attributes."""
        base = path.rstrip("/")

        data = self._api.get(
            f"namespace/{encode_path(path)}",
            params={"children": "true", "xattr": "true"},
        )

        for child in data.get("children", []):
            child_path = f"{base}/{child['fileName']}"
            if child["fileType"] == "REGULAR":
                xattrs = child.get("extendedAttributes", {})
                matching: dict[str, str] = {}

                if all_keys:
                    for k, v in xattrs.items():
                        if pattern.search(v):
                            matching[k] = v
                elif key in xattrs:
                    if pattern.search(xattrs[key]):
                        matching[key] = xattrs[key]

                if matching:
                    results.append((child_path, matching))
            elif child["fileType"] == "DIR" and recursive:
                self._find_xattr_in_dir(
                    child_path, key, pattern, recursive, all_keys, results
                )

    def _ensure_file(self, path: str) -> None:
        """Verify the path is a regular file, not a directory."""
        ns = self._get_namespace()
        try:
            ft = ns.get_file_type(path)
            if ft == FileType.DIR:
                raise AdaPathError(
                    f"'{path}' is a directory. Extended attributes can only be set on files."
                )
        except AdaPathError:
            raise
        except Exception:
            pass  # Let the API call handle non-existent paths
