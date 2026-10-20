"""Transfer service — upload and download file content via WebDAV.

The dCache REST API can only manage metadata; actual file content is
transferred through a WebDAV door (see ``ada.webdav``). This service
applies the same safety rules as the Bash version: no silent
overwrites, no downloading directories/symlinks, and — importantly —
refuses to download a file that's only on tape (nearline), since
dCache would otherwise silently stage it while the connection sits
there waiting, which can take anywhere from minutes to days.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import zlib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlsplit

from ada.exceptions import AdaNotFoundError, AdaPathError, AdaTransferError
from ada.models import FileType, TransferResult
from ada.services.checksum import ChecksumService
from ada.services.namespace import NamespaceService
from ada.webdav import WebdavClient, discover_webdav_door

if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.services.transfer")

_CHUNK_SIZE = 1024 * 1024


class TransferService:
    """Upload and download file content via WebDAV."""

    def __init__(
        self,
        api: DcacheAPI,
        namespace: Optional[NamespaceService] = None,
        checksums: Optional[ChecksumService] = None,
    ) -> None:
        self._api = api
        self._namespace = namespace
        self._checksums = checksums

    def _get_namespace(self) -> NamespaceService:
        """Lazy-load namespace service to avoid circular imports."""
        if self._namespace is None:
            self._namespace = NamespaceService(self._api)
        return self._namespace

    def _get_checksums(self) -> ChecksumService:
        """Lazy-load checksum service to avoid circular imports."""
        if self._checksums is None:
            self._checksums = ChecksumService(self._api, namespace=self._get_namespace())
        return self._checksums

    # ---- Upload ----

    def upload(
        self,
        local_path: str,
        remote_path: str,
        verify_checksum: bool = False,
        allow_insecure_redirects: bool = False,
    ) -> TransferResult:
        """Upload a local file to dCache.

        Args:
            local_path: Path to the local file to upload.
            remote_path: Destination dCache path, or a directory to
                upload into (keeping the local filename). May be
                prefixed with a WebDAV door (e.g. ``https://door/path``)
                to bypass door discovery.
            verify_checksum: If True, ask dCache to verify the upload's
                MD5 checksum server-side (via the Content-MD5 header),
                and if the destination already exists, compare checksums
                instead of failing outright.
            allow_insecure_redirects: If True, follow WebDAV redirects
                even if they downgrade to plain HTTP.

        Raises:
            AdaPathError: If the local file doesn't exist, the
                destination is an existing file (without
                verify_checksum) or a symlink, or its parent doesn't exist.
            AdaTransferError: On a checksum mismatch or WebDAV-level failure.
        """
        source = Path(local_path)
        if not source.is_file():
            raise AdaPathError(f"Local file '{local_path}' does not exist or is not a file.")

        door, path = self._split_door_and_path(remote_path)
        ns = self._get_namespace()

        file_type = self._file_type_or_none(path)
        if file_type == FileType.DIR:
            path = f"{path.rstrip('/')}/{source.name}"
            file_type = self._file_type_or_none(path)

        if file_type == FileType.REGULAR:
            if not verify_checksum:
                raise AdaPathError(
                    f"Target '{path}' already exists. Ada does not support overwriting a file."
                )
            logger.info("Target '%s' already exists. Verifying checksum...", path)
            self._verify_checksum(local_path, path)
            return TransferResult(local_path, path, status="already-verified", checksum_verified=True)
        if file_type == FileType.LINK:
            raise AdaPathError(
                f"Target '{path}' is a symlink. Ada does not support uploading to a symlink."
            )

        parent = str(PurePosixPath(path).parent)
        if not ns.is_dir(parent):
            raise AdaPathError(
                f"Parent of '{path}', '{parent}', is not a directory. Create it first."
            )

        extra_headers = None
        if verify_checksum:
            extra_headers = {"Content-MD5": self._content_md5_header(local_path)}

        if door is None:
            door = discover_webdav_door(self._api, self._api.auth)

        client = self._webdav_client(door, allow_insecure_redirects)
        try:
            client.upload(local_path, path, extra_headers=extra_headers)
        finally:
            client.close()

        return TransferResult(local_path, path, status="uploaded", checksum_verified=verify_checksum)

    # ---- Download ----

    def download(
        self,
        remote_path: str,
        local_path: str,
        verify_checksum: bool = False,
        allow_insecure_redirects: bool = False,
    ) -> TransferResult:
        """Download a file from dCache.

        Args:
            remote_path: Source dCache path. May be prefixed with a
                WebDAV door (e.g. ``https://door/path``) to bypass door
                discovery.
            local_path: Destination local path, or a directory to
                download into (keeping the remote filename).
            verify_checksum: If True and the local file already exists,
                compare checksums instead of failing outright; and after
                a fresh download, verify the transferred content's
                checksum against dCache's.
            allow_insecure_redirects: If True, follow WebDAV redirects
                even if they downgrade to plain HTTP.

        Raises:
            AdaPathError: If the local target already exists (without
                verify_checksum), or the source is a directory/symlink,
                or the parent directory doesn't exist.
            AdaNotFoundError: If the source doesn't exist.
            AdaTransferError: If the source is on tape and not online
                (with a suggestion to stage it first), or on checksum
                mismatch / WebDAV-level failure.
        """
        door, path = self._split_door_and_path(remote_path)
        ns = self._get_namespace()

        target = Path(local_path)
        real_target = target
        if target.is_file():
            if not verify_checksum:
                raise AdaPathError(f"Target file '{local_path}' already exists.")
            logger.info("Target file '%s' already exists. Verifying checksum...", local_path)
            self._verify_checksum(local_path, path)
            return TransferResult(local_path, path, status="already-verified", checksum_verified=True)
        if target.is_dir():
            real_target = target / PurePosixPath(path).name
            if real_target.exists():
                raise AdaPathError(f"Destination '{real_target}' already exists.")
        else:
            parent = target.parent
            if not parent.is_dir():
                raise AdaPathError(
                    f"Cannot download to '{local_path}': directory '{parent}' does not exist."
                )

        file_type = self._file_type_or_none(path)
        if file_type is None:
            raise AdaNotFoundError(f"Source file '{path}' does not exist.")
        if file_type == FileType.DIR:
            raise AdaPathError(
                f"Source '{path}' is a directory. Ada does not support downloading a directory."
            )
        if file_type == FileType.LINK:
            raise AdaPathError(
                f"Source '{path}' is a symlink. Ada does not support downloading from a symlink."
            )

        # If the file is only on tape, dCache would silently stage it
        # while we sit here waiting, which can take minutes to days and
        # ties up a transfer slot the whole time. Refuse and point the
        # user at --stage instead.
        if not ns.is_online(path):
            raise AdaTransferError(
                f"File '{path}' exists, but it is on tape and not online. "
                "You need to stage it first before you can download it. "
                "You can do that with:\n"
                f"    ada-cli stage '{path}'\n"
                "Staging works most efficiently when done in bulk."
            )

        if door is None:
            door = discover_webdav_door(self._api, self._api.auth)

        client = self._webdav_client(door, allow_insecure_redirects)
        try:
            client.download(path, str(real_target))
        finally:
            client.close()

        if verify_checksum:
            self._verify_checksum(str(real_target), path)

        return TransferResult(
            str(real_target), path, status="downloaded", checksum_verified=verify_checksum
        )

    # ---- Internal ----

    def _webdav_client(self, door: str, allow_insecure_redirects: bool) -> WebdavClient:
        return WebdavClient(
            door=door,
            auth=self._api.auth,
            verify=self._api.verify,
            allow_insecure_redirects=allow_insecure_redirects,
        )

    def _file_type_or_none(self, path: str) -> Optional[FileType]:
        try:
            return self._get_namespace().get_file_type(path)
        except AdaNotFoundError:
            return None

    def _verify_checksum(self, local_path: str, remote_path: str) -> None:
        """Compare local vs remote checksum, preferring Adler32 over MD5.

        Raises:
            AdaTransferError: If no checksum is available, or on mismatch.
        """
        remote_checksums = {
            c.checksum_type: c.value for c in self._get_checksums().get(remote_path)
        }
        if "ADLER32" in remote_checksums:
            checksum_type = "ADLER32"
            remote_value = remote_checksums["ADLER32"]
            local_value = self._local_adler32(local_path)
        elif "MD5_TYPE" in remote_checksums:
            checksum_type = "MD5_TYPE"
            remote_value = remote_checksums["MD5_TYPE"]
            local_value = self._local_md5(local_path)
        else:
            raise AdaTransferError(f"Unable to get a checksum for '{remote_path}'.")

        if local_value.lower() != remote_value.lower():
            raise AdaTransferError(
                f"Checksum mismatch for '{remote_path}' ({checksum_type}): "
                f"local={local_value} remote={remote_value}"
            )
        logger.info("Checksum OK (%s).", checksum_type)

    @staticmethod
    def _split_door_and_path(target: str) -> tuple[Optional[str], str]:
        """Split an optional WebDAV door prefix off a dCache path.

        ``https://door.example.org/pnfs/data/file`` -> (door, path).
        A plain path (no ``://``) is returned as-is, with door=None.
        """
        if "://" not in target:
            return None, target
        parts = urlsplit(target)
        return f"{parts.scheme}://{parts.netloc}", parts.path

    @staticmethod
    def _local_adler32(path: str) -> str:
        checksum = 1
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                checksum = zlib.adler32(chunk, checksum)
        return format(checksum & 0xFFFFFFFF, "08x")

    @staticmethod
    def _local_md5(path: str) -> str:
        return TransferService._md5_digest(path).hex()

    @staticmethod
    def _content_md5_header(path: str) -> str:
        """Base64-encoded raw MD5 digest, for the HTTP Content-MD5 header."""
        return base64.b64encode(TransferService._md5_digest(path)).decode("ascii")

    @staticmethod
    def _md5_digest(path: str) -> bytes:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                h.update(chunk)
        return h.digest()
