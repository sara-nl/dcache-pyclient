"""Helper functions used throughout ADA.

URL encoding of dCache paths, file permission checks, parsing of
metadata and lifetimes, reading lists of paths, and ADA's version.
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
    """URL-encode a dCache path, for use in a REST API URL.

    All characters are encoded, including ``/``, so the whole path
    becomes a single URL path segment, the way the dCache REST API
    expects it. Equivalent to the Bash ``urlencode`` function
    (``jq -sRr @uri``).

    Args:
        path: dCache path.

    Returns:
        The encoded path, e.g. ``%2Fpnfs%2Fdata`` for ``/pnfs/data``.
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
            f"Fix with: chmod o-w '{path}'"
        )
    if check_readable and mode & stat.S_IROTH:
        raise AdaSecurityError(
            f"File '{path}' is world readable. "
            f"Fix with: chmod o-r '{path}'"
        )


def check_config_permissions(filepath: str) -> None:
    """Check that a config file is not writable by others.

    Unlike credentials files, config files may be readable by others.

    Args:
        filepath: Path of the config file.

    Raises:
        AdaSecurityError: If the file is writable by others.
        FileNotFoundError: If the file does not exist.
    """
    check_file_permissions(filepath, check_readable=False)


def to_json(input_str: str) -> dict[str, str]:
    """Parse key-value metadata, e.g. for extended attributes, into a dict.

    Accepted formats:

    - A JSON object: ``{"key": "value"}``. Values are converted to strings.
    - ``key=value`` pairs, separated by newlines or commas. Quotes around
      values are removed.
    - Tab-separated key and value, one pair per line.

    Replicates the Bash ``to_json`` function.

    Args:
        input_str: The metadata text.

    Returns:
        The key-value pairs.

    Raises:
        AdaValidationError: If no key-value pairs can be found.

    Example::

        to_json("experiment=lofar, quality='good'")
        # {'experiment': 'lofar', 'quality': 'good'}
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
    """Parse a lifetime like ``"7D"``, ``"24H"`` or ``"30M"``.

    Args:
        lifetime_str: A positive whole number followed by a unit: S
            (seconds), M (minutes), H (hours) or D (days). The unit is
            not case-sensitive.

    Returns:
        A tuple of the number and the unit (in upper case), e.g.
        ``(7, "D")``.

    Raises:
        AdaValidationError: If the lifetime is empty, has an unknown
            unit, or the number is not a positive whole number.
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
    """Clean up a dCache path: remove double slashes and a trailing slash.

    Args:
        path: dCache path.

    Returns:
        The cleaned-up path, e.g. ``/pnfs/data`` for ``/pnfs//data/``.
        The root ``/`` stays as it is.
    """
    path = path.strip()
    # Remove double slashes but keep leading /
    while "//" in path:
        path = path.replace("//", "/")
    # Remove trailing slash unless it's the root
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def read_file_list(filepath: str) -> list[str]:
    """Read a local file with one dCache path per line.

    Whitespace around paths is removed. Empty lines and lines starting
    with ``#`` are skipped.

    Args:
        filepath: Path of the local file.

    Returns:
        The paths in the file.

    Raises:
        FileNotFoundError: If the file does not exist.
        AdaValidationError: If the file contains no paths.
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
    """Get the list of paths to work on, from either ``paths`` or ``from_file``.

    Args:
        paths: A path, or a list of paths.
        from_file: Local file with one path per line, read with
            :func:`read_file_list`.

    Returns:
        The paths, as a list.

    Raises:
        AdaValidationError: If both or neither of ``paths`` and
            ``from_file`` are given, or the file contains no paths.
        FileNotFoundError: If ``from_file`` does not exist.
    """

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
    """Ask the user on the terminal to confirm deleting a directory's contents.

    Args:
        path: The directory that will be emptied.

    Returns:
        True if the user answered ``y``.
    """
    confirmation = input(f"Delete all items in '{path}'? (y/n): ")
    return confirmation.lower() == 'y'


def get_version() -> str:
    """Get ADA's version, as shown by ``ada-cli --version``.

    When ADA runs from a git checkout (e.g. an editable install), the
    version comes from git: the latest tag, the number of commits since
    it, the commit and the branch. Otherwise it comes from the installed
    package's metadata (``pyproject.toml``).

    Returns:
        The version, e.g. ``"1.1.1"``, or
        ``"v1.1.1-3-g2db9fac, branch: main (development version)"`` in a
        git checkout, or ``"unknown"`` if neither is available.
    """
    try:
        version = _pkg_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        version = None

    git_info = _git_info()

    if git_info:
        return git_info
    if version:
        return version
    return "unknown"


def _git_info() -> Optional[str]:
    """Return "<git describe>, branch: <branch> (development version)" if
    running from a git checkout, else None. Independent of whether the
    package is installed.
    """
    run_kwargs = dict(
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    try:
        version = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"], **run_kwargs
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], **run_kwargs
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{version}, branch: {branch} (development version)"
