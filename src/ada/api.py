"""Low-level HTTP client for the dCache REST API.

Wraps ``httpx`` and provides:
- URL encoding of dCache paths
- JSON response parsing
- HTTP status code to exception mapping
- Debug logging of all requests
- SSE streaming support
"""

from __future__ import annotations

import logging
from typing import Any, Iterator, Optional

import httpx

from ada.auth import AuthProvider
from ada.exceptions import (
    AdaAPIError,
    AdaAuthenticationError,
    AdaForbiddenError,
    AdaNotFoundError,
)
from ada.utils import encode_path

logger = logging.getLogger("ada.api")


class DcacheAPI:
    """Low-level HTTP client for the dCache REST API.

    All service modules use this client to make API calls.
    It handles authentication, error mapping, and optional debug logging.
    """

    def __init__(
        self,
        base_url: str,
        auth: AuthProvider,
        debug: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.debug = debug

        # Build httpx client with appropriate auth and SSL settings
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(30.0, read=300.0),
            "follow_redirects": True,
        }

        ssl_ctx = auth.get_ssl_context()
        if ssl_ctx:
            client_kwargs["verify"] = ssl_ctx

        self._client = httpx.Client(**client_kwargs)

    def _headers(
        self,
        accept: str = "application/json",
        content_type: Optional[str] = None,
    ) -> dict[str, str]:
        """Build request headers including auth."""
        headers: dict[str, str] = {"Accept": accept}
        headers.update(self.auth.headers())
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _httpx_auth(self) -> Any:
        """Return httpx auth parameter if the provider needs it (e.g., netrc)."""
        return self.auth.get_httpx_auth()

    # ---- HTTP Methods ----

    def get(
        self,
        endpoint: str,
        params: Optional[dict[str, str]] = None,
        accept: str = "application/json",
    ) -> Any:
        """Perform a GET request."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if self.debug:
            logger.debug("GET %s params=%s", url, params)
        response = self._client.get(
            url, headers=self._headers(accept=accept), params=params,
            auth=self._httpx_auth(),
        )
        return self._handle_response(response)

    def post(
        self,
        endpoint: str,
        json: Optional[dict[str, Any]] = None,
        data: Optional[str] = None,
        content_type: str = "application/json",
        accept: str = "application/json",
    ) -> Any:
        """Perform a POST request."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if self.debug:
            logger.debug("POST %s body=%s", url, json or data)
        kwargs: dict[str, Any] = {
            "headers": self._headers(accept=accept, content_type=content_type),
            "auth": self._httpx_auth(),
        }
        if json is not None:
            kwargs["json"] = json
        elif data is not None:
            kwargs["content"] = data
        response = self._client.post(url, **kwargs)
        return self._handle_response(response)

    def post_raw(
        self,
        endpoint: str,
        json: Optional[dict[str, Any]] = None,
    ) -> httpx.Response:
        """POST that returns the raw httpx.Response (for bulk requests needing headers)."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if self.debug:
            logger.debug("POST (raw) %s body=%s", url, json)
        response = self._client.post(
            url,
            headers=self._headers(content_type="application/json"),
            json=json,
            auth=self._httpx_auth(),
        )
        return response

    def delete(self, endpoint: str) -> Any:
        """Perform a DELETE request."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if self.debug:
            logger.debug("DELETE %s", url)
        response = self._client.delete(url, headers=self._headers(), auth=self._httpx_auth())
        return self._handle_response(response)

    def patch(
        self,
        endpoint: str,
        json: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Perform a PATCH request."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if self.debug:
            logger.debug("PATCH %s body=%s", url, json)
        response = self._client.patch(
            url,
            headers=self._headers(content_type="application/json"),
            json=json,
            auth=self._httpx_auth(),
        )
        return self._handle_response(response)

    def stream_sse(
        self,
        endpoint: str,
        last_event_id: Optional[str] = None,
        timeout: int = 3600,
    ) -> Iterator[dict[str, str]]:
        """Open an SSE connection and yield parsed events.

        Each yielded dict has keys: ``event``, ``data``, ``id`` (all optional).
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._headers(accept="text/event-stream")
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id

        with self._client.stream(
            "GET",
            url,
            headers=headers,
            timeout=httpx.Timeout(30.0, read=float(timeout)),
            auth=self._httpx_auth(),
        ) as response:
            if response.status_code >= 400:
                # Read full body for error handling
                response.read()
                self._handle_response(response)

            current_event: dict[str, str] = {}
            for line in response.iter_lines():
                if not line:
                    # Empty line = event boundary
                    if current_event:
                        yield current_event
                        current_event = {}
                    continue

                if line.startswith(":"):
                    # Comment line, skip
                    continue

                if ":" in line:
                    field, _, value = line.partition(":")
                    value = value.lstrip(" ")
                else:
                    field = line
                    value = ""

                if field == "event":
                    current_event["event"] = value
                elif field == "data":
                    # Data can span multiple lines
                    if "data" in current_event:
                        current_event["data"] += "\n" + value
                    else:
                        current_event["data"] = value
                elif field == "id":
                    current_event["id"] = value

            # Yield any remaining event
            if current_event:
                yield current_event

    # ---- Response Handling ----

    def _handle_response(self, response: httpx.Response) -> Any:
        """Map HTTP status codes to exceptions and parse JSON responses."""
        if self.debug:
            body = response.text[:500] if response.text else "(empty)"
            logger.debug("Response %d: %s", response.status_code, body)

        status = response.status_code

        if status == 401:
            raise AdaAuthenticationError(
                "Authentication failed. Check your token, netrc, or proxy credentials."
            )
        if status == 404:
            raise AdaNotFoundError(f"Not found: {response.url}")
        if status == 403:
            raise AdaForbiddenError(
                f"Forbidden: {response.url}",
                response_body=response.text,
            )
        if status == 422:
            raise AdaAPIError(
                "Unprocessable entity",
                status_code=422,
                response_body=response.text,
            )
        if status >= 400:
            raise AdaAPIError(
                f"API error {status}: {response.text[:200]}",
                status_code=status,
                response_body=response.text,
            )

        # Success responses
        if not response.text:
            return None

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                return response.json()
            except Exception:
                return response.text
        return response.text

    # ---- Path Encoding ----

    @staticmethod
    def encode_path(path: str) -> str:
        """URL-encode a dCache namespace path."""
        return encode_path(path)

    # ---- Lifecycle ----

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
