"""Namespace service — file and directory operations on dCache.

Handles list, longlist, stat, mkdir, mv, delete, and helper functions
for recursive traversal and path type detection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Optional

from ada.exceptions import AdaNotFoundError, AdaPathError, AdaValidationError
from ada.models import Checksum, FileInfo, FileType, Locality
from ada.utils import encode_path, resolve_paths

if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.services.namespace")

MAX_RECURSIVE_MKDIR = 10


class NamespaceService:
    """File and directory operations on the dCache namespace."""

    def __init__(self, api: DcacheAPI) -> None:
        self._api = api

    def list(self, path: str) -> list[str]:
        """List directory contents or return the file path itself.

        For directories, returns sorted child names with '/' appended for subdirs.
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
        """Get detailed file information for one or more paths.

        For directories, lists children with size, mtime, QoS, and locality.
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

    def stat(self, path: str) -> FileInfo:
        """Get complete metadata for a file or directory.

        Includes children, locality, locations, QoS, xattr, labels, checksums.
        """
        data = self._api.get(
            f"namespace/{self._enc(path)}",
            params={
                "children": "true",
                "locality": "true",
                "locations": "true",
                "qos": "true",
                "xattr": "true",
                "labels": "true",
                "checksum": "true",
                "optional": "true",
            },
        )
        return self._parse_file_info(data, explicit_path=path)

    def mkdir(self, path: str, recursive: bool = False, _depth: int = 0) -> str:
        """Create a directory.

        Args:
            path: The directory path to create.
            recursive: If True, create parent directories as needed.

        Returns:
            Status message.

        Raises:
            AdaValidationError: If recursive depth exceeds MAX_RECURSIVE_MKDIR.
            AdaPathError: If parent does not exist and recursive is False.
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

        Raises:
            AdaPathError: If the destination already exists.
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
            path: Path to delete.
            recursive: If True, delete directory contents recursively.
            force: If True, skip confirmation prompts (library usage).

        Raises:
            AdaPathError: If the directory is not empty and recursive is False.
        """
        file_type = self.get_file_type(path)
        if file_type == FileType.DIR:
            children = self._get_children(path)
            if children and not recursive:
                raise AdaPathError(
                    f"Directory '{path}' is not empty ({len(children)} items). "
                    f"Use --recursive to delete it and its contents."
                )
            if children and recursive:
                self._delete_recursive(path)
            else:
                self._delete_single(path)
        else:
            self._delete_single(path)

    # ---- Helper Methods (also used by other services) ----

    def get_file_type(self, path: str) -> FileType:
        """Get the type of a path (DIR, REGULAR, LINK)."""
        data = self._api.get(f"namespace/{self._enc(path)}")
        if isinstance(data, dict) and "fileType" in data:
            return FileType(data["fileType"])
        raise AdaPathError(f"Cannot determine file type for '{path}'")

    def is_dir(self, path: str) -> bool:
        """Check if a path is a directory. Returns False if not found."""
        try:
            return self.get_file_type(path) == FileType.DIR
        except Exception:
            return False

    def is_online(self, path: str) -> bool:
        """Check if a file is online (not only on tape)."""
        data = self._api.get(
            f"namespace/{self._enc(path)}",
            params={"locality": "true", "qos": "true"},
        )
        locality = data.get("fileLocality", "")
        return "ONLINE" in locality

    def get_pnfs_id(self, path: str) -> str:
        """Get the PNFS ID of a file or directory."""
        data = self._api.get(f"namespace/{self._enc(path)}")
        return data.get("pnfsId", "")

    def get_subdirs(self, path: str) -> list[str]:
        """Get subdirectory names within a directory."""
        data = self._api.get(
            f"namespace/{self._enc(path)}", params={"children": "true"}
        )
        return [
            child["fileName"]
            for child in data.get("children", [])
            if child.get("fileType") == "DIR"
        ]

    def get_files_in_dir(self, path: str) -> list[str]:
        """Get regular file names within a directory."""
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
        """Get full paths of all regular files in a directory.

        If recursive, traverses subdirectories.
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

    def _get_children(self, path: str) -> list[str]:
        """Get all child names in a directory."""
        data = self._api.get(
            f"namespace/{self._enc(path)}", params={"children": "true"}
        )
        return [child["fileName"] for child in data.get("children", [])]

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

        mtime = None
        if "mtime" in data:
            try:
                mtime = datetime.fromtimestamp(
                    data["mtime"] / 1000, tz=timezone.utc
                )
            except (OSError, ValueError):
                pass

        locality = None
        if "fileLocality" in data:
            try:
                locality = Locality(data["fileLocality"])
            except ValueError:
                pass

        checksums = tuple(
            Checksum(path=path, checksum_type=c.get("type", ""), value=c.get("value", ""))
            for c in data.get("checksums", [])
        )

        return FileInfo(
            path=path,
            file_type=FileType(data.get("fileType", "REGULAR")),
            size=data.get("size"),
            mtime=mtime,
            pnfs_id=data.get("pnfsId"),
            current_qos=data.get("currentQos"),
            target_qos=data.get("targetQos"),
            locality=locality,
            labels=tuple(data.get("labels", [])),
            extended_attributes=data.get("extendedAttributes", {}),
            checksums=checksums,
        )
