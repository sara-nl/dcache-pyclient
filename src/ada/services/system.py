"""System service — whoami, space, and quota operations.

Provides user identity, storage space, and quota information.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ada.exceptions import AdaNotFoundError
from ada.models import QuotaInfo, SpaceInfo, UserInfo
from ada.utils import encode_path

if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.services.system")


class SystemService:
    """System information from the dCache API."""

    def __init__(self, api: DcacheAPI) -> None:
        self._api = api

    def whoami(self) -> UserInfo:
        """Get the authenticated user's identity.

        Returns user info including UID, GIDs, username, home directory,
        and the dCache version.
        """
        data = self._api.get("user")
        return UserInfo(
            status=data.get("status", ""),
            uid=data.get("uid"),
            gids=tuple(data.get("gids", [])),
            username=data.get("username"),
            home=data.get("homeDirectory") or data.get("home"),
            root=data.get("rootDirectory") or data.get("root"),
            raw=data,
        )

    def check_authenticated(self) -> bool:
        """Check if the user is authenticated by calling the user endpoint.

        Returns True if authenticated, raises on failure.
        """
        data = self._api.get("user")
        status = data.get("status", "")
        if status == "ANONYMOUS":
            return False
        return True

    def space(self, poolgroup: Optional[str] = None) -> SpaceInfo | list[str]:
        """Get storage space information.

        Args:
            poolgroup: If specified, return space info for this pool group.
                If None, return a list of available pool group names.

        Returns:
            SpaceInfo for a specific pool group, or list of pool group names.
        """
        if poolgroup:
            data = self._api.get(f"poolgroups/{poolgroup}/space")
            group_space = data.get("groupSpaceData", {})
            return SpaceInfo(
                total=group_space.get("total", 0),
                free=group_space.get("free", 0),
                precious=group_space.get("precious", 0),
                removable=group_space.get("removable", 0),
            )
        # List all pool groups
        data = self._api.get("poolgroups")
        return [item.get("name", str(item)) for item in data]

    def poolgroups_for_path(self, path: str) -> list[str]:
        """Resolve which pool group(s) serve a namespace path.

        Follows the same chain dCache itself uses to pick a pool group
        for a path: storage class + HSM identify a storage unit, which
        belongs to a unit group, which is attached to link(s), which
        are attached to pool group(s).

        Raises:
            AdaNotFoundError: If the path has no storage class/HSM, or
                no unit group/link/pool group could be found for it.
        """
        info = self._api.get(f"namespace/{encode_path(path)}", params={"optional": "true"})
        storage_class = info.get("storageClass")
        hsm = info.get("hsm")
        if not storage_class or not hsm:
            raise AdaNotFoundError(f"No storage class/HSM found for '{path}'.")
        unit = f"{storage_class}@{hsm}"

        link_names: list[str] = []
        for group in self._api.get("units/groups"):
            if unit in group.get("units", []):
                for link in group.get("links", []):
                    if link not in link_names:
                        link_names.append(link)
        if not link_names:
            raise AdaNotFoundError(
                f"No link found for storage unit '{unit}' (path '{path}')."
            )

        poolgroups: list[str] = []
        for link in self._api.get("links"):
            if link.get("name") in link_names:
                for poolgroup in link.get("poolGroups", []):
                    if poolgroup not in poolgroups:
                        poolgroups.append(poolgroup)
        if not poolgroups:
            raise AdaNotFoundError(
                f"No pool group found for path '{path}' (unit '{unit}')."
            )

        return poolgroups

    def quota(self) -> list[QuotaInfo]:
        """Get storage quota information for the current user and their
        primary group.

        Queries user and group quota separately, since dCache returns
        a 404 for a quota type that simply isn't set (not an error) --
        matching the Bash version.

        Returns:
            A list of quota entries (user and/or group, for both
            custodial/tape and replica/disk storage). Empty if neither
            the user nor the group has any quota set.
        """
        quotas: list[QuotaInfo] = []
        for quota_type in ("user", "group"):
            try:
                data = self._api.get(f"quota/{quota_type}", params={"user": "true"})
            except AdaNotFoundError:
                continue
            for item in data:
                quotas.append(
                    QuotaInfo(
                        quota_type=quota_type,
                        id=item.get("id", 0),
                        custodial=item.get("custodial", 0),
                        custodial_limit=item.get("custodialLimit"),
                        replica=item.get("replica", 0),
                        replica_limit=item.get("replicaLimit"),
                    )
                )
        return quotas
