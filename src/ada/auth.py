"""Authentication providers for ADA.

Implements the strategy pattern with an abstract ``AuthProvider`` base
and concrete implementations for token, netrc, and proxy authentication.

Precedence (matching Bash):
    1. Explicit arguments (highest)
    2. Environment variables
    3. Config file values (lowest)
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

from ada.exceptions import AdaAuthError
from ada.utils import check_file_permissions

if TYPE_CHECKING:
    from ada.config import AdaConfig

logger = logging.getLogger("ada.auth")


class AuthProvider(ABC):
    """Abstract base for all authentication methods."""

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Return HTTP headers for authentication."""
        ...

    @abstractmethod
    def method_name(self) -> str:
        """Human-readable name like 'token', 'netrc', 'proxy'."""
        ...

    def view_token(self) -> dict[str, Any]:
        """Decode and return token properties for display."""
        raise NotImplementedError(
            "Token viewing is not supported for this authentication method."
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
        from ada.tokens.validator import validate_token

        validate_token(self.token, source=self.source, command=command)

    def view_token(self) -> dict[str, Any]:
        from ada.tokens.jwt import decode_jwt, is_jwt
        from ada.tokens.macaroon import decode_macaroon

        if is_jwt(self.token):
            return decode_jwt(self.token)
        return decode_macaroon(self.token)


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
        content = Path(path).read_text()

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
        import httpx
        import netrc as netrc_module

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
        import ssl

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

    Precedence (matching Bash):
        1. Explicit arguments (token, tokenfile, netrc, proxy)
        2. Environment variables ($BEARER_TOKEN, $ada_tokenfile, etc.)
        3. Config file values

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