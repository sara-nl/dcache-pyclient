"""AdaClient: main entry point for using ADA as a library.

:class:`AdaClient` gives access to dCache through its REST API (and,
for uploads and downloads, a WebDAV door). It is fully independent of
the ``ada-cli`` command line tool.

Example::

    from ada import AdaClient

    with AdaClient(api="https://dcache.example.org:3880/api/v1",
                   tokenfile="~/macaroon.conf") as client:
        print(client.list("/pnfs/example.org/data/mydir"))
        client.stage("/pnfs/example.org/data/mydir/file.dat", lifetime="7D")
"""
from __future__ import annotations

import logging
from typing import Optional

from ada.config import load_config
from ada.exceptions import AdaConfigError
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

    Creating a client loads the configuration, picks an authentication
    method and checks the credentials (e.g. that a token has not
    expired), so problems show up right away rather than at the first
    request.

    **Configuration** is read from, in order of increasing precedence:
    the bundled defaults, ``/etc/ada.conf``, ``~/.ada/ada.conf``,
    environment variables (such as ``ada_api``) and finally the
    arguments given here.

    **Authentication** uses the first method found, in this order:

    1. Arguments: ``token``, ``tokenfile``, ``tokenclient``, ``netrc``,
       ``proxy``.
    2. Environment variables: ``$BEARER_TOKEN``, ``$ada_tokenfile``,
       ``$ada_tokenclient``, ``$ada_netrcfile``.
    3. Config file settings: ``tokenfile``, ``tokenclient``,
       ``netrcfile``.

    Use the client as a context manager, or call :meth:`close` when done,
    to close the network connections.

    Args:
        api: URL of the dCache REST API, e.g.
            ``"https://dcache.example.org:3880/api/v1"``. Must start
            with ``https://``. Overrides the ``api`` config setting.
        tokenfile: File with a bearer token (macaroon or OIDC token):
            either an rclone config file with a ``bearer_token`` line,
            or a file with only the token. Must not be readable or
            writable by others.
        token: Bearer token (macaroon or OIDC token) as a string.
        tokenclient: Name of an oidc-agent account to get OIDC tokens
            from. Needs oidc-agent to be installed and running, and
            ``pip install 'dcache-pyclient[oidc-agent]'``.
        netrc: Netrc file with a username and password for the API host.
            An empty string means ``~/.netrc``. Must not be readable or
            writable by others.
        proxy: X.509 proxy certificate file. An empty string means
            ``$X509_USER_PROXY``, or ``/tmp/x509up_u<uid>`` if that is
            not set.
        igtf: For proxy authentication, also trust the IGTF Grid CA
            certificates (in ``$X509_CERT_DIR``, by default
            ``/etc/grid-security/certificates``) when verifying the
            server. Set to False when the server has a regular
            certificate, e.g. from Let's Encrypt.
            Overrides the ``igtf`` config setting.
        config_paths: Config files to read instead of the default ones,
            highest precedence first.
        verify: Verify the server's TLS certificate. Only set to False
            for testing: it makes the connection insecure.
        debug: Log the HTTP requests and responses (at debug level, on
            the ``ada`` logger).

    Raises:
        AdaConfigError: If no API URL is given, or it does not start
            with ``https://``.
        AdaAuthError: If no authentication method is found, or the
            credentials can't be read (e.g. a missing proxy file).
        AdaTokenExpiredError: If the token or proxy has expired, or
            expires within 60 seconds.
        AdaSecurityError: If a token, netrc or config file is readable
            or writable by others.
        FileNotFoundError: If the token or netrc file does not exist.
        RuntimeError: If ``tokenclient`` is used but the oidc-agent
            library is not installed.

    Example::

        from ada import AdaClient

        with AdaClient(api="https://dcache.example.org:3880/api/v1",
                       tokenfile="~/macaroon.conf") as client:
            info = client.whoami()
            print(info.username, info.home)
    """

    def __init__(
        self,
        api: Optional[str] = None,
        tokenfile: Optional[str] = None,
        token: Optional[str] = None,
        tokenclient: Optional[str] = None,
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
        if not self.config.api:
            raise AdaConfigError(
                "No dCache API address specified. Use --api URL, $ada_api, "
                "or api=URL in ada.conf, e.g. "
                "api=https://dcache.example.org:3880/api/v1\n"
                "See https://sara-nl.github.io/dcache-pyclient/configuration.html"
            )

        # Resolve authentication
        self.auth: AuthProvider = resolve_auth(
            token=token,
            tokenfile=tokenfile,
            tokenclient=tokenclient,
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
        """List the contents of a directory.

        Args:
            path: dCache path of a directory or file.

        Returns:
            The names of the files and subdirectories in the directory,
            sorted, with ``/`` appended to subdirectory names. For a
            file, a list with only the file name.

        Raises:
            AdaNotFoundError: If the path does not exist.

        Example::

            client.list("/pnfs/example.org/data/run1")
            # ['calibration/', 'file1.dat', 'file2.dat']
        """
        return self.namespace.list(path)

    def longlist(
            self, paths: Optional[str | list[str]] = None,
            from_file: Optional[str] = None
            ) -> list[FileInfo]:
        """List files with details: size, modification time, QoS, locality.

        For a directory, its files and subdirectories are listed (not
        recursively). Give either ``paths`` or ``from_file``.

        Args:
            paths: dCache path, or list of paths, of files or directories.
            from_file: Local file with one dCache path per line. Empty
                lines and lines starting with ``#`` are skipped.

        Returns:
            A :class:`~ada.models.FileInfo` for each file or subdirectory.

        Raises:
            AdaValidationError: If both or neither of ``paths`` and
                ``from_file`` are given, or ``from_file`` contains no
                paths.
            FileNotFoundError: If ``from_file`` does not exist.
            AdaNotFoundError: If a path does not exist.

        Example::

            for info in client.longlist("/pnfs/example.org/data/run1"):
                print(info.path, info.size, info.locality)
        """
        return self.namespace.longlist(paths, from_file=from_file)

    def stat(self, path: str) -> dict:
        """Get all metadata of a file or directory, as dCache returns it.

        Unlike :meth:`longlist`, this returns the complete, unprocessed
        API response, including locality, locations, QoS, extended
        attributes, labels, checksums, storage class, access latency,
        retention policy, ownership and timestamps.

        Args:
            path: dCache path of a file or directory.

        Returns:
            The metadata as a dict, with the field names that dCache
            uses (e.g. ``fileLocality``, ``storageInfo``).

        Raises:
            AdaNotFoundError: If the path does not exist.
        """
        return self.namespace.stat(path)

    def mkdir(self, path: str, recursive: bool = False) -> str:
        """Create a directory.

        Args:
            path: dCache path of the directory to create.
            recursive: Also create missing parent directories, at most
                10 levels at once.

        Returns:
            ``"created"``, or ``"already exists"`` if the directory
            already existed.

        Raises:
            AdaPathError: If the parent directory does not exist and
                ``recursive`` is False.
            AdaValidationError: If more than 10 directory levels would
                have to be created.

        Example::

            client.mkdir("/pnfs/example.org/data/run2/raw", recursive=True)
        """
        return self.namespace.mkdir(path, recursive=recursive)

    def mv(self, source: str, destination: str) -> str:
        """Move or rename a file or directory.

        Moving a file does not change where its data is stored: a file
        on tape stays on tape, even when it is moved to a directory for
        disk-only data.

        Args:
            source: Current dCache path.
            destination: New dCache path. Must not exist yet.

        Returns:
            ``"moved"``.

        Raises:
            AdaPathError: If the destination already exists.
            AdaNotFoundError: If the source does not exist.
        """
        return self.namespace.mv(source, destination)

    def delete(
        self, path: str, recursive: bool = False, force: bool = False
    ) -> None:
        """Delete a file or directory.

        Args:
            path: dCache path of a file or directory.
            recursive: Required to delete a directory: deletes the
                directory with all its contents.
            force: When deleting recursively, don't ask for
                confirmation. Without it, the user is asked on the
                terminal to confirm before each subdirectory is deleted.
                Use ``force=True`` in scripts.

        Raises:
            AdaPathError: If the path is a directory and ``recursive``
                is False.
            AdaNotFoundError: If the path does not exist.
            SystemExit: If the user does not confirm the deletion.

        Example::

            client.delete("/pnfs/example.org/data/tmp", recursive=True, force=True)
        """
        self.namespace.delete(path, recursive=recursive, force=force)

    # ---- Label Operations ----

    def set_label(self, path: str, label: str) -> str:
        """Attach a label to a file.

        Labels are tags that can be used to group and find files, see
        :meth:`find_label`. Directories cannot have labels.

        Args:
            path: dCache path of a file.
            label: The label to attach.

        Returns:
            A message saying that the label was set.

        Raises:
            AdaPathError: If the path is a directory.
        """
        return self.labels.set(path, label)

    def list_labels(self, path: str, label: Optional[str] = None) -> list[str]:
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
        return self.labels.list(path, label=label)

    def remove_label(
        self, path: str, label: str = "", all_labels: bool = False
    ) -> str:
        """Remove one label, or all labels, from a file.

        Args:
            path: dCache path of a file.
            label: The label to remove.
            all_labels: Remove all labels instead.

        Returns:
            A message saying which labels were removed.

        Raises:
            AdaPathError: If the path is a directory.
            AdaValidationError: If neither ``label`` nor ``all_labels``
                is given.
        """
        return self.labels.remove(path, label=label, all_labels=all_labels)

    def find_label(
        self, path: str, regex: str, recursive: bool = False
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

        Example::

            for path, labels in client.find_label("/pnfs/example.org/data",
                                                  "^run-2026", recursive=True):
                print(path, labels)
        """
        return self.labels.find(path, regex, recursive=recursive)

    # ---- Extended Attribute Operations ----

    def set_xattr(self, path: str, attributes: dict[str, str] | str) -> str:
        """Set extended attributes on a file.

        Extended attributes are key-value pairs for your own metadata.
        Existing attributes with the same keys are overwritten.
        Directories cannot have extended attributes.

        Args:
            path: dCache path of a file.
            attributes: The attributes, as a dict, or as a string with
                JSON (``'{"key": "value"}'``) or ``key=value`` pairs
                separated by commas or newlines.

        Returns:
            A message saying that the attributes were set.

        Raises:
            AdaPathError: If the path is a directory.

        Example::

            client.set_xattr("/pnfs/example.org/data/run1/file1.dat",
                             {"experiment": "lofar", "quality": "good"})
        """
        return self.xattr.set(path, attributes)

    def list_xattr(
        self, path: str, key: Optional[str] = None
    ) -> dict[str, str]:
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
        return self.xattr.list(path, key=key)

    def remove_xattr(
        self, path: str, key: str = "", all_keys: bool = False
    ) -> str:
        """Remove one extended attribute, or all of them, from a file.

        Args:
            path: dCache path of a file.
            key: Key of the attribute to remove.
            all_keys: Remove all extended attributes instead.

        Returns:
            A message saying which attributes were removed.

        Raises:
            AdaPathError: If the path is a directory.
            AdaValidationError: If neither ``key`` nor ``all_keys`` is
                given.
        """
        return self.xattr.remove(path, key=key, all_keys=all_keys)

    def find_xattr(
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

        Example::

            matches = client.find_xattr("/pnfs/example.org/data", "quality",
                                        "^good$", recursive=True)
        """
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
        """Get the checksums that dCache stored for files.

        For a directory, the checksums of its files are returned (and,
        with ``recursive``, those in its subdirectories). Give either
        ``paths`` or ``from_file``.

        Args:
            paths: dCache path, or list of paths, of files or directories.
            recursive: Also include files in subdirectories.
            from_file: Local file with one dCache path per line. Empty
                lines and lines starting with ``#`` are skipped.

        Returns:
            A :class:`~ada.models.Checksum` for each checksum found. A
            file can have more than one, e.g. both Adler32 and MD5.

        Raises:
            AdaValidationError: If both or neither of ``paths`` and
                ``from_file`` are given, or ``from_file`` contains no
                paths.
            FileNotFoundError: If ``from_file`` does not exist.

        Example::

            for cs in client.checksum("/pnfs/example.org/data/run1"):
                print(cs.path, cs.checksum_type, cs.value)
        """
        return self.checksums.get(paths, recursive=recursive, from_file=from_file)

    # ---- Transfer Operations ----

    def upload(
        self,
        local_path: str,
        remote_path: str,
        verify_checksum: bool = False,
        allow_insecure_redirects: bool = False,
    ) -> TransferResult:
        """Upload a local file to dCache.

        The file content goes through a WebDAV door, which is found
        automatically through the REST API. Existing files are never
        overwritten.

        Args:
            local_path: Local file to upload.
            remote_path: dCache path for the new file, or an existing
                dCache directory to upload into (keeping the local file
                name). Can start with a WebDAV door URL, e.g.
                ``"https://webdav.example.org:2880/pnfs/..."``, to use
                that door.
            verify_checksum: Let dCache check the MD5 checksum of the
                uploaded data. If the file already exists in dCache,
                compare checksums instead of failing: when they match,
                nothing is uploaded.
            allow_insecure_redirects: Follow redirects from the WebDAV
                door to plain ``http://`` addresses.

        Returns:
            The result, with ``status`` ``"uploaded"``, or
            ``"already-verified"`` when an existing file had the same
            checksum.

        Raises:
            AdaPathError: If the local file doesn't exist, the dCache
                file already exists (without ``verify_checksum``) or is
                a symlink, or the dCache parent directory doesn't exist.
            AdaTransferError: If the checksums don't match, or no WebDAV
                door is found, or a redirect is refused.
            AdaAPIError: If the WebDAV door returns an HTTP error.

        Example::

            client.upload("results.csv", "/pnfs/example.org/data/run1/",
                          verify_checksum=True)
        """
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
        """Download a file from dCache.

        The file content goes through a WebDAV door, which is found
        automatically through the REST API. Existing local files are
        never overwritten. Files that are only on tape must be staged
        first (see :meth:`stage`).

        Args:
            remote_path: dCache path of the file. Can start with a
                WebDAV door URL, e.g.
                ``"https://webdav.example.org:2880/pnfs/..."``, to use
                that door.
            local_path: Local path for the new file, or an existing
                local directory to download into (keeping the dCache
                file name).
            verify_checksum: Check the downloaded file against the
                checksum in dCache. If the local file already exists,
                compare checksums instead of failing: when they match,
                nothing is downloaded.
            allow_insecure_redirects: Follow redirects from the WebDAV
                door to plain ``http://`` addresses.

        Returns:
            The result, with ``status`` ``"downloaded"``, or
            ``"already-verified"`` when an existing local file had the
            same checksum.

        Raises:
            AdaPathError: If the local file already exists (without
                ``verify_checksum``), the local directory doesn't exist,
                or the dCache path is a directory or symlink.
            AdaNotFoundError: If the dCache file doesn't exist.
            AdaTransferError: If the file is only on tape (not online),
                the checksums don't match, no WebDAV door is found, or a
                redirect is refused.
            AdaAPIError: If the WebDAV door returns an HTTP error.

        Example::

            client.download("/pnfs/example.org/data/run1/file1.dat", ".")
        """
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
        """Stage files from tape, so they are online (on disk) to be read.

        Staging also pins the files: dCache keeps the online copy at
        least until the pin lifetime has passed. Staging happens in the
        background; the returned request can be followed with
        :meth:`stat_request`. Give either ``paths`` or ``from_file``.

        Args:
            paths: dCache path, or list of paths, of the files or
                directories to stage. For a directory, the files in it
                are staged.
            recursive: For directories, also stage the files in their
                subdirectories.
            lifetime: How long the files stay pinned, as a number with a
                unit: S (seconds), M (minutes), H (hours) or D (days),
                e.g. ``"12H"`` or ``"7D"``.
            from_file: Local file with one dCache path per line. Empty
                lines and lines starting with ``#`` are skipped.

        Returns:
            The bulk request that dCache created for the staging.

        Raises:
            AdaTokenPermissionError: If the token does not allow staging.
            AdaValidationError: If the lifetime is not valid, both or
                neither of ``paths`` and ``from_file`` are given, or
                ``from_file`` contains no paths.
            FileNotFoundError: If ``from_file`` does not exist.
            AdaForbiddenError: If the server refuses the request, e.g.
                because staging directories (recursively) is not
                allowed.
            AdaAPIError: If the request fails otherwise.

        Example::

            request = client.stage("/pnfs/example.org/data/run1/file1.dat",
                                   lifetime="2D")
            print(client.stat_request(request.request_id).status)
        """
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
        """Unstage files: release their pins, so dCache may remove the online copy.

        The data stays safe on tape. Give either ``paths`` or
        ``from_file``.

        Args:
            paths: dCache path, or list of paths, of the files or
                directories to unstage. For a directory, the files in it
                are unstaged.
            recursive: For directories, also unstage the files in their
                subdirectories.
            request_id: Only release the pin created by this earlier
                stage request (its
                :attr:`~ada.models.BulkRequest.request_id`). By default,
                all pins of the files are released.
            from_file: Local file with one dCache path per line. Empty
                lines and lines starting with ``#`` are skipped.

        Returns:
            The bulk request that dCache created for the unstaging.

        Raises:
            AdaValidationError: If both or neither of ``paths`` and
                ``from_file`` are given, or ``from_file`` contains no
                paths.
            FileNotFoundError: If ``from_file`` does not exist.
            AdaForbiddenError: If the server refuses the request, e.g.
                because unstaging directories (recursively) is not
                allowed.
            AdaAPIError: If the request fails otherwise.
        """
        return self.staging.unstage(
            paths=paths,
            recursive=recursive,
            request_id=request_id,
            from_file=from_file,
        )

    def stat_request(self, request_id: str) -> BulkRequestStatus:
        """Get the status of a bulk (stage or unstage) request.

        Args:
            request_id: ID of the request, from
                :attr:`~ada.models.BulkRequest.request_id`.

        Returns:
            The status of the request and of each file in it.

        Raises:
            AdaNotFoundError: If the request does not exist.
        """
        return self.staging.stat_request(request_id)

    def delete_request(self, request_id: str) -> None:
        """Delete a bulk (stage or unstage) request from dCache.

        Args:
            request_id: ID of the request, from
                :attr:`~ada.models.BulkRequest.request_id`.

        Raises:
            AdaNotFoundError: If the request does not exist.
        """
        self.staging.delete_request(request_id)

    # ---- System Information ----

    def whoami(self) -> UserInfo:
        """Show how dCache identifies you with the current credentials.

        Returns:
            Your identity, with the status (``"AUTHENTICATED"`` when the
            credentials were accepted), user and group IDs, user name,
            and home and root directory.

        Example::

            info = client.whoami()
            print(info.status, info.username, info.home)
        """
        return self.system.whoami()

    def dcache_versions(self) -> list[str]:
        """Get the dCache version(s) running on the server.

        The services of a dCache instance can run different versions,
        e.g. during an upgrade.

        Returns:
            The versions found, sorted, without duplicates.
        """
        return self.system.dcache_versions()

    def space(self, poolgroup: Optional[str] = None) -> SpaceInfo | list[str]:
        """List the pool groups, or get the space of one pool group.

        A pool group is a set of storage nodes (pools) in dCache. To find
        the pool group(s) where a directory's data is stored, use
        :meth:`poolgroups_for_path`.

        Args:
            poolgroup: Name of a pool group. If not given, the names of
                all pool groups are returned.

        Returns:
            The names of all pool groups, or, with ``poolgroup``, its
            total, free, precious and removable space in bytes.

        Raises:
            AdaAPIError: If the pool group does not exist.

        Example::

            for name in client.poolgroups_for_path("/pnfs/example.org/data"):
                print(name, client.space(name).free)
        """
        return self.system.space(poolgroup)

    def poolgroups_for_path(self, path: str) -> list[str]:
        """Find the pool group(s) where new files in a directory are stored.

        Only directories are accepted: a file that was moved keeps its
        data in its original pool group, so the result would not be
        reliable for files.

        Args:
            path: dCache path of a directory.

        Returns:
            Names of the pool groups, to use with :meth:`space`.

        Raises:
            AdaValidationError: If the path is a file.
            AdaNotFoundError: If the path does not exist, or no pool
                group could be found for it.
        """
        return self.system.poolgroups_for_path(path)

    def quota(self) -> list[QuotaInfo]:
        """Get the storage quotas of your user and your primary group.

        Returns:
            One :class:`~ada.models.QuotaInfo` per quota that is set,
            with usage and limits in bytes for tape (custodial) and disk
            (replica) storage. Empty if no quota is set.
        """
        return self.system.quota()

    # ---- Token ----

    def view_token(self) -> dict:
        """Decode the current token, to see its properties.

        The token is decoded locally; its signature is not checked.

        Returns:
            The claims of an OIDC token (e.g. ``sub``, ``iss``,
            ``scope``, with ``exp``/``iat``/``nbf`` as ISO 8601 dates),
            or the caveats of a macaroon (e.g. ``before``, ``path``,
            ``activity``, ``ip``).

        Raises:
            AdaAuthError: If the client does not use token
                authentication, or the token can't be decoded.

        Example::

            print(client.view_token().get("activity"))
        """
        return self.auth.view_token()

    # ---- Lifecycle ----

    def close(self) -> None:
        """Close the network connections.

        Not needed when the client is used as a context manager
        (``with AdaClient(...) as client:``).
        """
        self._api.close()

    def __enter__(self) -> AdaClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
