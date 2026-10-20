"""WebDAV client for uploading and downloading file content.

The dCache REST API (``api.py``) can manage metadata (list, stat, mkdir,
checksums, ...) but cannot transfer file *content*. That requires a
WebDAV door: a separate endpoint dCache exposes for PUT/GET, often on
a different host and/or port than the REST API.

This module:
- finds a suitable WebDAV door (``discover_webdav_door``), and
- performs the actual streaming PUT/GET (``WebdavClient``),

reusing the same :class:`~ada.auth.AuthProvider` as the REST API client,
since the same credentials (bearer token, netrc, X.509 proxy) are valid
for both.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import quote, urljoin, urlparse

import httpx

from ada.api import build_ssl_kwargs
from ada.auth import AuthProvider, TokenFileAuth
from ada.exceptions import AdaAPIError, AdaTransferError

if TYPE_CHECKING:
    from ada.api import DcacheAPI

logger = logging.getLogger("ada.webdav")

MAX_REDIRECTS = 5
REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)


# ---- Door discovery ----


def discover_webdav_door(api: DcacheAPI, auth: AuthProvider) -> str:
    """Find a WebDAV door to use for uploads/downloads.

    Tries, in order:
        1. The ``url =`` entry in an rclone-format tokenfile, if that's
           the active authentication method.
        2. The dCache-view configuration endpoint (``/scripts/config.js``).
        3. The ``/doors`` API, picking the best public HTTPS door.

    A user can always bypass discovery entirely by prepending a door to
    the remote path (e.g. ``https://dcache.example.org:2880/pnfs/...``).

    Raises:
        AdaTransferError: If no WebDAV door could be found by any method.
    """
    if isinstance(auth, TokenFileAuth):
        door = _door_from_tokenfile(auth.tokenfile)
        if door:
            logger.debug("WebDAV door from tokenfile: %s", door)
            return door

    door = _door_from_config_js(api)
    if door:
        logger.debug("WebDAV door from config.js: %s", door)
        return door

    door = _door_from_doors_api(api)
    if door:
        logger.debug("WebDAV door from /doors: %s", door)
        return door

    raise AdaTransferError(
        "Unable to determine a WebDAV door. Run with --debug for details, "
        "or work around this by prepending the door to the remote path, "
        "e.g. 'https://webdav.example.org/pnfs/...'."
    )


def _door_from_tokenfile(tokenfile: str) -> Optional[str]:
    """Read a WebDAV door from an rclone-format tokenfile's ``url =`` entry."""
    try:
        content = Path(tokenfile).read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("Could not read tokenfile '%s': %s", tokenfile, exc)
        return None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("url"):
            parts = stripped.split("=", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return None


def _door_from_config_js(api: DcacheAPI) -> Optional[str]:
    """Read the WebDAV door from the dCache-view ``/scripts/config.js`` endpoint."""
    api_server = re.sub(r"/api/v\d+$", "", api.base_url)
    try:
        data = api.get_absolute(f"{api_server}/scripts/config.js")
    except Exception as exc:
        logger.debug("Could not get WebDAV door from config.js: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    return data.get("dcache-view.endpoints.webdav") or None


def _door_from_doors_api(api: DcacheAPI) -> Optional[str]:
    """Pick the best public HTTPS door from the ``/doors`` API.

    Preference: door must serve https, root '/', with read+write access
    to '/'; among those, prefer more tags (more "publicly advertised"),
    then port 443, then lowest reported load.
    """
    try:
        doors = api.get("doors")
    except Exception as exc:
        logger.debug("Could not get WebDAV door from /doors: %s", exc)
        return None
    if not isinstance(doors, list):
        return None

    candidates = [
        door
        for door in doors
        if door.get("protocol") == "https"
        and door.get("root") == "/"
        and "/" in (door.get("readPaths") or [])
        and "/" in (door.get("writePaths") or [])
        and door.get("addresses")
    ]
    if not candidates:
        return None

    candidates.sort(
        key=lambda door: (
            -len(door.get("tags") or []),
            door.get("port") != 443,
            door.get("load", 0),
        )
    )
    best = candidates[0]
    return f"{best['protocol']}://{best['addresses'][0]}:{best['port']}"


# ---- Streaming PUT/GET ----


class WebdavClient:
    """Streaming upload/download over WebDAV, reusing an AuthProvider.

    By default, redirects are only followed if they stay on https — a
    dCache WebDAV door redirecting to a plain http pool would otherwise
    silently downgrade the connection. Pass ``allow_insecure_redirects``
    to override this (matching the Bash version's behavior).
    """

    def __init__(
        self,
        door: str,
        auth: AuthProvider,
        verify: bool = True,
        allow_insecure_redirects: bool = False,
    ) -> None:
        self.door = door.rstrip("/")
        self.auth = auth
        self.allow_insecure_redirects = allow_insecure_redirects

        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(30.0, read=None),
            "follow_redirects": False,  # we follow redirects manually, see _next_url
        }
        client_kwargs.update(build_ssl_kwargs(auth, verify))
        self._client = httpx.Client(**client_kwargs)

    def url_for(self, path: str) -> str:
        """Build the full WebDAV URL for a dCache namespace path."""
        return f"{self.door}{quote(path, safe='/')}"

    def upload(
        self,
        local_path: str,
        remote_path: str,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> None:
        """Upload a local file to a remote path via PUT.

        Raises:
            AdaTransferError: On too many redirects or an insecure redirect.
            AdaAPIError: If the server returns an HTTP error status.
        """
        url = self.url_for(remote_path)
        headers = dict(self.auth.headers())
        if extra_headers:
            headers.update(extra_headers)
        httpx_auth = self.auth.get_httpx_auth()

        for _ in range(MAX_REDIRECTS + 1):
            with open(local_path, "rb") as handle:
                response = self._client.put(
                    url, headers=headers, content=handle, auth=httpx_auth,
                )
            if response.status_code in REDIRECT_STATUS_CODES:
                url = self._next_url(response)
                continue
            self._raise_for_status(response)
            return

        raise AdaTransferError(f"Too many redirects while uploading to '{remote_path}'.")

    def download(self, remote_path: str, local_path: str) -> None:
        """Download a remote file to a local path via GET, streaming to disk.

        Raises:
            AdaTransferError: On too many redirects or an insecure redirect.
            AdaAPIError: If the server returns an HTTP error status.
        """
        url = self.url_for(remote_path)
        headers = dict(self.auth.headers())
        httpx_auth = self.auth.get_httpx_auth()

        for _ in range(MAX_REDIRECTS + 1):
            with self._client.stream(
                "GET", url, headers=headers, auth=httpx_auth,
            ) as response:
                if response.status_code in REDIRECT_STATUS_CODES:
                    url = self._next_url(response)
                    continue
                if response.status_code >= 400:
                    response.read()
                    self._raise_for_status(response)
                with open(local_path, "wb") as out:
                    for chunk in response.iter_bytes():
                        out.write(chunk)
                return

        raise AdaTransferError(f"Too many redirects while downloading '{remote_path}'.")

    # ---- Internal ----

    def _next_url(self, response: httpx.Response) -> str:
        """Validate a redirect response and return the target URL."""
        location = response.headers.get("location")
        if not location:
            raise AdaTransferError(
                f"Redirect response ({response.status_code}) without a Location header."
            )
        target = urljoin(str(response.url), location)
        if urlparse(target).scheme != "https" and not self.allow_insecure_redirects:
            raise AdaTransferError(
                f"Refusing to follow insecure redirect to '{target}'. "
                "Use --allow-insecure-redirects to override."
            )
        return target

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise AdaAPIError(
                f"WebDAV error {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
                response_body=response.text,
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WebdavClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
