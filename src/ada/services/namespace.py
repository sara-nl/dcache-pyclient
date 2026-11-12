"""Namespace service: file and directory operations on dCache.

Handles list, longlist, stat, mkdir, mv and delete, and has helper
methods, also used by other services, to check the type of a path and
to walk through directories.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Optional

from ada.exceptions import AdaNotFoundError, AdaPathError, AdaValidationError
from ada.models import Checksum, FileInfo, FileType, Locality
from ada.utils import encode_path, resolve_paths, confirm_deletion

if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.services.namespace")

#: Maximum number of directory levels that a recursive mkdir creates at once.
MAX_RECURSIVE_MKDIR = 10


class NamespaceService:
    """File and directory operations on the dCache namespace.

    Args:
        api: Client for the dCache REST API.
    """

    def __init__(self, api: DcacheAPI) -> None:
        self._api = api

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
        """
        file_type = self.get_file_type(path)
        if file_type == FileType.DIR:
            data = self._api.get(
                f"namespace/{self._enc(path)}", params={"children": "true"}
            )
            result = []
            for child in data.get("children", []):
                name = child["fileName"]
                if child["fileType"] == "DIR":
                    name += "/"
                result.append(name)
            return sorted(result)
        return [path.rsplit("/", 1)[-1]]

    def longlist(
            self,
            paths: Optional[str | list[str]] = None,
            from_file: Optional[str] = None
            ) -> list[FileInfo]:
        """Get details (size, modification time, QoS, locality) of files.

        For a directory, its files and subdirectories are listed (not
        recursively). Give either ``paths`` or ``from_file``.

        Args:
            paths: dCache path, or list of paths, of files or directories.
            from_file: Local file with one dCache path per line.

        Returns:
            A :class:`~ada.models.FileInfo` for each file or subdirectory.

        Raises:
            AdaValidationError: If both or neither of ``paths`` and
                ``from_file`` are given, or ``from_file`` contains no
                paths.
            AdaNotFoundError: If a path does not exist.
        """

        # Get list of paths
        target_paths = resolve_paths(paths, from_file)

        results: list[FileInfo] = []
        for path in target_paths:
            file_type = self.get_file_type(path)
            if file_type == FileType.DIR:
                data = self._api.get(
                    f"namespace/{self._enc(path)}",
                    params={"children": "true", "locality": "true", "qos": "true"},
                )
                for child in data.get("children", []):
                    results.append(self._parse_file_info(child, parent=path))
            else:
                data = self._api.get(
                    f"namespace/{self._enc(path)}",
                    params={"locality": "true", "qos": "true"},
                )
                results.append(self._parse_file_info(data, explicit_path=path))
        return results

    def stat(self, path: str) -> dict:
        """Get all metadata of a file or directory, as dCache returns it.

        Returns the full API response as-is (locality, locations, QoS,
        xattr, labels, checksums, storage class/HSM, access latency,
        retention policy, ownership/timestamps, etc.) rather than a
        curated subset, so fields a future dCache version adds show up
        automatically.

        Args:
            path: dCache path of a file or directory.

        Returns:
            The metadata, with dCache's field names.

        Raises:
            AdaNotFoundError: If the path does not exist.
        """
        return self._api.get(
            f"namespace/{self._enc(path)}",
            params={
                "locality": "true",
                "locations": "true",
                "qos": "true",
                "xattr": "true",
                "labels": "true",
                "checksum": "true",
                "optional": "true",
            },
        )

    def mkdir(self, path: str, recursive: bool = False, _depth: int = 0) -> str:
        """Create a directory.

        Args:
            path: dCache path of the directory to create.
            recursive: Also create missing parent directories, at most
                :data:`MAX_RECURSIVE_MKDIR` levels at once.

        Returns:
            ``"created"``, or ``"already exists"`` if the directory
            already existed.

        Raises:
            AdaValidationError: If more than :data:`MAX_RECURSIVE_MKDIR`
                directory levels would have to be created.
            AdaPathError: If the parent does not exist and ``recursive``
                is False.
        """
        if _depth > MAX_RECURSIVE_MKDIR:
            raise AdaValidationError(
                f"Maximum number of directories that can be created at once "
                f"is {MAX_RECURSIVE_MKDIR}."
            )

        # Check if already exists
        try:
            ft = self.get_file_type(path)
            if ft == FileType.DIR:
                return "already exists"
        except (AdaNotFoundError, Exception):
            pass

        parent = str(PurePosixPath(path).parent)
        name = PurePosixPath(path).name

        # Check parent exists
        try:
            self.get_file_type(parent)
        except Exception as exc:
            if recursive and len(parent) > 1:
                logger.info("Parent dir '%s' does not exist. Creating it.", parent)
                self.mkdir(parent, recursive=True, _depth=_depth + 1)
            else:
                raise AdaPathError(
                    f"Parent directory '{parent}' does not exist. "
                    f"Use --recursive to create it."
                ) from exc

        self._api.post(
            f"namespace/{self._enc(parent)}",
            json={"action": "mkdir", "name": name},
        )
        return "created"

    def mv(self, source: str, destination: str) -> str:
        """Move or rename a file or directory.

        Args:
            source: Current dCache path.
            destination: New dCache path. Must not exist yet.

        Returns:
            ``"moved"``.

        Raises:
            AdaPathError: If the destination already exists.
            AdaNotFoundError: If the source does not exist.
        """
        try:
            self.get_file_type(destination)
            raise AdaPathError(f"Target '{destination}' already exists.")
        except AdaNotFoundError:
            pass  # Expected — destination should not exist
        except AdaPathError:
            raise

        self._api.post(
            f"namespace/{self._enc(source)}",
            json={"action": "mv", "destination": destination},
        )
        return "moved"

    def delete(
        self, path: str, recursive: bool = False, force: bool = False
    ) -> None:
        """Delete a file or directory.

        Args:
            path: dCache path of a file or directory.
            recursive: Required to delete a directory: deletes the
                directory with all its contents.
            force: Don't ask on the terminal for confirmation before
                each subdirectory is deleted.

        Raises:
            AdaPathError: If the path is a directory and ``recursive``
                is False.
            AdaNotFoundError: If the path does not exist.
            SystemExit: If the user does not confirm the deletion.
        """

        """Recursively delete all children then the directory itself."""

        file_type = self.get_file_type(path)
        if file_type == FileType.DIR:
            if not recursive:     
                raise AdaPathError(
                    f"'{path}' is a directory, use --recursive to delete it."
                )
            base = path.rstrip("/")
            data = self._api.get(
                f"namespace/{self._enc(path)}", params={"children": "true"}
            )
            # delete children
            for child in data.get("children", []):
                child_path = f"{base}/{child['fileName']}"
                if child["fileType"] == FileType.REGULAR:
                    self._delete_single(child_path)
                elif child["fileType"] == FileType.DIR:
                    if not force:
                        # prompt confirmation of deletion
                        if confirm_deletion(path):
                            self.delete(child_path, recursive, force)
                        else:
                            raise SystemExit(f"Deleting '{path}' aborted.")                    
                    else:
                        # delete all children recursively
                        self.delete(child_path, recursive, force)
            # delete empty dir
            self._delete_single(path)            
        else:
            # delete file
            self._delete_single(path)


    # ---- Helper Methods (also used by other services) ----

    def get_file_type(self, path: str) -> FileType:
        """Get the type of a path: file, directory or link.

        Args:
            path: dCache path.

        Returns:
            The type.

        Raises:
            AdaNotFoundError: If the path does not exist.
            AdaPathError: If dCache does not report a type.
        """
        data = self._api.get(f"namespace/{self._enc(path)}")
        if isinstance(data, dict) and "fileType" in data:
            return FileType(data["fileType"])
        raise AdaPathError(f"Cannot determine file type for '{path}'")

    def is_dir(self, path: str) -> bool:
        """Check whether a path is a directory.

        Args:
            path: dCache path.

        Returns:
            True for a directory. False for anything else, including a
            path that doesn't exist or can't be checked.
        """
        try:
            return self.get_file_type(path) == FileType.DIR
        except Exception:
            return False

    def is_online(self, path: str) -> bool:
        """Check whether a file is online, i.e. on disk and not only on tape.

        Args:
            path: dCache path of a file.

        Returns:
            True if the file's locality includes ``ONLINE``.

        Raises:
            AdaNotFoundError: If the path does not exist.
        """
        data = self._api.get(
            f"namespace/{self._enc(path)}",
            params={"locality": "true", "qos": "true"},
        )
        locality = data.get("fileLocality", "")
        return "ONLINE" in locality

    def get_pnfs_id(self, path: str) -> str:
        """Get dCache's internal ID (PNFS ID) of a file or directory.

        Args:
            path: dCache path.

        Returns:
            The PNFS ID, or an empty string if dCache doesn't report one.

        Raises:
            AdaNotFoundError: If the path does not exist.
        """
        data = self._api.get(f"namespace/{self._enc(path)}")
        return data.get("pnfsId", "")

    def get_subdirs(self, path: str) -> list[str]:
        """Get the names of the subdirectories in a directory.

        Args:
            path: dCache path of a directory.

        Returns:
            The names, without the directory path.

        Raises:
            AdaNotFoundError: If the path does not exist.
        """
        data = self._api.get(
            f"namespace/{self._enc(path)}", params={"children": "true"}
        )
        return [
            child["fileName"]
            for child in data.get("children", [])
            if child.get("fileType") == "DIR"
        ]

    def get_files_in_dir(self, path: str) -> list[str]:
        """Get the names of the files in a directory.

        Args:
            path: dCache path of a directory.

        Returns:
            The names of the regular files (not subdirectories or
            links), without the directory path.

        Raises:
            AdaNotFoundError: If the path does not exist.
        """
        data = self._api.get(
            f"namespace/{self._enc(path)}", params={"children": "true"}
        )
        return [
            child["fileName"]
            for child in data.get("children", [])
            if child.get("fileType") == "REGULAR"
        ]

    def with_files_in_dir(
        self, path: str, recursive: bool = False
    ) -> list[str]:
        """Get the full paths of the files in a directory.

        Args:
            path: dCache path of a directory.
            recursive: Also include the files in subdirectories.

        Returns:
            The paths of the regular files.

        Raises:
            AdaNotFoundError: If the path does not exist.
        """
        files: list[str] = []
        base = path.rstrip("/")
        for fname in self.get_files_in_dir(path):
            files.append(f"{base}/{fname}")
        if recursive:
            for subdir in self.get_subdirs(path):
                subpath = f"{base}/{subdir}"
                files.extend(self.with_files_in_dir(subpath, recursive=True))
        return files

    # ---- Internal ----

    def _delete_recursive(self, path: str) -> None:
        """Recursively delete all children then the directory itself."""
        base = path.rstrip("/")
        data = self._api.get(
            f"namespace/{self._enc(path)}", params={"children": "true"}
        )
        for child in data.get("children", []):
            child_path = f"{base}/{child['fileName']}"
            if child["fileType"] == "DIR":
                self._delete_recursive(child_path)
            else:
                self._delete_single(child_path)
        self._delete_single(path)

    def _delete_single(self, path: str) -> None:
        """Delete a single file or empty directory."""
        self._api.delete(f"namespace/{self._enc(path)}")

    @staticmethod
    def _enc(path: str) -> str:
        return encode_path(path)

    @staticmethod
    def _parse_file_info(
        data: dict,
        parent: str = "",
        explicit_path: str = "",
    ) -> FileInfo:
        """Parse API response into a FileInfo dataclass."""
        if explicit_path:
            path = explicit_path
        elif parent:
            path = f"{parent.rstrip('/')}/{data['fileName']}"
        else:
            path = data.get("fileName", data.get("path", ""))

        return FileInfo(
            path=path,
            file_type=FileType(data.get("fileType", "REGULAR")),
            size=data.get("size"),
            mtime=NamespaceService._parse_timestamp(data, "mtime"),
            pnfs_id=data.get("pnfsId"),
            current_qos=data.get("currentQos"),
            target_qos=data.get("targetQos"),
            locality=NamespaceService._parse_locality(data),
            labels=tuple(data.get("labels", [])),
            extended_attributes=data.get("extendedAttributes", {}),
            checksums=NamespaceService._parse_checksums(path, data),
        )

    @staticmethod
    def _parse_timestamp(data: dict, key: str) -> Optional[datetime]:
        if key not in data:
            return None
        try:
            return datetime.fromtimestamp(data[key] / 1000, tz=timezone.utc)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _parse_locality(data: dict) -> Optional[Locality]:
        if "fileLocality" not in data:
            return None
        try:
            return Locality(data["fileLocality"])
        except ValueError:
            return None

    @staticmethod
    def _parse_checksums(path: str, data: dict) -> tuple[Checksum, ...]:
        return tuple(
            Checksum(path=path, checksum_type=c.get("type", ""), value=c.get("value", ""))
            for c in data.get("checksums", [])
        )
