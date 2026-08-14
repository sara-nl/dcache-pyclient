"""Output formatting utilities for the CLI.

Provides human-readable formatting of file listings, space info, etc.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator, Optional

from ada.models import FileInfo


def format_longlist(files: list[FileInfo]) -> list[str]:
    """Format a list of FileInfo objects for longlist output.

    Returns tab-separated lines with: path, size, modified, QoS, locality.
    """
    lines: list[str] = []

    for info in files:
        parts: list[str] = []

        # File type indicator
        if info.file_type.value == "DIR":
            parts.append(f"{info.path}/")
        else:
            parts.append(info.path)

        # Size
        if info.size is not None:
            parts.append(str(info.size))
        else:
            parts.append("-")

        # Modified time
        if info.mtime:
            parts.append(info.mtime.strftime("%Y-%m-%d %H:%M UTC"))
        else:
            parts.append("-")

        # QoS
        qos = info.current_qos or "-"
        if info.target_qos:
            qos += f" -> {info.target_qos}"
        parts.append(qos)

        # Locality
        parts.append(info.locality.value if info.locality else "-")

        lines.append(parts)

    # get maxmum width of each column
    cols = []
    for i in range(0, len(lines)):
        cols.append([len(word) for word in lines[:][i]])
    col_width = [max(idx) for idx in zip(*cols)]

    result = []
    for row in lines:
        result.append("\t".join(word.ljust(col_width[idx]) for idx, word in enumerate(row)))

    return result


def format_stat(data: dict) -> list[str]:
    """Format complete, raw file/directory metadata as key: value lines.

    Every field in the API response is shown -- nested objects are
    flattened to dotted keys (e.g. 'storageInfo.hsm'), lists of objects
    to indexed dotted keys (e.g. 'checksums[0].type') -- so fields a
    future dCache version adds show up automatically, with no curation.
    """
    rows = list(_flatten(data))
    label_width = max(len(key) for key, _ in rows) + 2
    return [f"{key + ':':<{label_width}}{value}" for key, value in rows]


def _flatten(data: dict, prefix: str = "") -> Iterator[tuple[str, str]]:
    for key, value in data.items():
        full_key = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _flatten(value, prefix=f"{full_key}.")
        elif isinstance(value, list):
            if not value:
                yield full_key, "-"
            elif all(isinstance(item, dict) for item in value):
                for i, item in enumerate(value):
                    yield from _flatten(item, prefix=f"{full_key}[{i}].")
            else:
                yield full_key, ", ".join(str(item) for item in value)
        else:
            yield full_key, _format_scalar(full_key, value)


def _format_scalar(key: str, value: object) -> str:
    # Any integer field whose name contains "time" is assumed to be a
    # dCache epoch-milliseconds timestamp (mtime, ctime, atime,
    # creationTime, and whatever future fields follow the same
    # convention); show the formatted date alongside the raw value.
    if isinstance(value, int) and not isinstance(value, bool) and "time" in key.lower():
        formatted = _format_epoch_millis(value)
        if formatted:
            return f"{value} ({formatted})"
    return str(value)


def _format_epoch_millis(value: int) -> Optional[str]:
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return None
