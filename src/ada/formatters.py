"""Output formatting utilities for the CLI.

Provides human-readable formatting of file listings, space info, etc.
"""

from __future__ import annotations

from ada.models import FileInfo
from ada.utils import human_readable_size


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
            parts.append(human_readable_size(info.size))
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
        result.append("\t".join(word.ljust(col_width[idx]) for idx,word in enumerate(row)))

    return result
