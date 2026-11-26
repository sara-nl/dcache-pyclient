"""Event service: receiving dCache events and managing event channels.

dCache can report changes in the namespace (inotify events) as
Server-Sent Events (SSE) on an event channel. This service creates and
reuses channels, subscribes them to paths, and streams the events. ADA
keeps the names of channels and the last received event in
``~/.ada/channels`` (see :class:`AdaState`), so a stream can be resumed.

Not yet available through :class:`~ada.client.AdaClient`.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Iterator, Optional
from pathlib import Path
import re

from ada.exceptions import AdaAPIError
from ada.models import Channel


if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.services.events")


class EventService:
    """Event streaming and channel management for dCache.

    Args:
        api: Client for the dCache REST API.
        state: Where channel names and event IDs are kept. Defaults to
            ``~/.ada``.
    """

    def __init__(self, api: DcacheAPI, state: Optional[AdaState] = None) -> None:
        self._api = api
        self._state = state or AdaState()

    def subscribe(
        self,
        channel_name: str,
        path: str,
        recursive: bool = False,
        resume: bool = False,
        force: bool = False,
        timeout: int = 3600,
    ) -> Iterator[dict[str, Any]]:
        """Subscribe to inotify events on a path.

        Creates (or reuses) an event channel, adds a subscription for
        inotify events, then streams events via SSE.

        Args:
            channel_name: Name for the channel, to reuse it later.
            path: dCache path to watch.
            recursive: Also watch subdirectories.
            resume: Continue after the last event received earlier on
                this channel.
            force: Create a new channel even if one with this name exists.
            timeout: Close the connection when no data arrives for this
                many seconds.

        Yields:
            Each event as a dict, with the keys ``event`` (the event
            type) and ``id``, and the fields of the event data. Heartbeat
            (``SYSTEM``) events are skipped.

        Raises:
            AdaAPIError: If the channel or subscription can't be created,
                or the stream fails.
        """
        channel = self._get_or_create_channel(channel_name, force=force)
        channel_id = channel.channel_id

        # Add inotify subscription
        self._add_subscription(channel_id, path, "inotify", recursive=recursive)

        # Determine resume point
        last_event_id: Optional[str] = None
        if resume:
            last_event_id = self._state.get_last_event_id(channel_id)
            if last_event_id:
                logger.info("Resuming from event ID: %s", last_event_id)

        # Stream events
        yield from self._stream_events(channel_id, last_event_id, timeout)

    def report_staged(
        self,
        channel_name: str,
        path: str,
        recursive: bool = False,
        timeout: int = 3600,
    ) -> Iterator[dict[str, Any]]:
        """Watch a path for changes, to follow staging progress.

        Reuses the channel with this name if it exists. Currently
        subscribes to the same inotify events as :meth:`subscribe`,
        without resuming.

        Args:
            channel_name: Name for the channel, to reuse it later.
            path: dCache path to watch.
            recursive: Also watch subdirectories.
            timeout: Close the connection when no data arrives for this
                many seconds.

        Yields:
            Each event as a dict, like :meth:`subscribe`.

        Raises:
            AdaAPIError: If the channel or subscription can't be created,
                or the stream fails.
        """
        channel = self._get_or_create_channel(channel_name)
        channel_id = channel.channel_id

        # Subscribe to inotify events with IN_ATTRIB mask for locality changes
        self._add_subscription(channel_id, path, "inotify", recursive=recursive)

        yield from self._stream_events(channel_id, None, timeout)

    def list_channels(self, name: Optional[str] = None) -> Any:
        """List your event channels, or get one by name.

        Channels that ADA knows a name for get a ``local_name`` field.

        Args:
            name: If given, return only the channel with this name.

        Returns:
            The channels as dCache reports them. With ``name``, the
            matching channel, or all channels if it isn't found.
        """
        data = self._api.get("events/channels")

        if name:
            # Find channel by name from local state
            channel_id = self._state.find_channel_id_by_name(name)
            if channel_id and isinstance(data, list):
                for ch in data:
                    ch_id = str(ch.get("id", ""))
                    if ch_id == channel_id:
                        ch["local_name"] = name
                        return ch
            # Try matching by API-side data
            if isinstance(data, list):
                return list(data)
            return data

        # Enrich with local channel names
        if isinstance(data, list):
            for ch in data:
                ch_id = str(ch.get("id", ""))
                local_name = self._state.get_channel_name(ch_id)
                if local_name:
                    ch["local_name"] = local_name
        return data

    def delete_channel(self, name: str) -> None:
        """Delete an event channel, in dCache and in ADA's local state.

        Args:
            name: Name of the channel, or its ID.

        Raises:
            AdaAPIError: If no channel with this name or ID exists.
        """
        channel_id = self._state.find_channel_id_by_name(name)
        if channel_id:
            try:
                self._api.delete(f"events/channels/{channel_id}")
            except Exception as exc:
                logger.warning("Could not delete channel %s from API: %s", channel_id, exc)
            self._state.delete_channel_files(channel_id)
        else:
            # Try deleting by name directly (maybe it's an ID)
            try:
                self._api.delete(f"events/channels/{name}")
            except Exception as exc:
                raise AdaAPIError(
                    f"Channel '{name}' not found. Use 'ada channels' to list available channels."
                ) from exc

    # ---- Internal ----

    def _get_or_create_channel(
        self, name: str, force: bool = False
    ) -> Channel:
        """Get an existing channel by name or create a new one."""
        if not force:
            existing_id = self._state.find_channel_id_by_name(name)
            if existing_id:
                logger.info("Reusing existing channel '%s' (ID: %s)", name, existing_id)
                return Channel(
                    channel_id=existing_id,
                    channel_url=f"events/channels/{existing_id}",
                    name=name,
                )

        # Create new channel
        data = self._api.post("events/channels", json={})
        if isinstance(data, dict):
            channel_id = str(data.get("id", ""))
            channel_url = data.get("url", f"events/channels/{channel_id}")
        else:
            # Response might be a Location header redirect
            channel_id = str(data) if data else ""
            channel_url = f"events/channels/{channel_id}"

        if not channel_id:
            raise AdaAPIError("Failed to create event channel: no ID returned.")

        self._state.save_channel_name(channel_id, name)
        logger.info("Created channel '%s' (ID: %s)", name, channel_id)

        return Channel(
            channel_id=channel_id,
            channel_url=channel_url,
            name=name,
        )

    def _add_subscription(
        self,
        channel_id: str,
        path: str,
        event_type: str = "inotify",
        recursive: bool = False,
    ) -> None:
        """Add an event subscription to a channel."""
        body: dict[str, Any] = {
            "path": path,
        }
        if recursive:
            # For inotify, recursive means watching subdirectories too
            body["flags"] = "IN_CREATE,IN_DELETE,IN_MODIFY,IN_MOVE,IN_ATTRIB"

        try:
            self._api.post(
                f"events/channels/{channel_id}/subscriptions/{event_type}",
                json=body,
            )
        except AdaAPIError as exc:
            if exc.status_code == 409:
                logger.info("Subscription already exists for path '%s'", path)
            else:
                raise

    def _stream_events(
        self,
        channel_id: str,
        last_event_id: Optional[str],
        timeout: int,
    ) -> Iterator[dict[str, Any]]:
        """Stream SSE events from a channel."""
        for raw_event in self._api.stream_sse(
            f"events/channels/{channel_id}",
            last_event_id=last_event_id,
            timeout=timeout,
        ):
            event_type = raw_event.get("event", "")
            event_id = raw_event.get("id")
            data_str = raw_event.get("data", "")

            # Parse event data (JSON)
            event_data: dict[str, Any] = {}
            if data_str:
                try:
                    event_data = json.loads(data_str)
                except json.JSONDecodeError:
                    event_data = {"raw": data_str}

            # Save last event ID for resume support
            if event_id:
                self._state.save_last_event_id(channel_id, event_id)

            # Build output event
            output = {
                "event": event_type,
                "id": event_id,
                **event_data,
            }

            # Skip SYSTEM heartbeat events
            if event_type == "SYSTEM":
                logger.debug("Heartbeat: %s", data_str)
                continue

            yield output


class AdaState:
    """ADA's local state: names of event channels, the last event received
    on each channel, and a log of requests.

    Creates the state directory (readable only by you) if it doesn't
    exist.

    Args:
        base_dir: The state directory. Defaults to ``~/.ada``.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir or Path.home() / ".ada")
        self.channels_dir = self.base_dir / "channels"
        self.requests_log = self.base_dir / "requests.log"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create state directories if they don't exist."""
        self.base_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.channels_dir.mkdir(mode=0o700, exist_ok=True)
        if not self.requests_log.exists():
            self.requests_log.touch(mode=0o600)

    # ---- Channel State ----

    def get_channel_name(self, channel_id: str) -> Optional[str]:
        """Get the name ADA gave a channel.

        Args:
            channel_id: ID of the channel.

        Returns:
            The name, or None if ADA doesn't know the channel.
        """
        path = self.channels_dir / f"channel-name-{channel_id}"
        if path.exists():
            return path.read_text().strip()
        return None

    def save_channel_name(self, channel_id: str, name: str) -> None:
        """Remember the name of a channel.

        Args:
            channel_id: ID of the channel.
            name: Name for the channel.
        """
        path = self.channels_dir / f"channel-name-{channel_id}"
        path.write_text(name)

    def get_last_event_id(self, channel_id: str) -> Optional[str]:
        """Get the ID of the last event received on a channel.

        Args:
            channel_id: ID of the channel.

        Returns:
            The event ID, or None if no event was saved.
        """
        path = self.channels_dir / f"channel-status-{channel_id}"
        if path.exists():
            match = re.search(r"\d+", path.read_text())
            return match.group(0) if match else None
        return None

    def save_last_event_id(self, channel_id: str, event_id: str) -> None:
        """Remember the last event received on a channel, to resume later.

        Args:
            channel_id: ID of the channel.
            event_id: ID of the event.
        """
        path = self.channels_dir / f"channel-status-{channel_id}"
        path.write_text(event_id)

    def find_channel_id_by_name(self, name: str) -> Optional[str]:
        """Find the ID of a channel by its name.

        Args:
            name: Name of the channel.

        Returns:
            The channel ID, or None if no channel has this name.
        """
        for path in self.channels_dir.glob("channel-name-*"):
            if path.read_text().strip() == name:
                return path.name.replace("channel-name-", "")
        return None

    def delete_channel_files(self, channel_id: str) -> None:
        """Forget a channel: remove its name and last event ID.

        Args:
            channel_id: ID of the channel.
        """
        for prefix in ("channel-name-", "channel-status-"):
            path = self.channels_dir / f"{prefix}{channel_id}"
            path.unlink(missing_ok=True)

    def list_channels(self) -> list[dict[str, str]]:
        """List the channels that ADA knows a name for.

        Returns:
            For each channel, a dict with ``id``, ``name`` and
            ``last_event_id`` (``"none"`` if no event was saved).
        """
        channels: list[dict[str, str]] = []
        for path in sorted(self.channels_dir.glob("channel-name-*")):
            channel_id = path.name.replace("channel-name-", "")
            name = path.read_text().strip()
            last_event = self.get_last_event_id(channel_id) or "none"
            channels.append({
                "id": channel_id,
                "name": name,
                "last_event_id": last_event,
            })
        return channels

    # ---- Request Logging ----

    def log_request(self, lines: list[str]) -> None:
        """Add lines to the request log (``requests.log``).

        Args:
            lines: The lines to add.
        """
        with self.requests_log.open("a") as f:
            for line in lines:
                f.write(line + "\n")
