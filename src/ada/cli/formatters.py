"""Output formatting utilities for the CLI.

Provides human-readable formatting of file listings, space info, etc.
"""

from __future__ import annotations

from typing import Optional

from ada.models import FileInfo, QuotaInfo


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


def format_quota(quotas: list[QuotaInfo]) -> list[str]:
    """Format quota entries as an aligned table (with header row).

    Columns: quota (type:id), custodial (tape) usage/limit/percentage,
    replica (disk) usage/limit/percentage.
    """
    header = [
        "Quota", "custodial (tape)", "custodialLimit", "%",
        "replica (disk)", "replicaLimit", "%",
    ]
    rows = [header]
    for q in quotas:
        rows.append([
            f"{q.quota_type}:{q.id}",
            str(q.custodial),
            str(q.custodial_limit) if q.custodial_limit is not None else "-",
            _percentage(q.custodial, q.custodial_limit),
            str(q.replica),
            str(q.replica_limit) if q.replica_limit is not None else "-",
            _percentage(q.replica, q.replica_limit),
        ])

    col_width = [max(len(row[i]) for row in rows) for i in range(len(header))]
    return [
        "\t".join(cell.ljust(col_width[i]) for i, cell in enumerate(row))
        for row in rows
    ]


def _percentage(value: int, limit: Optional[int]) -> str:
    if not limit:
        return "-"
    return f"{value / limit * 100:.1f}%"
