"""Low-level HTTP client for the dCache REST API.

Wraps ``httpx`` and takes care of authentication, parsing JSON
responses, turning HTTP errors into ADA exceptions, debug logging of
requests, and streaming Server-Sent Events. Library users normally use
:class:`~ada.client.AdaClient` instead.
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


def build_ssl_kwargs(auth: AuthProvider, verify: bool) -> dict[str, Any]:
    """Build the TLS settings for an ``httpx.Client``.

    Shared between :class:`DcacheAPI` (REST) and the WebDAV client,
    since both need the same client certificate handling for proxy
    authentication.

    Args:
        auth: The authentication method. For proxy authentication, its
            SSL context holds the client certificate.
        verify: Verify the server's TLS certificate.

    Returns:
        Keyword arguments for ``httpx.Client``, with ``verify=False``,
        with an SSL context as ``verify``, or empty (the httpx defaults).
    """
    kwargs: dict[str, Any] = {}
    if verify is False:
        kwargs["verify"] = False
        return kwargs
    ssl_ctx = auth.get_ssl_context()
    if ssl_ctx:
        kwargs["verify"] = ssl_ctx
    return kwargs


class DcacheAPI:
    """Low-level HTTP client for the dCache REST API.

    All service modules use this client to make API calls. Redirects are
    followed. Requests time out after 30 seconds, or 300 seconds while
    reading the response.

    Args:
        base_url: URL of the REST API, e.g.
            ``"https://dcache.example.org:3880/api/v1"``.
        auth: The authentication method, which provides the headers,
            credentials or client certificate for each request.
        verify: Verify the server's TLS certificate. Disabling it logs a
            warning.
        debug: Log each request and response at debug level.
    """

    def __init__(
        self,
        base_url: str,
        auth: AuthProvider,
        verify: bool = True,
        debug: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.verify = verify
        self.debug = debug

        # Build httpx client with appropriate auth and SSL settings
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(30.0, read=300.0),
            "follow_redirects": True,
        }

        # verify: False to disable verification
        if verify is False:
            logger.warning("WARNING: You have disabled SSL verification, connection may be insecure!")
        client_kwargs.update(build_ssl_kwargs(auth, verify))

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
        """Send a GET request.

        Args:
            endpoint: API endpoint, relative to the base URL, e.g.
                ``"namespace/%2Fpnfs%2Fdata"``.
            params: Query parameters.
            accept: Value of the Accept header.

        Returns:
            The parsed JSON response, the response text if it isn't
            JSON, or None if the response is empty.

        Raises:
            AdaAuthenticationError: If dCache rejected the credentials
                (HTTP 401).
            AdaForbiddenError: If access is forbidden (HTTP 403).
            AdaNotFoundError: If the resource does not exist (HTTP 404).
            AdaAPIError: For other HTTP errors (status 400 and higher).
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if self.debug:
            logger.debug("GET %s params=%s", url, params)
        response = self._client.get(
            url, headers=self._headers(accept=accept), params=params,
            auth=self._httpx_auth(),
        )
        return self._handle_response(response)

    def get_absolute(
        self,
        url: str,
        accept: str = "application/json",
    ) -> Any:
        """Send a GET request to a URL outside the REST API base path.

        Used for endpoints that live alongside the REST API rather than
        under it (e.g. ``/scripts/config.js``, used for WebDAV door
        discovery), while reusing the same authentication, TLS and
        timeout settings.

        Args:
            url: The complete URL.
            accept: Value of the Accept header.

        Returns:
            The parsed JSON response, the response text if it isn't
            JSON, or None if the response is empty.

        Raises:
            AdaAuthenticationError: If dCache rejected the credentials
                (HTTP 401).
            AdaForbiddenError: If access is forbidden (HTTP 403).
            AdaNotFoundError: If the resource does not exist (HTTP 404).
            AdaAPIError: For other HTTP errors (status 400 and higher).
        """
        if self.debug:
            logger.debug("GET (absolute) %s", url)
        response = self._client.get(
            url, headers=self._headers(accept=accept), auth=self._httpx_auth(),
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
        """Send a POST request, with a JSON body or other data.

        Args:
            endpoint: API endpoint, relative to the base URL.
            json: Body to send as JSON. Takes precedence over ``data``.
            data: Body to send as text, if ``json`` is not given.
            content_type: Value of the Content-Type header.
            accept: Value of the Accept header.

        Returns:
            The parsed JSON response, the response text if it isn't
            JSON, or None if the response is empty.

        Raises:
            AdaAuthenticationError: If dCache rejected the credentials
                (HTTP 401).
            AdaForbiddenError: If access is forbidden (HTTP 403).
            AdaNotFoundError: If the resource does not exist (HTTP 404).
            AdaAPIError: For other HTTP errors (status 400 and higher).
        """
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
        """Send a POST request with a JSON body, and return the raw response.

        For callers that need the response headers, like bulk requests.
        HTTP errors are not turned into exceptions: check the status code
        of the response.

        Args:
            endpoint: API endpoint, relative to the base URL.
            json: Body to send as JSON.

        Returns:
            The response.
        """
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
        """Send a DELETE request.

        Args:
            endpoint: API endpoint, relative to the base URL.

        Returns:
            The parsed JSON response, the response text if it isn't
            JSON, or None if the response is empty.

        Raises:
            AdaAuthenticationError: If dCache rejected the credentials
                (HTTP 401).
            AdaForbiddenError: If access is forbidden (HTTP 403).
            AdaNotFoundError: If the resource does not exist (HTTP 404).
            AdaAPIError: For other HTTP errors (status 400 and higher).
        """
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
        """Send a PATCH request with a JSON body.

        Args:
            endpoint: API endpoint, relative to the base URL.
            json: Body to send as JSON.

        Returns:
            The parsed JSON response, the response text if it isn't
            JSON, or None if the response is empty.

        Raises:
            AdaAuthenticationError: If dCache rejected the credentials
                (HTTP 401).
            AdaForbiddenError: If access is forbidden (HTTP 403).
            AdaNotFoundError: If the resource does not exist (HTTP 404).
            AdaAPIError: For other HTTP errors (status 400 and higher).
        """
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
        """Open a Server-Sent Events (SSE) connection and yield the events.

        Args:
            endpoint: API endpoint of the event channel, relative to the
                base URL.
            last_event_id: Resume after this event, by sending it as the
                Last-Event-ID header.
            timeout: Close the connection when no data arrives for this
                many seconds.

        Yields:
            Each event as a dict with the keys ``event``, ``data`` and
            ``id``, each only present if the event has it. Data of
            multiple ``data:`` lines is joined with newlines.

        Raises:
            AdaAuthenticationError: If dCache rejected the credentials
                (HTTP 401).
            AdaForbiddenError: If access is forbidden (HTTP 403).
            AdaNotFoundError: If the resource does not exist (HTTP 404).
            AdaAPIError: For other HTTP errors (status 400 and higher).
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
        """URL-encode a dCache path, see :func:`ada.utils.encode_path`.

        Args:
            path: dCache path.

        Returns:
            The encoded path.
        """
        return encode_path(path)

    # ---- Lifecycle ----

    def close(self) -> None:
        """Close the network connections."""
        self._client.close()
