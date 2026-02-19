"""Event service — SSE event streaming and channel management.

Handles subscribing to inotify events, monitoring staging progress,
and managing event channels in the dCache API.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Iterator, Optional

from ada.exceptions import AdaAPIError, AdaValidationError
from ada.models import Channel, SSEEvent, Subscription
from ada.state import AdaState
from ada.utils import encode_path

if TYPE_CHECKING:
    from ada.core.api import DcacheAPI

logger = logging.getLogger("ada.services.events")


class EventService:
    """SSE event streaming and channel management for dCache."""

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
            channel_name: Human-readable channel name.
            path: dCache path to watch.
            recursive: If True, watch subdirectories too.
            resume: If True, resume from last processed event.
            force: If True, create a new channel even if one exists.
            timeout: SSE connection timeout in seconds.

        Yields:
            Parsed event dicts from the SSE stream.
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
        """Monitor file locality/QoS changes (staging progress).

        Similar to subscribe but watches for QoS transition events.

        Yields:
            Events related to file staging status changes.
        """
        channel = self._get_or_create_channel(channel_name)
        channel_id = channel.channel_id

        # Subscribe to inotify events with IN_ATTRIB mask for locality changes
        self._add_subscription(channel_id, path, "inotify", recursive=recursive)

        yield from self._stream_events(channel_id, None, timeout)

    def list_channels(self, name: Optional[str] = None) -> Any:
        """List event channels.

        Args:
            name: If specified, return details for this channel.
                Otherwise, return all channels.

        Returns:
            Channel details dict or list of channels.
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
                return [ch for ch in data]
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
        """Delete an event channel by name.

        Removes both the API-side channel and local state files.
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
