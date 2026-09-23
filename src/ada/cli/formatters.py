"""Output formatting utilities for the CLI.

Provides human-readable formatting of file listings, space info, etc.
"""

from __future__ import annotations

from typing import Optional

from ada.models import FileInfo, QuotaInfo, SpaceInfo


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
    replica (disk) usage/limit/percentage. Numeric columns are
    right-aligned with space-separated thousands.
    """
    header = [
        "Quota", "custodial (tape)", "custodialLimit", "%",
        "replica (disk)", "replicaLimit", "%",
    ]
    right_cols = {1, 2, 3, 4, 5, 6}

    rows = [header]
    for q in quotas:
        rows.append([
            f"{q.quota_type}:{q.id}",
            _format_number(q.custodial),
            _format_number(q.custodial_limit) if q.custodial_limit is not None else "-",
            _percentage(q.custodial, q.custodial_limit),
            _format_number(q.replica),
            _format_number(q.replica_limit) if q.replica_limit is not None else "-",
            _percentage(q.replica, q.replica_limit),
        ])

    col_width = [max(len(row[i]) for row in rows) for i in range(len(header))]
    return [
        "\t".join(
            cell.rjust(col_width[i]) if i in right_cols else cell.ljust(col_width[i])
            for i, cell in enumerate(row)
        )
        for row in rows
    ]


def format_space(result: SpaceInfo) -> list[str]:
    """Format space info for a single pool group.

    Labels are left-aligned, values right-aligned so the numbers line
    up in a column.
    """
    rows = _space_rows(result)
    label_width, value_width = _space_widths(rows)
    return _render_space_rows(rows, label_width, value_width)


def format_space_groups(groups: list[tuple[str, SpaceInfo]]) -> list[str]:
    """Format space info for multiple pool groups, e.g. all the pool
    groups serving a path.

    Numbers are aligned across all pool groups (not just within each
    one's own block), and each block is preceded by a '[name]' header.
    """
    all_rows = [row for _, result in groups for row in _space_rows(result)]
    label_width, value_width = _space_widths(all_rows)

    lines: list[str] = []
    for i, (name, result) in enumerate(groups):
        if i > 0:
            lines.append("")
        lines.append(f"[{name}]")
        lines.extend(_render_space_rows(_space_rows(result), label_width, value_width))
    return lines


def _space_rows(result: SpaceInfo) -> list[tuple[str, int, str]]:
    available = result.free + result.removable
    return [
        ("Total:", result.total, ""),
        ("Free:", result.free, ""),
        ("Precious:", result.precious, ""),
        ("Removable:", result.removable, "  (cached replicas, reclaimable)"),
        ("Available:", available, "  (free + removable)"),
    ]


def _space_widths(rows: list[tuple[str, int, str]]) -> tuple[int, int]:
    label_width = max(len(label) for label, _, _ in rows) + 1
    value_width = max(len(_format_number(value)) for _, value, _ in rows)
    return label_width, value_width


def _render_space_rows(
    rows: list[tuple[str, int, str]], label_width: int, value_width: int
) -> list[str]:
    return [
        f"{label:<{label_width}}{_format_number(value):>{value_width}}{suffix}"
        for label, value, suffix in rows
    ]


def _format_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _percentage(value: int, limit: Optional[int]) -> str:
    if not limit:
        return "-"
    return f"{value / limit * 100:.1f}%"
