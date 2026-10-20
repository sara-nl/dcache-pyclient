"""Utility functions for ADA.

Provides URL encoding, file permission checks, JSON conversion helpers,
and human-readable size formatting.
"""

from __future__ import annotations

import json
import re
import stat
import subprocess
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from urllib.parse import quote as urlquote
from typing import Optional

from ada.exceptions import AdaSecurityError, AdaValidationError

DISTRIBUTION_NAME = "dcache-pyclient"


def encode_path(path: str) -> str:
    """URL-encode a dCache namespace path.

    Equivalent to the Bash ``urlencode`` function (``jq -sRr @uri``).
    Encodes all characters including ``/`` so the entire path becomes
    a single URL path segment (e.g., ``/pnfs/data`` → ``%2Fpnfs%2Fdata``).
    """
    return urlquote(path, safe="")


def check_file_permissions(filepath: str, *, check_readable: bool = True) -> None:
    """Verify a file is not world-readable or world-writable.

    Replicates the Bash security checks on token files, netrc files,
    and config files.

    Args:
        filepath: Path to check.
        check_readable: If True, also checks world-readable bit.

    Raises:
        AdaSecurityError: If the file has insecure permissions.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(filepath).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File does not exist: {filepath}")
    mode = path.stat().st_mode
    if mode & stat.S_IWOTH:
        raise AdaSecurityError(
            f"File '{path}' is world writable. "
            "Fix with: chmod o-w '{path}'"
        )
    if check_readable and mode & stat.S_IROTH:
        raise AdaSecurityError(
            f"File '{path}' is world readable. "
            "Fix with: chmod o-r '{path}'"
        )


def check_config_permissions(filepath: str) -> None:
    """Verify a config file is not world-writable.

    Config files are allowed to be world-readable but not world-writable.
    """
    check_file_permissions(filepath, check_readable=False)


def to_json(input_str: str) -> dict[str, str]:
    """Convert various metadata formats to a JSON dict.

    Supports:
    - JSON format: ``{"key": "value"}``
    - key=value pairs (one per line, or comma-separated)
    - Tab-separated key/value pairs

    Replicates the Bash ``to_json`` function.
    """
    input_str = input_str.strip()

    # Try JSON first
    if input_str.startswith("{"):
        try:
            result = json.loads(input_str)
            if isinstance(result, dict):
                return {str(k): str(v) for k, v in result.items()}
        except json.JSONDecodeError:
            pass

    result: dict[str, str] = {}

    # Try key=value (newline or comma separated)
    lines = re.split(r"[,\n]", input_str)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip("'\"")
        elif "\t" in line:
            parts = line.split("\t", 1)
            if len(parts) == 2:
                result[parts[0].strip()] = parts[1].strip()

    if not result:
        raise AdaValidationError(
            f"Cannot parse metadata. Expected JSON, key=value, or tab-separated format. "
            f"Got: {input_str[:100]}"
        )
    return result


def parse_lifetime(lifetime_str: str) -> tuple[int, str]:
    """Parse a lifetime string like '7D', '24H', '30M' into (value, unit).

    Returns:
        Tuple of (numeric_value, unit_character).

    Raises:
        AdaValidationError: If the format is invalid.
    """
    if not lifetime_str:
        raise AdaValidationError("Lifetime cannot be empty.")
    unit = lifetime_str[-1].upper()
    if unit not in ("S", "M", "H", "D"):
        raise AdaValidationError(
            f"Invalid lifetime unit '{unit}'. Use S (seconds), M (minutes), "
            f"H (hours), or D (days)."
        )
    try:
        value = int(lifetime_str[:-1])
    except ValueError as exc:
        raise AdaValidationError(
            f"Invalid lifetime value: '{lifetime_str}'. Expected format: <number><unit>, "
            f"e.g., '7D', '24H'."
        ) from exc
    if value <= 0:
        raise AdaValidationError("Lifetime must be a positive number.")
    return value, unit


def normalize_path(path: str) -> str:
    """Normalize a dCache path by removing trailing slashes and double slashes."""
    path = path.strip()
    # Remove double slashes but keep leading /
    while "//" in path:
        path = path.replace("//", "/")
    # Remove trailing slash unless it's the root
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def read_file_list(filepath: str) -> list[str]:
    """Read a file containing one path per line.

    Strips whitespace and ignores empty lines and comments (lines starting with #).
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File list not found: {filepath}")
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    if not lines:
        raise AdaValidationError(f"File list is empty: {filepath}")
    return lines


def resolve_paths(
    paths: Optional[str | list[str]] = None, from_file: Optional[str] = None
) -> list[str]:
    """Resolve paths from arguments or file list."""

    if paths is None and from_file is None:
        raise AdaValidationError("Neither path nor from_file is given")
    if paths is not None and from_file is not None:
        raise AdaValidationError("Both path and from_file are given")
    if from_file:
        return read_file_list(from_file)
    if isinstance(paths, str):
        return [paths]
    return list(paths)


def confirm_deletion(path):
    confirmation = input(f"Delete all items in '{path}'? (y/n): ")
    return confirmation.lower() == 'y'


def get_version() -> str:
    """Return ADA's version string.

    The installed package's version (from pyproject.toml via package
    metadata) is always shown when available. Since Poetry's editable
    dev install has valid metadata regardless of which branch/commit
    is checked out, the package version alone doesn't tell you that
    you're on unreleased code — so when running from a git checkout,
    the branch and commit are appended too, e.g.::

        0.2.1 (branch: 26-add-ada-cli---version, commit: 5977a71)

    If neither is available (not installed, and not a git checkout),
    returns "unknown".
    """
    try:
        version = _pkg_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        version = None

    git_info = _git_info()

    if version and git_info:
        return f"{version} ({git_info})"
    if version:
        return version
    if git_info:
        return f"{git_info} (development version)"
    return "unknown"


def _git_info() -> Optional[str]:
    """Return "branch: <branch>, commit: <commit>" if running from a git
    checkout, else None. Independent of whether the package is installed.
    """
    run_kwargs = dict(
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], **run_kwargs
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "describe", "--always", "--dirty"], **run_kwargs
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"branch: {branch}, commit: {commit}"
