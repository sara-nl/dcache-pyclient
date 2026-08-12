"""System service — whoami, space, and quota operations.

Provides user identity, storage space, and quota information.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ada.models import QuotaInfo, SpaceInfo, UserInfo

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

    def quota(self) -> list[QuotaInfo]:
        """Get storage quota information for the current user.

        Returns a list of quota entries (user and group quotas,
        for both disk and tape storage).
        """
        data = self._api.get("quota")
        quotas: list[QuotaInfo] = []

        if isinstance(data, list):
            for item in data:
                quotas.append(
                    QuotaInfo(
                        quota_type=item.get("type", "unknown"),
                        id=item.get("id", 0),
                        custodial=item.get("custodial", 0),
                        custodial_limit=item.get("custodialLimit"),
                        replica=item.get("replica", 0),
                        replica_limit=item.get("replicaLimit"),
                    )
                )
        elif isinstance(data, dict):
            # Some API versions return a dict with user/group keys
            for qtype in ("user", "group"):
                if qtype in data:
                    for entry in data[qtype]:
                        quotas.append(
                            QuotaInfo(
                                quota_type=qtype,
                                id=entry.get("id", 0),
                                custodial=entry.get("custodial", 0),
                                custodial_limit=entry.get("custodialLimit"),
                                replica=entry.get("replica", 0),
                                replica_limit=entry.get("replicaLimit"),
                            )
                        )

        return quotas
