"""Authentication providers for ADA.

Implements the strategy pattern with an abstract ``AuthProvider`` base
and concrete implementations for token, netrc, and proxy authentication.

Precedence (matching Bash):
    1. Explicit arguments (highest)
    2. Environment variables
    3. Config file values (lowest)
"""

from __future__ import annotations

import ipaddress
import logging
import os
import base64
import json
import re
import time
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse
import netrc as netrc_module
import ssl

import httpx
from ada.exceptions import AdaAuthError, AdaTokenExpiredError, AdaTokenPermissionError
from ada.utils import check_file_permissions


if TYPE_CHECKING:
    from ada.config import AdaConfig

logger = logging.getLogger("ada.auth")


class AuthProvider(ABC):
    """Abstract base for all authentication methods."""

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Return HTTP headers for authentication."""

    @abstractmethod
    def method_name(self) -> str:
        """Human-readable name like 'token', 'netrc', 'proxy'."""

    def view_token(self) -> dict[str, Any]:
        """Decode and return token properties for display."""
        raise AdaAuthError(
            "Token viewing is not supported for this authentication method."
        )

    def expiry_status(self) -> str:
        """Describe token expiry, informationally (never raises on expiry).

        Unlike ``validate()``, this doesn't gate whether the token may
        be used — it's for commands like ``viewtoken`` that just want
        to show the status, even for an expired token.
        """
        raise AdaAuthError(
            "Token expiry is not applicable for this authentication method."
        )

    def validate(self, command: Optional[str] = None) -> None:
        """Validate credentials before use. Override in subclasses."""

    def get_httpx_auth(self) -> Any:
        """Return an httpx auth object, if applicable (e.g., BasicAuth)."""
        return None

    def get_ssl_context(self) -> Any:
        """Return an SSL context for client certificate auth, if applicable."""
        return None


class TokenAuth(AuthProvider):
    """Bearer token authentication (JWT/OIDC or Macaroon)."""

    def __init__(self, token: str, source: str = "direct") -> None:
        self.token = token.strip()
        self.source = source

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def method_name(self) -> str:
        return "token"

    def validate(self, command: Optional[str] = None) -> None:
        validate_token(self.token, source=self.source, command=command)

    def view_token(self) -> dict[str, Any]:
        if is_jwt(self.token):
            return decode_jwt(self.token)
        return decode_macaroon(self.token)

    def expiry_status(self) -> str:
        if is_jwt(self.token):
            exp_unix = get_jwt_expiry(self.token)
        else:
            exp_unix = extract_macaroon_expiry(decode_macaroon_raw(self.token))
        return describe_expiry(exp_unix)


class TokenFileAuth(TokenAuth):
    """Reads token from a file (rclone config format or plain bearer token)."""

    def __init__(self, tokenfile: str) -> None:
        check_file_permissions(tokenfile)
        token = self._read_token(tokenfile)
        super().__init__(token, source=f"tokenfile: {tokenfile}")
        self.tokenfile = tokenfile

    @staticmethod
    def _read_token(path: str) -> str:
        """Read a bearer token from a file.

        Supports:
        - rclone config format (``bearer_token = <token>``)
        - Plain token (first non-empty line)
        """
        content = Path(path).read_text(encoding="utf-8")

        # Try rclone config format first
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("bearer_token"):
                parts = stripped.split("=", 1)
                if len(parts) == 2:
                    token = parts[1].strip()
                    if token:
                        return token

        # Fall back to plain token (first non-empty line)
        for line in content.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped

        raise AdaAuthError(f"Could not read token from file: {path}")


class NetrcAuth(AuthProvider):
    """Netrc-based username/password (Basic) authentication."""

    def __init__(self, netrcfile: Optional[str] = None, hostname: Optional[str] = None) -> None:
        self.netrcfile = netrcfile or str(Path.home() / ".netrc")
        self.hostname = hostname
        check_file_permissions(self.netrcfile)

    def headers(self) -> dict[str, str]:
        # Basic auth is handled via httpx auth parameter, not headers
        return {}

    def method_name(self) -> str:
        return "netrc"

    def get_httpx_auth(self) -> Any:
        """Parse netrc and return httpx BasicAuth for the API host."""
        try:
            nrc = netrc_module.netrc(self.netrcfile)
        except Exception as exc:
            raise AdaAuthError(f"Cannot parse netrc file '{self.netrcfile}': {exc}") from exc

        if not self.hostname:
            raise AdaAuthError(
                "Cannot use netrc authentication without knowing the API hostname."
            )

        auth_tuple = nrc.authenticators(self.hostname)
        if auth_tuple is None:
            raise AdaAuthError(
                f"No credentials found for host '{self.hostname}' in '{self.netrcfile}'."
            )

        login, _, password = auth_tuple
        if not login or not password:
            raise AdaAuthError(
                f"Incomplete credentials for host '{self.hostname}' in '{self.netrcfile}'."
            )

        return httpx.BasicAuth(username=login, password=password)


class ProxyAuth(AuthProvider):
    """X.509 proxy certificate authentication."""

    def __init__(
        self,
        proxyfile: Optional[str] = None,
        certdir: Optional[str] = None,
        igtf: bool = True,
    ) -> None:
        self.proxyfile = proxyfile or os.environ.get(
            "X509_USER_PROXY", f"/tmp/x509up_u{os.getuid()}"
        )
        self.certdir = certdir or os.environ.get(
            "X509_CERT_DIR", "/etc/grid-security/certificates"
        )
        self.igtf = igtf

        if not Path(self.proxyfile).exists():
            raise AdaAuthError(f"Proxy file not found: {self.proxyfile}")
        if igtf and not Path(self.certdir).is_dir():
            raise AdaAuthError(
                f"Certificate directory not found: {self.certdir}"
            )

    def headers(self) -> dict[str, str]:
        # Proxy auth uses TLS client certificate, not HTTP headers
        return {}

    def method_name(self) -> str:
        return "proxy"

    def get_ssl_context(self) -> Any:
        """Return an SSL context configured with the proxy certificate."""

        ctx = ssl.create_default_context()
        if self.igtf:
            ctx.load_verify_locations(capath=self.certdir)
        ctx.load_cert_chain(certfile=self.proxyfile)
        return ctx


def _extract_hostname(api_url: str) -> str:
    """Extract hostname from an API URL."""
    parsed = urlparse(api_url)
    return parsed.hostname or ""


def resolve_auth(
    token: Optional[str] = None,
    tokenfile: Optional[str] = None,
    netrc: Optional[str] = None,
    proxy: Optional[str] = None,
    config: Optional[AdaConfig] = None,
) -> AuthProvider:
    """Resolve authentication method from args, env vars, and config.

    Precedence (from high to low):
        1. Explicit arguments (token, tokenfile, netrc, proxy)
        2. Environment variables ($BEARER_TOKEN, $ada_tokenfile, $ada_netrcfile)
        3. Config file values (tokenfile, netrcfile)

    Raises:
        AdaAuthError: If no authentication method can be resolved.
    """
    igtf = config.igtf if config else True
    hostname = _extract_hostname(config.api) if config and config.api else ""

    # 1. Explicit arguments
    if token:
        return TokenAuth(token, source="direct")
    if tokenfile:
        return TokenFileAuth(tokenfile)
    if netrc is not None:
        return NetrcAuth(netrc if netrc else None, hostname=hostname)
    if proxy is not None:
        return ProxyAuth(
            proxyfile=proxy if proxy else None,
            igtf=igtf,
        )

    # 2. Environment variables
    if bearer := os.environ.get("BEARER_TOKEN"):
        return TokenAuth(bearer, source="$BEARER_TOKEN")
    if tf := os.environ.get("ada_tokenfile"):
        return TokenFileAuth(tf)
    if nf := os.environ.get("ada_netrcfile"):
        return NetrcAuth(nf, hostname=hostname)

    # 3. Config file values
    if config:
        if config.tokenfile:
            return TokenFileAuth(config.tokenfile)
        if config.netrcfile:
            return NetrcAuth(config.netrcfile, hostname=hostname)

    raise AdaAuthError(
        "No authentication method specified. "
        "Use --tokenfile, --netrc, or --proxy."
    )


# JWT/OIDC token handling.

# Decodes and inspects JWT tokens without requiring external libraries
# by using base64 decoding of the payload section.


# JWT pattern: three base64url-encoded parts separated by dots
JWT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def is_jwt(token: str) -> bool:
    """Check if a token looks like a JWT (three dot-separated base64url parts)."""
    return bool(JWT_PATTERN.match(token.strip()))


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode the payload section of a JWT token.

    Does NOT verify the signature — this is for inspection only,
    matching the Bash version's behavior.

    Returns:
        Decoded payload as a dict.

    Raises:
        AdaAuthError: If the token cannot be decoded.
    """
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise AdaAuthError("Invalid JWT: expected 3 dot-separated parts")

    payload_b64 = parts[1]
    # Add padding if needed (base64url omits trailing =)
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding

    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception as exc:
        raise AdaAuthError(f"Invalid JWT: cannot decode payload: {exc}") from exc


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode a JWT and return payload with human-readable timestamps.

    Converts ``exp``, ``nbf``, and ``iat`` fields from Unix timestamps
    to ISO 8601 strings (matching the Bash ``jq .exp |= todate`` behavior).
    """
    payload = decode_jwt_payload(token)
    result = dict(payload)
    for field in ("exp", "nbf", "iat"):
        if field in result and isinstance(result[field], (int, float)):
            try:
                result[field] = datetime.fromtimestamp(
                    result[field], tz=timezone.utc
                ).isoformat()
            except (OSError, ValueError):
                pass  # Keep original value if conversion fails
    return result


def get_jwt_expiry(token: str) -> Optional[int]:
    """Extract the expiration timestamp (exp) from a JWT.

    Returns:
        Unix timestamp as int, or None if not present.
    """
    payload = decode_jwt_payload(token)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        return int(exp)
    return None


def get_jwt_scope(token: str) -> str:
    """Extract the scope claim from a JWT.

    Returns:
        The scope string, or empty string if not present.
    """
    payload = decode_jwt_payload(token)
    return str(payload.get("scope", ""))


# Macaroon token handling.

# Decodes Macaroon tokens using base64 decoding and text parsing,
# matching the Bash version's approach.


def is_macaroon(token: str) -> bool:
    """Check if a token looks like a Macaroon (not a JWT)."""
    return not is_jwt(token)


def decode_macaroon_raw(token: str) -> str:
    """Decode a Macaroon token to its raw text representation.

    Replicates the Bash decoding logic:
        base64 -d | awk '{print substr($0, 5)}' | grep -v 'signature' | tr -d '\\0'

    Returns:
        Decoded macaroon text (caveats, etc.).

    Raises:
        AdaAuthError: If the token cannot be decoded.
    """
    # Macaroons are often base64url-encoded (- and _ instead of + and /)
    # and unpadded. urlsafe_b64decode() also accepts standard base64
    # unchanged, so this handles both; add padding since it's commonly
    # omitted.
    stripped = token.strip()
    padded = stripped + "=" * (-len(stripped) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(padded)
    except Exception as exc:
        raise AdaAuthError(f"Invalid macaroon: cannot base64 decode: {exc}") from exc

    # Strip first 4 bytes (binary header), remove null bytes,
    # filter out signature lines
    try:
        text = decoded_bytes[4:].decode("utf-8", errors="replace")
        text = text.replace("\0", "")
        lines = [
            line for line in text.splitlines() if "signature" not in line.lower()
        ]
        result = "\n".join(lines).strip()
    except Exception as exc:
        raise AdaAuthError(f"Invalid macaroon: cannot decode content: {exc}") from exc

    if not result:
        raise AdaAuthError("Invalid macaroon: empty after decoding")

    return result


_MACAROON_CAVEAT_PATTERN = re.compile(
    r"\b(before|activity|path|id|ip|home|root):(.*)"
)

# The location and identifier are macaroon header fields, not caveats:
# space-separated rather than colon-separated, and optionally preceded
# by a 4-hex-digit length (e.g. "0018identifier jy4B2HLA").
_MACAROON_HEADER_PATTERN = re.compile(r"^(?:[0-9a-f]{4})?(location|identifier)\s+(.*)$")


def decode_macaroon(token: str) -> dict[str, str]:
    """Decode a Macaroon and return its properties as a dict.

    Parses the decoded text for the ``location``/``identifier`` header
    fields and known caveats like ``before:``, ``activity:``,
    ``path:``, ``id:``, etc. Real macaroons (v2 binary format) prefix
    each caveat line with a hex length and a ``cid `` tag (e.g.
    ``002ecid before:2026-...Z``), so caveats are searched for
    anywhere in the line rather than requiring them at the start.
    """
    raw = decode_macaroon_raw(token)
    properties: dict[str, str] = {}

    for line in raw.splitlines():
        header_match = _MACAROON_HEADER_PATTERN.match(line)
        if header_match:
            key, value = header_match.group(1), header_match.group(2).strip()
            properties.setdefault(key, value)
            continue

        caveat_match = _MACAROON_CAVEAT_PATTERN.search(line)
        if caveat_match:
            key, value = caveat_match.group(1), caveat_match.group(2).strip()
            properties.setdefault(key, value)

    return properties


def extract_macaroon_expiry(decoded_text: str) -> Optional[int]:
    """Extract the expiration timestamp from decoded Macaroon text.

    Looks for ``before:`` caveat with ISO 8601 timestamp.

    Returns:
        Unix timestamp as int, or None if not found.
    """
    match = re.search(r"before:([0-9T:.\-]+Z)", decoded_text)
    if not match:
        return None

    exp_str = match.group(1)
    try:
        # Parse ISO 8601 timestamp (e.g., "2024-12-31T23:59:59.000Z")
        # Try with microseconds first, then without
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(exp_str[:26], fmt)
                dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            except ValueError:
                continue
        # Fallback: try parsing just the first 19 chars
        dt = datetime.strptime(exp_str[:19], "%Y-%m-%dT%H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, OSError) as exc:
        raise AdaAuthError(
            f"Invalid macaroon: unable to parse 'before' timestamp: {exp_str}"
        ) from exc


# IP caveat checking.

# Looks up this system's public IP address(es) and compares them
# against a macaroon's IP caveat, using the standard library's
# ipaddress module for subnet matching (no external ipcalc dependency).


# Hostnames that resolve/respond IPv4-only or IPv6-only, so we don't
# need to force a specific address family at the socket level.
_IP_LOOKUP_URLS = {
    4: ("https://api.ipify.org", "https://ipv4.icanhazip.com", "https://checkip.amazonaws.com"),
    6: ("https://api6.ipify.org", "https://ipv6.icanhazip.com"),
}


def get_public_ip(version: int) -> Optional[str]:
    """Look up this system's public IPv4 or IPv6 address.

    Tries a few well-known lookup services in order, falling through
    to the next if one is unreachable.

    Returns:
        The address as a string, or None if it could not be
        determined (e.g. this system has no address of that family).
    """
    for url in _IP_LOOKUP_URLS[version]:
        try:
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
            candidate = response.text.strip()
            if ipaddress.ip_address(candidate).version == version:
                return candidate
        except (httpx.HTTPError, ValueError):
            continue
    return None


def check_ip_caveat(ip_caveat: str) -> str:
    """Check this system's public IP address(es) against a macaroon's IP caveat.

    Args:
        ip_caveat: Comma-separated list of IPs/subnets, as found in a
            macaroon's ``ip:`` caveat.

    Returns:
        A human-readable status message. Never raises — this is purely
        informational.
    """
    if not ip_caveat.strip():
        return "no IP caveat present (recommended, to reduce the impact of a stolen token)."

    try:
        networks = [
            ipaddress.ip_network(item.strip(), strict=False)
            for item in ip_caveat.split(",")
            if item.strip()
        ]
    except ValueError as exc:
        return f"could not parse IP caveat '{ip_caveat}': {exc}"
    if not networks:
        return f"could not parse IP caveat '{ip_caveat}'."

    results = []
    for version, label in ((4, "IPv4"), (6, "IPv6")):
        my_ip = get_public_ip(version)
        if my_ip is None:
            continue
        addr = ipaddress.ip_address(my_ip)
        matched = any(addr in net for net in networks if net.version == version)
        results.append(f"{label} ({my_ip}) {'matches' if matched else 'does not match'}")

    if not results:
        return "could not determine this system's public IP address(es); unable to check."

    return "; ".join(results) + "."


# Token validation logic.

# Validates JWT and Macaroon tokens for expiry and required permissions,
# replicating the Bash ``check_token`` function.


MIN_VALID_TIME = 60  # seconds — token must be valid for at least this long


def format_duration(seconds: int) -> str:
    """Format a duration in seconds as a human-readable string, e.g. '2d 3h 15m'."""
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = [f"{n}{unit}" for n, unit in ((days, "d"), (hours, "h"), (minutes, "m")) if n]
    parts.append(f"{seconds}s")
    return " ".join(parts)


def describe_expiry(exp_unix: Optional[int]) -> str:
    """Describe a token's expiry status, informationally — never raises.

    Unlike ``_check_expiry()``, this doesn't gate whether the token may
    be used; it's for 'viewtoken'-style commands where the goal is to
    inspect the token, not to use it, so an expired token is not an
    error — just a fact worth showing.
    """
    if exp_unix is None or not isinstance(exp_unix, (int, float)):
        return "unknown (no expiration field found)"

    now = int(time.time())
    if now >= exp_unix:
        return f"expired {format_duration(now - exp_unix)} ago"
    return f"valid, expires in {format_duration(exp_unix - now)}"


def validate_token(
    token: str, source: str = "", command: Optional[str] = None
) -> None:
    """Validate a token (JWT or Macaroon) for expiry and permissions.

    Args:
        token: The raw token string.
        source: Description of where the token came from (for error messages).
        command: The command being executed (e.g., "stage"), used to check
            command-specific permissions.

    Raises:
        AdaTokenExpiredError: If the token has expired or is about to expire.
        AdaTokenPermissionError: If the token lacks required permissions.
        AdaAuthError: If the token cannot be decoded.
    """
    if is_jwt(token):
        logger.debug("Token identified as JWT/OIDC (%s)", source)
        _validate_jwt(token, source, command)
    else:
        logger.debug("Token identified as Macaroon (%s)", source)
        _validate_macaroon(token, source, command)


def _validate_jwt(token: str, source: str, command: Optional[str]) -> None:
    """Validate a JWT/OIDC token."""
    exp_unix = get_jwt_expiry(token)
    _check_expiry(exp_unix, source)

    if command == "stage":
        scope = get_jwt_scope(token)
        # Only check if there are storage.* claims at all.
        # If no storage.* claims, dCache assumes everything is allowed.
        if "storage." in scope and "storage.stage" not in scope:
            raise AdaTokenPermissionError(
                "You want to stage data from tape, but your OIDC token "
                "does not have the storage.stage permission in its scope. "
                "You can check this with the --viewtoken option. "
                "Please use an OIDC token with 'storage.stage' in its scope."
            )


def _validate_macaroon(token: str, source: str, command: Optional[str]) -> None:
    """Validate a Macaroon token."""
    decoded = decode_macaroon_raw(token)
    exp_unix = extract_macaroon_expiry(decoded)
    _check_expiry(exp_unix, source)

    if command == "stage":
        # Check for STAGE activity permission
        if "activity:" in decoded and "STAGE" not in decoded:
            raise AdaTokenPermissionError(
                "You want to stage data from tape, but your macaroon token "
                "does not have the STAGE activity permission. "
                "You can check this with the --viewtoken option. "
                "Please use a macaroon with the STAGE activity permission."
            )


def _check_expiry(exp_unix: Optional[int], source: str) -> None:
    """Check token expiration timestamp.

    Raises:
        AdaAuthError: If expiration field is missing or invalid.
        AdaTokenExpiredError: If the token has expired or will expire soon.
    """
    if exp_unix is None or not isinstance(exp_unix, (int, float)):
        raise AdaAuthError(
            f"Invalid token: missing or invalid expiration field. {source}"
        )

    now = int(time.time())

    if now >= exp_unix:
        raise AdaTokenExpiredError(
            f"Token has expired {now - exp_unix} seconds ago. {source}",
            seconds_ago=now - exp_unix,
        )

    if now >= exp_unix - MIN_VALID_TIME:
        raise AdaTokenExpiredError(
            f"Token will expire in {exp_unix - now} seconds. "
            f"Please use a token that is valid for more than {MIN_VALID_TIME} seconds, "
            f"to ensure Ada can finish the task. {source}",
            seconds_ago=0,
        )
