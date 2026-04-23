"""Checksum service — retrieve file checksums from dCache.

Supports MD5 and Adler32 checksums, with recursive directory traversal
and file-list input.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ada.models import Checksum, FileType
from ada.utils import encode_path, resolve_paths
from ada.services.namespace import NamespaceService

if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.services.checksum")


class ChecksumService:
    """Checksum retrieval for dCache files."""

    def __init__(self, api: DcacheAPI, namespace: Optional[NamespaceService] = None) -> None:
        self._api = api
        self._namespace = namespace

    def _get_namespace(self) -> NamespaceService:
        """Lazy-load namespace service to avoid circular imports."""
        if self._namespace is None:
            self._namespace = NamespaceService(self._api)
        return self._namespace

    def get(
        self,
        paths: Optional[str | list[str]] = None,
        recursive: bool = False,
        from_file: Optional[str] = None,
    ) -> list[Checksum]:
        """Get checksums for one or more files.

        Args:
            paths: File or directory path(s).
            recursive: If True, recurse into directories.
            from_file: Path to a file containing one path per line.

        Returns:
            List of Checksum objects.
        """

        # Get list of paths
        target_paths = resolve_paths(paths, from_file)

        results: list[Checksum] = []
        ns = self._get_namespace()

        for path in target_paths:
            try:
                file_type = ns.get_file_type(path)
            except Exception:
                logger.warning("Cannot determine type of '%s', treating as file.", path)
                file_type = FileType.REGULAR

            if file_type == FileType.DIR:
                if recursive:
                    file_list = ns.with_files_in_dir(path, recursive=True)
                    results.extend(self._get_checksums_for_paths(file_list))
                else:
                    file_list = [
                        f"{path.rstrip('/')}/{f}"
                        for f in ns.get_files_in_dir(path)
                    ]
                    results.extend(self._get_checksums_for_paths(file_list))
            else:
                results.extend(self._get_checksums_for_file(path))

        return results

    def _get_checksums_for_paths(self, paths: list[str]) -> list[Checksum]:
        """Get checksums for a list of file paths."""
        results: list[Checksum] = []
        for path in paths:
            results.extend(self._get_checksums_for_file(path))
        return results

    def _get_checksums_for_file(self, path: str) -> list[Checksum]:
        """Get checksums for a single file from the API."""
        encoded = encode_path(path)
        data = self._api.get(
            f"namespace/{encoded}",
            params={"checksum": "true"},
        )
        checksums: list[Checksum] = []
        for cs in data.get("checksums", []):
            checksums.append(
                Checksum(
                    path=path,
                    checksum_type=cs.get("type", ""),
                    value=cs.get("value", ""),
                )
            )
        return checksums
