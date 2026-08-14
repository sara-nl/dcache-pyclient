"""AdaClient: main entry point for using ADA as a library.

Composes all services and provides a high-level interface for
interacting with dCache. Fully independent of the CLI layer.

Usage::

    from ada import AdaClient

    with AdaClient(api="https://...", tokenfile="/path/to/token") as client:
        files = client.list("/pnfs/data/mydir")
        client.stage("/pnfs/data/mydir/file.dat", lifetime="7D")
        info = client.whoami()
"""
from __future__ import annotations

import logging
from typing import Optional

from ada.config import load_config
from ada.api import DcacheAPI
from ada.auth import AuthProvider, resolve_auth
from ada.models import (
    BulkRequest,
    BulkRequestStatus,
    Checksum,
    FileInfo,
    QuotaInfo,
    SpaceInfo,
    TransferResult,
    UserInfo,
)
from ada.services.checksum import ChecksumService
from ada.services.labels import LabelService
from ada.services.namespace import NamespaceService
from ada.services.staging import StagingService
from ada.services.system import SystemService
from ada.services.transfer import TransferService
from ada.services.xattr import XattrService

logger = logging.getLogger("ada")


class AdaClient:
    """High-level client for the dCache REST API.

    Can be used as a context manager for automatic cleanup::

        with AdaClient(...) as client:
            client.list("/data")
    """

    def __init__(
        self,
        api: Optional[str] = None,
        tokenfile: Optional[str] = None,
        token: Optional[str] = None,
        netrc: Optional[str] = None,
        proxy: Optional[str] = None,
        igtf: Optional[bool] = None,
        config_paths: Optional[list[str]] = None,
        verify: bool = True,
        debug: bool = False,
    ) -> None:
        # Load config from files and env vars
        self.config = load_config(config_paths)
        if api:
            self.config.api = api
        if debug:
            self.config.debug = debug
        if igtf is not None:
            self.config.igtf = igtf
        self.config.validate()

        # Resolve authentication
        self.auth: AuthProvider = resolve_auth(
            token=token,
            tokenfile=tokenfile,
            netrc=netrc,
            proxy=proxy,
            config=self.config,
        )
        self.auth.validate()

        # Create HTTP client
        self._api = DcacheAPI(
            base_url=self.config.api,
            auth=self.auth,
            verify=verify,
            debug=self.config.debug,
        )

        # Initialize services (with shared namespace reference)
        self.namespace = NamespaceService(self._api)
        self.labels = LabelService(self._api, namespace=self.namespace)
        self.xattr = XattrService(self._api, namespace=self.namespace)
        self.staging = StagingService(self._api, namespace=self.namespace)
        self.checksums = ChecksumService(self._api, namespace=self.namespace)
        self.system = SystemService(self._api)
        self.transfer = TransferService(
            self._api, namespace=self.namespace, checksums=self.checksums
        )

    # ---- Namespace Operations ----

    def list(self, path: str) -> list[str]:
        """List directory contents."""
        return self.namespace.list(path)

    def longlist(
            self, paths: Optional[str | list[str]] = None,
            from_file: Optional[str] = None
            ) -> list[FileInfo]:
        """Get detailed file listing."""
        return self.namespace.longlist(paths, from_file=from_file)

    def stat(self, path: str) -> FileInfo:
        """Get complete file/directory metadata."""
        return self.namespace.stat(path)

    def mkdir(self, path: str, recursive: bool = False) -> str:
        """Create a directory."""
        return self.namespace.mkdir(path, recursive=recursive)

    def mv(self, source: str, destination: str) -> str:
        """Move or rename a file/directory."""
        return self.namespace.mv(source, destination)

    def delete(
        self, path: str, recursive: bool = False, force: bool = False
    ) -> None:
        """Delete a file or directory."""
        self.namespace.delete(path, recursive=recursive, force=force)

    # ---- Label Operations ----

    def set_label(self, path: str, label: str) -> str:
        """Attach a label to a file."""
        return self.labels.set(path, label)

    def list_labels(self, path: str, label: Optional[str] = None) -> list[str]:
        """List labels attached to a file."""
        return self.labels.list(path, label=label)

    def remove_label(
        self, path: str, label: str = "", all_labels: bool = False
    ) -> str:
        """Remove label(s) from a file."""
        return self.labels.remove(path, label=label, all_labels=all_labels)

    def find_label(
        self, path: str, regex: str, recursive: bool = False
    ) -> list[tuple[str, list[str]]]:
        """Find files with labels matching a regex."""
        return self.labels.find(path, regex, recursive=recursive)

    # ---- Extended Attribute Operations ----

    def set_xattr(self, path: str, attributes: dict[str, str] | str) -> str:
        """Set extended attributes on a file."""
        return self.xattr.set(path, attributes)

    def list_xattr(
        self, path: str, key: Optional[str] = None
    ) -> dict[str, str]:
        """List extended attributes of a file."""
        return self.xattr.list(path, key=key)

    def remove_xattr(
        self, path: str, key: str = "", all_keys: bool = False
    ) -> str:
        """Remove extended attribute(s) from a file."""
        return self.xattr.remove(path, key=key, all_keys=all_keys)

    def find_xattr(
        self,
        path: str,
        key: str,
        regex: str,
        recursive: bool = False,
        all_keys: bool = False,
    ) -> list[tuple[str, dict[str, str]]]:
        """Find files with extended attributes matching a regex."""
        return self.xattr.find(
            path, key=key, regex=regex, recursive=recursive, all_keys=all_keys
        )

    # ---- Checksum Operations ----

    def checksum(
        self,
        paths: Optional[str | list[str]] = None,
        recursive: bool = False,
        from_file: Optional[str] = None,
    ) -> list[Checksum]:
        """Get checksums for file(s)."""
        return self.checksums.get(paths, recursive=recursive, from_file=from_file)

    # ---- Transfer Operations ----

    def upload(
        self,
        local_path: str,
        remote_path: str,
        verify_checksum: bool = False,
        allow_insecure_redirects: bool = False,
    ) -> TransferResult:
        """Upload a local file to dCache via WebDAV."""
        return self.transfer.upload(
            local_path,
            remote_path,
            verify_checksum=verify_checksum,
            allow_insecure_redirects=allow_insecure_redirects,
        )

    def download(
        self,
        remote_path: str,
        local_path: str,
        verify_checksum: bool = False,
        allow_insecure_redirects: bool = False,
    ) -> TransferResult:
        """Download a file from dCache via WebDAV."""
        return self.transfer.download(
            remote_path,
            local_path,
            verify_checksum=verify_checksum,
            allow_insecure_redirects=allow_insecure_redirects,
        )

    # ---- Staging Operations ----

    def stage(
        self,
        paths: Optional[str | list[str]] = None,
        recursive: bool = False,
        lifetime: str = "7D",
        from_file: Optional[str] = None,
    ) -> BulkRequest:
        """Stage files from tape to disk."""
        self.auth.validate(command="stage")
        return self.staging.stage(
            paths=paths, recursive=recursive, lifetime=lifetime, from_file=from_file
        )

    def unstage(
        self,
        paths: Optional[str | list[str]] = None,
        recursive: bool = False,
        request_id: Optional[str] = None,
        from_file: Optional[str] = None,
    ) -> BulkRequest:
        """Unstage files — release disk pins."""
        return self.staging.unstage(
            paths=paths,
            recursive=recursive,
            request_id=request_id,
            from_file=from_file,
        )

    def stat_request(self, request_id: str) -> BulkRequestStatus:
        """Get bulk request status."""
        return self.staging.stat_request(request_id)

    def delete_request(self, request_id: str) -> None:
        """Delete a bulk request."""
        self.staging.delete_request(request_id)

    # ---- System Information ----

    def whoami(self) -> UserInfo:
        """Get authenticated user identity."""
        return self.system.whoami()

    def dcache_versions(self) -> list[str]:
        """Get the dCache version(s) running on the server."""
        return self.system.dcache_versions()

    def space(self, poolgroup: Optional[str] = None) -> SpaceInfo | list[str]:
        """Get storage space info."""
        return self.system.space(poolgroup)

    def poolgroups_for_path(self, path: str) -> list[str]:
        """Resolve which pool group(s) serve a namespace directory."""
        return self.system.poolgroups_for_path(path)

    def quota(self) -> list[QuotaInfo]:
        """Get storage quota info."""
        return self.system.quota()

    # ---- Token ----

    def view_token(self) -> dict:
        """Decode and display the current token."""
        return self.auth.view_token()

    def token_expiry_status(self) -> str:
        """Describe the current token's expiry, informationally.

        Unlike commands that use the token, this never raises just
        because the token is expired — it's meant for inspection.
        """
        return self.auth.expiry_status()

    # ---- Lifecycle ----

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._api.close()

    def __enter__(self) -> AdaClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
