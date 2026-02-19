"""Extended attributes service — key-value metadata on dCache files.

Extended attributes (xattr) are key-value pairs that can be attached
to files for custom metadata storage.
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
    from ada.core.api import DcacheAPI

logger = logging.getLogger("ada.services.xattr")


class XattrService:
    """Extended attribute management for dCache files."""

    def __init__(self, api: DcacheAPI, namespace: Optional[NamespaceService] = None) -> None:
        self._api = api
        self._namespace = namespace

    def _get_namespace(self) -> NamespaceService:
        if self._namespace is None:
            self._namespace = NamespaceService(self._api)
        return self._namespace

    def set(self, path: str, attributes: dict[str, str] | str) -> str:
        """Set extended attributes on a file.

        Args:
            path: File path.
            attributes: Either a dict of key-value pairs, or a string
                in JSON/key=value format that will be parsed.

        Returns:
            Status message.
        """
        if isinstance(attributes, str):
            attributes = to_json(attributes)

        encoded = encode_path(path)
        self._api.post(
            f"namespace/{encoded}/xattr",
            json=attributes,
        )
        return f"Extended attributes set on '{path}'"

    def set_from_file(self, path: str, attr_file: str) -> str:
        """Set extended attributes from a file.

        The file can contain JSON or key=value pairs.
        """
        content = PathLib(attr_file).read_text(encoding="utf-8").strip()
        return self.set(path, content)

    def list(self, path: str, key: Optional[str] = None) -> dict[str, str]:
        """List extended attributes of a file.

        Args:
            path: File path.
            key: If specified, return only this attribute.

        Returns:
            Dict of attribute key-value pairs.
        """
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
        """Remove extended attribute(s) from a file.

        Args:
            path: File path.
            key: Specific attribute key to remove.
            all_keys: If True, remove all extended attributes.

        Returns:
            Status message.
        """
        encoded = encode_path(path)

        if all_keys:
            xattrs = self.list(path)
            for k in xattrs:
                self._api.delete(f"namespace/{encoded}/xattr/{k}")
            return f"All extended attributes removed from '{path}'"

        if not key:
            raise AdaValidationError(
                "Specify an attribute key to remove, or use all__keys=True."
            )

        self._api.delete(f"namespace/{encoded}/xattr/{key}")
        return f"Extended attribute '{key}' removed from '{path}'"

    def find(
        self,
        path: str,
        key: str,
        regex: str,
        recursive: bool = False,
        all_keys: bool = False,
    ) -> list[tuple[str, dict[str, str]]]:
        """Find files with extended attributes matching a regex.

        Args:
            path: Directory to search.
            key: Attribute key to match against (or search all keys if all_keys=True).
            regex: Regular expression to match against attribute values.
            recursive: If True, search subdirectories.
            all_keys: If True, search all attribute keys.

        Returns:
            List of (file_path, matching_attributes) tuples.
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
