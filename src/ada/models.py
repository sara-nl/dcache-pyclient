"""Data models for ADA.

The :class:`~ada.client.AdaClient` methods return these objects. They
are frozen (read-only) dataclasses. Sizes are in bytes and timestamps
are timezone-aware :class:`~datetime.datetime` objects in UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class FileType(str, Enum):
    """Type of an entry in the dCache namespace."""
    REGULAR = "REGULAR"
    DIR = "DIR"
    LINK = "LINK"


class Locality(str, Enum):
    """Where the data of a file is available in dCache.

    ``ONLINE`` means on disk, ready to be read. ``NEARLINE`` means only
    on tape: the file must be staged before it can be read. ``UNAVAILABLE``
    means no copy can be reached at the moment.
    """
    ONLINE = "ONLINE"
    NEARLINE = "NEARLINE"
    ONLINE_AND_NEARLINE = "ONLINE_AND_NEARLINE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Checksum:
    """A checksum that dCache stored for a file."""

    #: dCache path of the file.
    path: str
    #: Checksum algorithm, ``"ADLER32"`` or ``"MD5_TYPE"`` (as dCache
    #: names them).
    checksum_type: str  # "ADLER32" or "MD5_TYPE"
    #: The checksum, as a hexadecimal string.
    value: str


@dataclass(frozen=True)
class FileInfo:
    """A file or directory in dCache, with its details.

    Returned by :meth:`~ada.client.AdaClient.longlist`, which fills in
    the size, modification time, QoS and locality. Labels, extended
    attributes and checksums are not requested there and stay empty; use
    :meth:`~ada.client.AdaClient.stat` to get all metadata.
    """

    #: dCache path.
    path: str
    #: File, directory or symbolic link.
    file_type: FileType
    #: Size in bytes.
    size: Optional[int] = None
    #: Last modification time, in UTC.
    mtime: Optional[datetime] = None
    #: dCache's internal ID of the file (PNFS ID).
    pnfs_id: Optional[str] = None
    #: Current quality of service, e.g. ``"disk"``, ``"tape"`` or
    #: ``"disk+tape"``.
    current_qos: Optional[str] = None
    #: Quality of service the file is being moved to, if a QoS change
    #: is in progress.
    target_qos: Optional[str] = None
    #: Where the data is available (on disk, on tape, or both). Not set
    #: for directories.
    locality: Optional[Locality] = None
    #: Labels attached to the file.
    labels: tuple[str, ...] = ()
    #: Extended attributes of the file.
    extended_attributes: dict[str, str] = field(default_factory=dict)
    #: Checksums stored for the file.
    checksums: tuple[Checksum, ...] = ()


@dataclass(frozen=True)
class TransferResult:
    """Result of an :meth:`~ada.client.AdaClient.upload` or
    :meth:`~ada.client.AdaClient.download`."""

    #: The local file that was uploaded, or the local file that was
    #: written, including the file name when downloading into a
    #: directory.
    local_path: str
    #: The dCache file that was downloaded, or the dCache file that was
    #: written, including the file name when uploading into a directory.
    remote_path: str
    #: ``"uploaded"``, ``"downloaded"``, or ``"already-verified"`` when
    #: the target already existed with the same checksum, so nothing was
    #: transferred.
    status: str  # "uploaded", "downloaded", or "already-verified" (checksum matched, no transfer needed)
    #: Whether the checksum was verified.
    checksum_verified: bool = False


@dataclass(frozen=True)
class BulkRequest:
    """A bulk request created by :meth:`~ada.client.AdaClient.stage` or
    :meth:`~ada.client.AdaClient.unstage`.

    dCache handles the request in the background. Use
    :meth:`~ada.client.AdaClient.stat_request` with the
    :attr:`request_id` to follow its progress.
    """

    #: ID of the request in dCache.
    request_id: str
    #: URL of the request in the dCache REST API.
    request_url: str
    #: ``"PIN"`` for staging, ``"UNPIN"`` for unstaging.
    activity: str
    #: The paths given in the request.
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class BulkRequestStatus:
    """Status of a bulk request, from
    :meth:`~ada.client.AdaClient.stat_request`."""

    #: ID of the request in dCache.
    uid: str
    #: Status of the request as a whole, as dCache reports it, or
    #: ``"UNKNOWN"`` if dCache didn't report one.
    status: str
    #: The status of each file in the request, as dCache reports it.
    targets: tuple[dict, ...] = ()  # type: ignore[type-arg]
    #: The complete API response.
    raw: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass(frozen=True)
class UserInfo:
    """How dCache identifies you, from :meth:`~ada.client.AdaClient.whoami`."""

    #: ``"AUTHENTICATED"`` when dCache accepted the credentials.
    status: str
    #: User ID.
    uid: Optional[int] = None
    #: Group IDs.
    gids: tuple[int, ...] = ()
    #: User name.
    username: Optional[str] = None
    #: Home directory in dCache.
    home: Optional[str] = None
    #: Root directory, the part of the dCache namespace you can see.
    root: Optional[str] = None
    #: The complete API response.
    raw: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass(frozen=True)
class SpaceInfo:
    """Space in a pool group, from :meth:`~ada.client.AdaClient.space`.

    All values are in bytes. The space available for new data is
    ``free + removable``.
    """

    #: Total size of the pool group.
    total: int
    #: Space not in use.
    free: int
    #: Space used by data that still has to be written to tape.
    precious: int
    #: Space used by cached copies that dCache can remove when it needs
    #: room, because the data is also on tape.
    removable: int


@dataclass(frozen=True)
class QuotaInfo:
    """A storage quota, from :meth:`~ada.client.AdaClient.quota`.

    Usage and limits are in bytes. A limit of None means no limit is set
    for that kind of storage.
    """

    #: ``"user"`` or ``"group"``.
    quota_type: str  # "user" or "group"
    #: User ID or group ID that the quota applies to.
    id: int
    #: Tape (custodial) storage in use.
    custodial: int
    #: Tape (custodial) storage limit.
    custodial_limit: Optional[int]
    #: Disk (replica) storage in use.
    replica: int
    #: Disk (replica) storage limit.
    replica_limit: Optional[int]


@dataclass(frozen=True)
class Channel:
    """A channel for receiving dCache events (Server-Sent Events)."""

    #: ID of the channel in dCache.
    channel_id: str
    #: URL of the channel in the dCache REST API.
    channel_url: str
    #: Name that ADA gave the channel, to find it again later.
    name: Optional[str] = None
    #: Timeout of the channel.
    timeout: Optional[int] = None


@dataclass(frozen=True)
class Subscription:
    """A subscription to events for a path, within an event channel."""

    #: ID of the subscription in dCache.
    subscription_id: str
    #: Type of events, e.g. ``"inotify"``.
    event_type: str
    #: dCache path the subscription is for.
    path: str


@dataclass(frozen=True)
class SSEEvent:
    """An event received from dCache (Server-Sent Event)."""

    #: ``"inotify"`` for a change in the namespace, or ``"SYSTEM"``.
    event_type: str  # "inotify" or "SYSTEM"
    #: ID of the event.
    event_id: Optional[str] = None
    #: dCache path the event is about.
    path: Optional[str] = None
    #: Name of the file or directory the event is about.
    object_name: Optional[str] = None
    #: inotify event mask, e.g. ``"IN_CREATE"``.
    mask: Optional[str] = None
    #: inotify cookie, which links the two events of a move.
    cookie: Optional[str] = None
    #: The event data as received.
    raw_data: Optional[dict] = None  # type: ignore[type-arg]
