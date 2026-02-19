"""Data models for ADA.

All models are frozen dataclasses representing dCache API entities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class FileType(str, Enum):
    REGULAR = "REGULAR"
    DIR = "DIR"
    LINK = "LINK"


class Locality(str, Enum):
    ONLINE = "ONLINE"
    NEARLINE = "NEARLINE"
    ONLINE_AND_NEARLINE = "ONLINE_AND_NEARLINE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Checksum:
    """File checksum."""

    path: str
    checksum_type: str  # "ADLER32" or "MD5_TYPE"
    value: str


@dataclass(frozen=True)
class FileInfo:
    """Represents a file or directory in dCache."""

    path: str
    file_type: FileType
    size: Optional[int] = None
    mtime: Optional[datetime] = None
    pnfs_id: Optional[str] = None
    current_qos: Optional[str] = None
    target_qos: Optional[str] = None
    locality: Optional[Locality] = None
    labels: tuple[str, ...] = ()
    extended_attributes: dict[str, str] = field(default_factory=dict)
    checksums: tuple[Checksum, ...] = ()


@dataclass(frozen=True)
class BulkRequest:
    """Result of a bulk (stage/unstage) operation."""

    request_id: str
    request_url: str
    activity: str
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class BulkRequestStatus:
    """Status of a bulk request."""

    uid: str
    status: str
    targets: tuple[dict, ...] = ()  # type: ignore[type-arg]
    raw: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass(frozen=True)
class UserInfo:
    """User identity from whoami."""

    status: str
    uid: Optional[int] = None
    gids: tuple[int, ...] = ()
    username: Optional[str] = None
    home: Optional[str] = None
    root: Optional[str] = None
    raw: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass(frozen=True)
class SpaceInfo:
    """Pool group space information."""

    total: int
    free: int
    precious: int
    removable: int


@dataclass(frozen=True)
class QuotaInfo:
    """Storage quota information."""

    quota_type: str  # "user" or "group"
    id: int
    custodial: int
    custodial_limit: Optional[int]
    replica: int
    replica_limit: Optional[int]


@dataclass(frozen=True)
class Channel:
    """SSE event channel."""

    channel_id: str
    channel_url: str
    name: Optional[str] = None
    timeout: Optional[int] = None


@dataclass(frozen=True)
class Subscription:
    """SSE event subscription within a channel."""

    subscription_id: str
    event_type: str
    path: str


@dataclass(frozen=True)
class SSEEvent:
    """A parsed Server-Sent Event."""

    event_type: str  # "inotify" or "SYSTEM"
    event_id: Optional[str] = None
    path: Optional[str] = None
    object_name: Optional[str] = None
    mask: Optional[str] = None
    cookie: Optional[str] = None
    raw_data: Optional[dict] = None  # type: ignore[type-arg]