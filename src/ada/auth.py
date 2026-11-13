"""Authentication for ADA, and inspection of tokens.

Each authentication method is an :class:`AuthProvider`: a bearer token
(:class:`TokenAuth`, :class:`TokenFileAuth`, :class:`TokenOidcAgentAuth`),
a netrc file (:class:`NetrcAuth`) or an X.509 proxy certificate
(:class:`ProxyAuth`). :func:`resolve_auth` picks the method from, in
order of precedence (matching the Bash version):

1. Explicit arguments (highest)
2. Environment variables
3. Config file values (lowest)

The module also decodes JWT/OIDC tokens and macaroons, checks their
expiry and permissions, and checks a macaroon's IP caveat against this
system's public IP address.
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
import ssl

import httpx
from ada.exceptions import AdaAuthError, AdaTokenExpiredError, AdaTokenPermissionError
from ada.utils import check_file_permissions
from ada.x509utils import (
    VOMS_EXTENSION_OID,
    find_extension,
    pem_certs,
    voms_ac_validity,
    x509_validity,
)


if TYPE_CHECKING:
    from ada.config import AdaConfig

logger = logging.getLogger("ada.auth")


class AuthProvider(ABC):
    """Base class for all authentication methods.

    Subclasses provide the request headers and, where needed, httpx
    credentials or an SSL context with a client certificate.
    """

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Get the HTTP headers that authenticate a request.

        Returns:
            The headers, e.g. an Authorization header with a bearer
            token. Empty for methods that authenticate otherwise.
        """

    @abstractmethod
    def method_name(self) -> str:
        """Get the short name of the method.

        Returns:
            ``"token"``, ``"netrc"`` or ``"proxy"``.
        """

    def describe(self) -> str:
        """Describe the method and where it came from.

        Auth methods can come from explicit CLI arguments, environment
        variables, or ada.conf, so this is shown in ``whoami`` to make an
        otherwise invisible choice visible.

        Returns:
            A description, e.g.
            ``"token (tokenfile: /home/user/macaroon.conf)"``.
        """
        return self.method_name()

    def view_token(self) -> dict[str, Any]:
        """Decode the token, to show its properties.

        Returns:
            The token's claims (OIDC) or caveats (macaroon).

        Raises:
            AdaAuthError: If the method does not use a token.
        """
        raise AdaAuthError(
            "Token viewing is not supported for this authentication method."
        )

    def expiry_status(self) -> str:
        """Describe when the token expires, without failing if it has.

        Unlike :meth:`validate`, this doesn't decide whether the token
        may be used: it's for commands like ``viewtoken`` that only show
        the status, even of an expired token.

        Returns:
            E.g. ``"valid, expires in 2h 5m 0s"`` or
            ``"expired 3m 10s ago"``.

        Raises:
            AdaAuthError: If the method does not use a token.
        """
        raise AdaAuthError(
            "Token expiry is not applicable for this authentication method."
        )

    def validate(self, command: Optional[str] = None) -> None:
        """Check the credentials before they are used.

        For tokens and proxies, checks that they don't expire within 60
        seconds, and, for ``command="stage"``, that a token allows
        staging. Methods without such checks do nothing.

        Args:
            command: The operation the credentials will be used for, to
                check operation-specific permissions. Only ``"stage"``
                is checked.

        Raises:
            AdaTokenExpiredError: If the token or proxy has expired or
                expires within 60 seconds.
            AdaTokenPermissionError: If the token does not allow the
                operation.
            AdaAuthError: If the credentials can't be decoded.
        """

    def get_httpx_auth(self) -> Any:
        """Get httpx credentials, for methods that need them.

        Returns:
            E.g. ``httpx.BasicAuth`` for netrc authentication, or None.
        """
        return None

    def get_ssl_context(self) -> Any:
        """Get an SSL context with a client certificate, for methods that need it.

        Returns:
            An SSL context for proxy authentication, or None.
        """
        return None


class TokenAuth(AuthProvider):
    """Bearer token authentication, with an OIDC token or a macaroon.

    Args:
        token: The token. Surrounding whitespace is removed.
        source: Where the token came from, shown by :meth:`describe`.
    """

    def __init__(self, token: str, source: str = "direct") -> None:
        self.token = token.strip()
        self.source = source

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def method_name(self) -> str:
        return "token"

    def describe(self) -> str:
        return f"token ({self.source})"

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
    """Bearer token authentication, with the token read from a file.

    The file is either an rclone config file with a
    ``bearer_token = <token>`` line, or a file with only the token (the
    first non-empty line is used).

    Args:
        tokenfile: Path of the file. ``~`` is expanded.

    Raises:
        FileNotFoundError: If the file does not exist.
        AdaSecurityError: If the file is readable or writable by others.
        AdaAuthError: If no token can be read from the file.
    """

    def __init__(self, tokenfile: str) -> None:
        tokenfile = str(Path(tokenfile).expanduser())
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

        # Try rclone config format first. A bearer_token key found with an
        # empty value means this is an rclone-format file with no token
        # configured — fail clearly rather than falling through to the
        # plain-token fallback below, which would otherwise misread an
        # unrelated line (e.g. the "[section]" header) as the token.
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("bearer_token"):
                parts = stripped.split("=", 1)
                if len(parts) == 2:
                    token = parts[1].strip()
                    if token:
                        return token
                    raise AdaAuthError(f"bearer_token is empty in tokenfile: {path}")

        # Fall back to plain token (first non-empty line), only reached
        # when the file has no bearer_token key at all.
        for line in content.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped

        raise AdaAuthError(f"Could not read token from file: {path}")

class TokenOidcAgentAuth(TokenAuth):
    '''Bearer token authentication, with OIDC tokens from oidc-agent.

    A fresh token is requested from oidc-agent for each request, so a
    token never expires during a long operation. Requires oidc-agent to be
    installed, configured and running, and the ``liboidcagent`` library
    (``pip install 'dcache-pyclient[oidc-agent]'``).

    Args:
        client: Name of the oidc-agent account.
        **kwargs: Passed on to ``liboidcagent.get_access_token``, e.g.
            ``min_valid_period`` or ``scope``.

    Raises:
        RuntimeError: If ``liboidcagent`` is not installed.
    '''

    def __init__(self, client: str,**kwargs):
        
        try:
            import liboidcagent as agent
            self.agent = agent
        except ImportError:
            raise RuntimeError(
                "This auth method requires 'liboidcagent'. "
                "Install it using: pip install 'dcache-pyclient[oidc-agent]'"
            ) from None

        self.client = client
        self.token_options = kwargs

        token = self._get_token()
        
        source = f"oidc-agent : {client}"
        super().__init__(token, source)

    def _get_token(self) -> str:
        return self.agent.get_access_token(self.client, **self.token_options)

    def headers(self) -> dict[str, str]:
        self.token = self._get_token() 
        return super().headers()


def _parse_netrc(path: str, hostname: str) -> tuple[str, str]:
    """Parse a netrc file for the login/password of the given host.

    Reimplemented instead of using the stdlib ``netrc`` module, which
    silently strips backslashes from values — a long-standing, deliberately
    unfixed bug (https://github.com/python/cpython/issues/99080) that
    corrupts any password containing one. ``curl --netrc`` does not have
    this bug, so this parser matches curl's plain whitespace-tokenized
    behavior instead.
    """
    text = Path(path).read_text(encoding="utf-8")
    entries: dict[str, dict[str, str]] = {}
    default: dict[str, str] = {}
    current: Optional[dict[str, str]] = None
    in_macdef = False
    for line in text.splitlines():
        if in_macdef:
            if not line.strip():
                in_macdef = False
            continue
        tokens = line.split()
        i = 0
        while i < len(tokens):
            keyword = tokens[i]
            if keyword == "machine" and i + 1 < len(tokens):
                current = entries.setdefault(tokens[i + 1], {})
                i += 2
            elif keyword == "default":
                current = default
                i += 1
            elif keyword in ("login", "password", "account") and current is not None and i + 1 < len(tokens):
                current[keyword] = tokens[i + 1]
                i += 2
            elif keyword == "macdef":
                # Macro bodies run until a blank line; not used by ADA, so skip them.
                in_macdef = True
                break
            else:
                i += 1

    entry = entries.get(hostname, default)
    return entry.get("login", ""), entry.get("password", "")


class NetrcAuth(AuthProvider):
    """Username and password (HTTP Basic) authentication, from a netrc file.

    The login and password of the ``machine`` entry for the API host are
    used, or the ``default`` entry if there is none.

    Args:
        netrcfile: Path of the netrc file. ``~`` is expanded. Defaults
            to ``~/.netrc``.
        hostname: Host name of the API, to find its entry.

    Raises:
        FileNotFoundError: If the file does not exist.
        AdaSecurityError: If the file is readable or writable by others.
    """

    def __init__(self, netrcfile: Optional[str] = None, hostname: Optional[str] = None) -> None:
        self.netrcfile = str(Path(netrcfile).expanduser()) if netrcfile else str(Path.home() / ".netrc")
        self.hostname = hostname
        check_file_permissions(self.netrcfile)

    def headers(self) -> dict[str, str]:
        # Basic auth is handled via httpx auth parameter, not headers
        return {}

    def method_name(self) -> str:
        return "netrc"

    def describe(self) -> str:
        return f"netrc ({self.netrcfile})"

    def get_httpx_auth(self) -> Any:
        """Parse netrc and return httpx BasicAuth for the API host."""
        if not self.hostname:
            raise AdaAuthError(
                "Cannot use netrc authentication without knowing the API hostname."
            )

        try:
            login, password = _parse_netrc(self.netrcfile, self.hostname)
        except OSError as exc:
            raise AdaAuthError(f"Cannot read netrc file '{self.netrcfile}': {exc}") from exc

        if not login or not password:
            raise AdaAuthError(
                f"No credentials found for host '{self.hostname}' in '{self.netrcfile}'."
            )

        return httpx.BasicAuth(username=login, password=password)


class ProxyAuth(AuthProvider):
    """Authentication with an X.509 proxy certificate (TLS client certificate).

    Args:
        proxyfile: Path of the proxy file. Defaults to
            ``$X509_USER_PROXY``, or ``/tmp/x509up_u<uid>`` if not set.
        certdir: Directory with CA certificates to verify the server
            with. Defaults to ``$X509_CERT_DIR``, or
            ``/etc/grid-security/certificates`` if not set.
        igtf: Also trust the CA certificates in ``certdir`` (e.g. IGTF
            Grid CAs) when verifying the server, besides the system's
            default CAs.

    Raises:
        AdaAuthError: If the proxy file or (with ``igtf``) the CA
            certificate directory does not exist.
    """

    def __init__(
        self,
        proxyfile: Optional[str] = None,
        certdir: Optional[str] = None,
        igtf: bool = True,
    ) -> None:
        proxyfile = proxyfile or os.environ.get(
            "X509_USER_PROXY", f"/tmp/x509up_u{os.getuid()}"
        )
        certdir = certdir or os.environ.get(
            "X509_CERT_DIR", "/etc/grid-security/certificates"
        )
        self.proxyfile = str(Path(proxyfile).expanduser())
        self.certdir = str(Path(certdir).expanduser())
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

    def validate(self, command: Optional[str] = None) -> None:
        """Check that the proxy does not expire within 60 seconds.

        A VOMS proxy has two, potentially different, validity windows:
        the X.509 certificate's own ``notAfter``, and (if present) the
        embedded VOMS attribute certificate's ``attrCertValidityPeriod``,
        which the VOMS server controls independently of the certificate
        lifetime requested at ``voms-proxy-init`` time. Both are checked;
        whichever expires first determines the effective expiry. With
        several certificates in the file, the earliest expiry counts.

        Args:
            command: Not used; a proxy has no operation-specific
                permissions to check.

        Raises:
            AdaTokenExpiredError: If the proxy or its VOMS attributes
                have expired or expire within 60 seconds.
            AdaAuthError: If the file contains no certificates.
        """
        pem_text = Path(self.proxyfile).read_text(encoding="utf-8")
        der_certs = pem_certs(pem_text)
        if not der_certs:
            raise AdaAuthError(f"No certificates found in proxy file: {self.proxyfile}")

        x509_expiry: Optional[int] = None
        voms_expiry: Optional[int] = None
        for der_cert in der_certs:
            _, not_after = x509_validity(der_cert)
            exp = int(not_after.timestamp())
            if x509_expiry is None or exp < x509_expiry:
                x509_expiry = exp

            extension = find_extension(der_cert, VOMS_EXTENSION_OID)
            if extension is None:
                continue
            validity = voms_ac_validity(extension)
            if validity is None:
                logger.debug(
                    "Could not parse VOMS attribute validity in proxy: %s",
                    self.proxyfile,
                )
                continue
            _, voms_not_after = validity
            exp = int(voms_not_after.timestamp())
            if voms_expiry is None or exp < voms_expiry:
                voms_expiry = exp

        if voms_expiry is not None and voms_expiry < x509_expiry:
            _check_expiry(voms_expiry, f"VOMS attributes in proxy: {self.proxyfile}")
        else:
            _check_expiry(x509_expiry, f"certificate in proxy: {self.proxyfile}")
    def describe(self) -> str:
        return f"proxy ({self.proxyfile})"

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


# Shown when no authentication method is given anywhere.
_NO_AUTH_METHOD_MESSAGE = """\
No authentication method specified. Use one of:
  Token file (macaroon or OIDC token):
      --tokenfile FILE, $ada_tokenfile, or tokenfile=FILE in ada.conf
  Token in an environment variable:
      $BEARER_TOKEN (--token to require it)
  OIDC token from oidc-agent:
      --tokenclient ACCOUNT, $ada_tokenclient, or tokenclient=ACCOUNT in ada.conf
  Username and password in a netrc file:
      --netrc (~/.netrc), --netrcfile FILE, $ada_netrcfile, or netrcfile=FILE in ada.conf
  X.509 proxy certificate:
      --proxy ($X509_USER_PROXY or /tmp/x509up_u<uid>), or --proxyfile FILE
See https://sara-nl.github.io/dcache-pyclient/configuration.html"""


def resolve_auth(
    token: Optional[str] = None,
    tokenfile: Optional[str] = None,
    tokenclient: Optional[str] = None,
    netrc: Optional[str] = None,
    proxy: Optional[str] = None,
    config: Optional[AdaConfig] = None,
) -> AuthProvider:
    """Pick the authentication method from arguments, environment and config.

    The first method found is used, in this order:

    1. Arguments: ``token``, ``tokenfile``, ``tokenclient``, ``netrc``,
       ``proxy``.
    2. Environment variables: ``$BEARER_TOKEN``, ``$ada_tokenfile``,
       ``$ada_tokenclient``, ``$ada_netrcfile``.
    3. Config file values: ``tokenfile``, ``tokenclient``, ``netrcfile``.

    Args:
        token: Bearer token.
        tokenfile: File with a bearer token.
        tokenclient: oidc-agent account name.
        netrc: Netrc file; an empty string means ``~/.netrc``.
        proxy: Proxy certificate file; an empty string means the default
            location (see :class:`ProxyAuth`).
        config: The configuration, for the config file values, the API
            host name (for netrc) and the ``igtf`` setting (for proxies).

    Returns:
        The authentication method.

    Raises:
        AdaAuthError: If no authentication method is found.
    """
    igtf = config.igtf if config else True
    hostname = _extract_hostname(config.api) if config and config.api else ""

    # 1. Explicit arguments
    if token:
        return TokenAuth(token, source="direct")
    if tokenfile:
        return TokenFileAuth(tokenfile)
    if tokenclient:
        return TokenOidcAgentAuth(tokenclient)
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
    if tc := os.environ.get("ada_tokenclient"):
        return TokenOidcAgentAuth(tc)
    if nf := os.environ.get("ada_netrcfile"):
        return NetrcAuth(nf, hostname=hostname)

    # 3. Config file values
    if config:
        if config.tokenfile:
            return TokenFileAuth(config.tokenfile)
        if config.tokenclient:
           return TokenOidcAgentAuth(config.tokenclient)
        if config.netrcfile:
            return NetrcAuth(config.netrcfile, hostname=hostname)

    raise AdaAuthError(_NO_AUTH_METHOD_MESSAGE)


# JWT/OIDC token handling.

# Decodes and inspects JWT tokens without requiring external libraries
# by using base64 decoding of the payload section.


# JWT pattern: three base64url-encoded parts separated by dots
JWT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def is_jwt(token: str) -> bool:
    """Check whether a token looks like a JWT (OIDC token).

    Args:
        token: The token.

    Returns:
        True if the token consists of three base64url parts separated
        by dots.
    """
    return bool(JWT_PATTERN.match(token.strip()))


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode the payload section of a JWT token.

    Does NOT verify the signature: this is for inspection only,
    matching the Bash version's behavior.

    Args:
        token: The JWT.

    Returns:
        The claims in the payload.

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
    """Decode a JWT, with its times in a readable format.

    Converts ``exp``, ``nbf``, and ``iat`` fields from Unix timestamps
    to ISO 8601 strings (matching the Bash ``jq .exp |= todate`` behavior).
    The signature is not verified.

    Args:
        token: The JWT.

    Returns:
        The claims in the payload.

    Raises:
        AdaAuthError: If the token cannot be decoded.
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
    """Get the expiry time (``exp`` claim) of a JWT.

    Args:
        token: The JWT.

    Returns:
        The expiry time as a Unix timestamp, or None if the token has
        no ``exp`` claim.

    Raises:
        AdaAuthError: If the token can't be decoded.
    """
    payload = decode_jwt_payload(token)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        return int(exp)
    return None


def get_jwt_scope(token: str) -> str:
    """Get the ``scope`` claim of a JWT.

    Args:
        token: The JWT.

    Returns:
        The scopes, separated by spaces, e.g. ``"openid storage.read:/"``.
        Empty if the token has no ``scope`` claim.

    Raises:
        AdaAuthError: If the token can't be decoded.
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

    Replicates the Bash decoding logic::

        base64 -d | awk '{print substr($0, 5)}' | grep -v 'signature' | tr -d '\\0'

    Args:
        token: The macaroon.

    Returns:
        The decoded text, with the location, identifier and caveats,
        without the signature.

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
    """Get the expiry time of a macaroon, from its ``before:`` caveat.

    Args:
        decoded_text: The decoded macaroon, from
            :func:`decode_macaroon_raw`.

    Returns:
        The expiry time as a Unix timestamp, or None if there is no
        ``before:`` caveat.

    Raises:
        AdaAuthError: If the ``before:`` time can't be parsed.
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

    Args:
        version: 4 for IPv4, 6 for IPv6.

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
        return "IP caveat is empty. Warning: use IP caveats in a macaroon to reduce security risks."

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
    """Format a duration in seconds in a readable way.

    Args:
        seconds: The duration in seconds.

    Returns:
        E.g. ``"2d 3h 15m 0s"`` or ``"45s"``. Zero days, hours or
        minutes are left out; seconds are always shown.
    """
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = [f"{n}{unit}" for n, unit in ((days, "d"), (hours, "h"), (minutes, "m")) if n]
    parts.append(f"{seconds}s")
    return " ".join(parts)


def describe_expiry(exp_unix: Optional[int]) -> str:
    """Describe when a token expires, without failing if it has.

    Unlike ``_check_expiry()``, this doesn't decide whether the token
    may be used; it's for 'viewtoken'-style commands where the goal is
    to inspect the token, not to use it, so an expired token is not an
    error, just a fact worth showing.

    Args:
        exp_unix: The expiry time as a Unix timestamp, or None if
            unknown.

    Returns:
        ``"valid, expires in <duration>"``, ``"expired <duration> ago"``,
        or ``"unknown (no expiration field found)"``.
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
