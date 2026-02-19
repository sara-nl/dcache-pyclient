"""Configuration loading for ADA.

Supports the same key=value file format as the Bash version so that
existing ``~/.ada/ada.conf`` files continue to work without changes.

Precedence (lowest to highest):
    1. Bundled default config  (<package>/etc/ada.conf)
    2. System-wide config      (/etc/ada.conf)
    3. User config             (~/.ada/ada.conf)
    4. Environment variables   (ada_api, ada_debug, etc.)
    5. Constructor arguments   (handled by caller)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ada.exceptions import AdaConfigError, AdaSecurityError
from ada.utils import check_config_permissions

logger = logging.getLogger("ada.config")


@dataclass
class AdaConfig:
    """Configuration for ADA, assembled from files + env + CLI args."""

    api: str = ""
    debug: bool = False
    igtf: bool = True
    channel_timeout: int = 3600
    tokenfile: Optional[str] = None
    netrcfile: Optional[str] = None
    curl_options: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Validate configuration values.

        Raises:
            AdaConfigError: If the API URL is set but has an invalid format.
        """
        if self.api:
            api = self.api.rstrip("/")
            self.api = api
            if not api.startswith("https://"):
                raise AdaConfigError(
                    f"API address must start with 'https://'. Got: {api}"
                )
            if not re.search(r"/api/v[12]$", api):
                logger.warning(
                    "API address '%s' does not end with '/api/v1' or '/api/v2'. "
                    "This may cause errors.",
                    api,
                )


def load_config(paths: Optional[list[str]] = None) -> AdaConfig:
    """Load configuration from files and environment variables.

    Args:
        paths: Optional list of config file paths to search.
            If not provided, uses default search paths.

    Returns:
        Populated AdaConfig instance.
    """
    config = AdaConfig()
    search_paths = paths or _default_config_paths()

    for path_str in search_paths:
        path = Path(path_str).expanduser()
        if path.is_file():
            try:
                check_config_permissions(str(path))
            except AdaSecurityError:
                logger.warning("Skipping config file with insecure permissions: %s", path)
                raise
            _load_config_file(config, path)

    _apply_env_vars(config)
    return config


def _default_config_paths() -> list[str]:
    """Return default config search paths in order of precedence (lowest first)."""
    script_dir = str(Path(__file__).parent)
    return [
        f"{script_dir}/etc/ada.conf",  # Bundled defaults
        "/etc/ada.conf",  # System-wide
        "~/.ada/ada.conf",  # User-level
    ]


def _load_config_file(config: AdaConfig, path: Path) -> None:
    """Parse a simple key=value config file.

    Lines starting with ``#`` are comments. Supports both quoted and
    unquoted values. Bash-style array syntax is ignored (curl_options).
    """
    logger.debug("Loading config from %s", path)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Skip bash-style array assignments like curl_options_common=(...)
        if "=(" in line:
            continue
        # Skip lines that are part of a bash array (indented or ending with \)
        if line.startswith("-") or line.endswith(")") or line.endswith("\\"):
            continue

        match = re.match(r"^(\w+)\s*=\s*[\"']?(.*?)[\"']?\s*$", line)
        if match:
            key, value = match.group(1), match.group(2)
            _apply_config_value(config, key, value)


def _apply_config_value(config: AdaConfig, key: str, value: str) -> None:
    """Apply a single config key/value pair."""
    if key == "api":
        config.api = value
    elif key == "igtf":
        config.igtf = value.lower() in ("true", "1", "yes")
    elif key == "channel_timeout":
        try:
            config.channel_timeout = int(value)
        except ValueError:
            logger.warning("Invalid channel_timeout value: %s", value)
    elif key == "debug":
        config.debug = value.lower() in ("true", "1", "yes")
    elif key == "tokenfile":
        config.tokenfile = value
    elif key == "netrcfile":
        config.netrcfile = value


def _apply_env_vars(config: AdaConfig) -> None:
    """Apply environment variable overrides (matching Bash precedence)."""
    if v := os.environ.get("ada_api"):
        config.api = v
    if v := os.environ.get("ada_debug"):
        config.debug = v.lower() in ("true", "1", "yes")
    if v := os.environ.get("ada_channel_timeout"):
        try:
            config.channel_timeout = int(v)
        except ValueError:
            logger.warning("Invalid ada_channel_timeout env value: %s", v)
    if v := os.environ.get("ada_igtf"):
        config.igtf = v.lower() in ("true", "1", "yes")
    if v := os.environ.get("ada_tokenfile"):
        config.tokenfile = v
    if v := os.environ.get("ada_netrcfile"):
        config.netrcfile = v