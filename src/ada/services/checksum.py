"""Checksum service: get the checksums that dCache stored for files.

dCache stores Adler32 and/or MD5 checksums. Checksums can be retrieved
for files, for the files in a directory (recursively if wanted), or for
the paths listed in a local file.
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
    """Checksum retrieval for dCache files.

    Args:
        api: Client for the dCache REST API.
        namespace: Namespace service to check path types with. Created
            when needed if not given.
    """

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
        """Get the checksums that dCache stored for files.

        For a directory, the checksums of its files are returned (and,
        with ``recursive``, those in its subdirectories). Give either
        ``paths`` or ``from_file``.

        Args:
            paths: dCache path, or list of paths, of files or directories.
            recursive: Also include files in subdirectories.
            from_file: Local file with one dCache path per line.

        Returns:
            A :class:`~ada.models.Checksum` for each checksum found. A
            file can have more than one, e.g. both Adler32 and MD5.

        Raises:
            AdaValidationError: If both or neither of ``paths`` and
                ``from_file`` are given, or ``from_file`` contains no
                paths.
            FileNotFoundError: If ``from_file`` does not exist.
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
