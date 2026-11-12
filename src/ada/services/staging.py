"""Staging service: bringing files from tape to disk, and releasing them.

Staging creates a bulk request in dCache that copies files from tape to
disk and pins them there for a while. Unstaging releases the pins, so
dCache may remove the disk copies. Both run in the background in dCache;
their bulk requests can be followed and deleted.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ada.exceptions import (
    AdaAPIError,
    AdaForbiddenError
)
from ada.models import BulkRequest, BulkRequestStatus
from ada.utils import parse_lifetime, resolve_paths
from ada.services.namespace import NamespaceService

if TYPE_CHECKING:
    from ada.core.api import DcacheAPI

logger = logging.getLogger("ada.services.staging")


class StagingService:
    """Stage and unstage operations for dCache tape-backed storage.

    Args:
        api: Client for the dCache REST API.
        namespace: Namespace service to check path types with. Created
            when needed if not given.
    """

    def __init__(self, api: DcacheAPI, namespace: Optional[NamespaceService] = None) -> None:
        self._api = api
        self._namespace = namespace

    def _get_namespace(self) -> NamespaceService:
        if self._namespace is None:
            self._namespace = NamespaceService(self._api)
        return self._namespace

    def stage(
        self,
        paths: Optional[str | list[str]] = None,
        recursive: bool = False,
        lifetime: str = "7D",
        from_file: Optional[str] = None,
    ) -> BulkRequest:
        """Stage files from tape, so they are online (on disk) to be read.

        Staging also pins the files: dCache keeps the online copy at
        least until the pin lifetime has passed. Give either ``paths`` or
        ``from_file``.

        Args:
            paths: dCache path, or list of paths, of the files or
                directories to stage. For a directory, the files in it
                are staged.
            recursive: For directories, also stage the files in their
                subdirectories.
            lifetime: How long the files stay pinned, as a number with a
                unit: S, M, H or D, e.g. ``"12H"`` or ``"7D"``.
            from_file: Local file with one dCache path per line.

        Returns:
            The bulk request that dCache created.

        Raises:
            AdaValidationError: If the lifetime is not valid, both or
                neither of ``paths`` and ``from_file`` are given, or
                ``from_file`` contains no paths.
            FileNotFoundError: If ``from_file`` does not exist.
            AdaForbiddenError: If the server refuses the request (HTTP
                403 or 422), e.g. because staging directories
                (recursively) is not allowed.
            AdaAPIError: If the request fails otherwise.
        """
        lifetime_value, lifetime_unit = parse_lifetime(lifetime)

        # Determine expand mode based on recursive flag
        if recursive:
            expand = "ALL"
        else:
            # Get list of paths
            target_paths = resolve_paths(paths, from_file)
            # Check if any path is a directory
            ns = self._get_namespace()
            has_dir = any(ns.is_dir(p) for p in target_paths)
            expand = "TARGETS" if has_dir else "NONE"

        target_paths = resolve_paths(paths, from_file)
        lifetime_millis = self._lifetime_to_millis(lifetime_value, lifetime_unit)

        body = {
            "activity": "PIN",
            "target": target_paths,
            "arguments": {
                "lifetime": str(lifetime_millis),
                "lifetimeUnit": "MILLISECONDS",
            },
            "expandDirectories": expand,
        }

        response = self._api.post_raw("bulk-requests", json=body)

        if response.status_code in (403, 422):
            self._handle_bulk_error(response, expand)

        if response.status_code >= 400:
            raise AdaAPIError(
                f"Stage request failed: {response.text[:200]}",
                status_code=response.status_code,
                response_body=response.text,
            )

        # Extract request ID from Location header or response body
        request_url = response.headers.get("request-url", "")
        request_id = request_url.rsplit("/", 1)[-1] if request_url else ""

        if not request_id:
            try:
                data = response.json()
                request_id = str(data.get("id", data.get("uid", "")))
                request_url = data.get("url", request_url)
            except Exception:
                pass

        return BulkRequest(
            request_id=request_id,
            request_url=request_url,
            activity="PIN",
            targets=tuple(target_paths),
        )

    def unstage(
        self,
        paths: Optional[str | list[str]] = None,
        recursive: bool = False,
        request_id: Optional[str] = None,
        from_file: Optional[str] = None,
    ) -> BulkRequest:
        """Unstage files: release their pins, so dCache may remove the disk copy.

        Give either ``paths`` or ``from_file``.

        Args:
            paths: dCache path, or list of paths, of the files or
                directories to unstage. For a directory, the files in it
                are unstaged.
            recursive: For directories, also unstage the files in their
                subdirectories.
            request_id: Only release the pin created by this earlier
                stage request. By default, all pins of the files are
                released.
            from_file: Local file with one dCache path per line.

        Returns:
            The bulk request that dCache created.

        Raises:
            AdaValidationError: If both or neither of ``paths`` and
                ``from_file`` are given, or ``from_file`` contains no
                paths.
            FileNotFoundError: If ``from_file`` does not exist.
            AdaForbiddenError: If the server refuses the request (HTTP
                403 or 422), e.g. because unstaging directories
                (recursively) is not allowed.
            AdaAPIError: If the request fails otherwise.
        """
        target_paths = resolve_paths(paths, from_file)

        if recursive:
            expand = "ALL"
        else:
            ns = self._get_namespace()
            has_dir = any(ns.is_dir(p) for p in target_paths)
            expand = "TARGETS" if has_dir else "NONE"

        body: dict = {
            "activity": "UNPIN",
            "target": target_paths,
            "expandDirectories": expand,
        }

        if request_id:
            body["arguments"] = {"id": request_id}

        response = self._api.post_raw("bulk-requests", json=body)

        if response.status_code in (403, 422):
            self._handle_bulk_error(response, expand)

        if response.status_code >= 400:
            raise AdaAPIError(
                f"Unstage request failed: {response.text[:200]}",
                status_code=response.status_code,
                response_body=response.text,
            )

        request_url = response.headers.get("request-url", "")
        rid = request_url.rsplit("/", 1)[-1] if request_url else ""

        if not rid:
            try:
                data = response.json()
                rid = str(data.get("id", data.get("uid", "")))
            except Exception:
                pass

        return BulkRequest(
            request_id=rid,
            request_url=request_url,
            activity="UNPIN",
            targets=tuple(target_paths),
        )

    def stat_request(self, request_id: str) -> BulkRequestStatus:
        """Get the status of a bulk request.

        Args:
            request_id: ID of the request.

        Returns:
            The status of the request and of each file in it.

        Raises:
            AdaNotFoundError: If the request does not exist.
        """
        data = self._api.get(f"bulk-requests/{request_id}")
        return BulkRequestStatus(
            uid=data.get("uid", data.get("id", request_id)),
            status=data.get("status", "UNKNOWN"),
            targets=tuple(data.get("targets", [])),
            raw=data,
        )

    def delete_request(self, request_id: str) -> None:
        """Delete a bulk request.

        Args:
            request_id: ID of the request.

        Raises:
            AdaNotFoundError: If the request does not exist.
        """
        self._api.delete(f"bulk-requests/{request_id}")

    # ---- Internal ----

    @staticmethod
    def _lifetime_to_millis(value: int, unit: str) -> int:
        """Convert lifetime value and unit to milliseconds."""
        multipliers = {"S": 1000, "M": 60_000, "H": 3_600_000, "D": 86_400_000}
        return value * multipliers.get(unit, 86_400_000)

    @staticmethod
    def _handle_bulk_error(response, expand: str) -> None:
        """Raise descriptive errors for 403/422 on bulk requests."""
        if expand == "ALL":
            raise AdaForbiddenError(
                "Staging failed. Recursive staging may be prohibited by the server. "
                "Try without --recursive. "
                "Ask the system administrators to set "
                "'bulk.allowed-directory-expansion=ALL' if recursive staging is needed.",
                response_body=response.text,
            )
        if expand == "TARGETS":
            raise AdaForbiddenError(
                "Staging failed. Staging a directory may be prohibited by the server. "
                "Try staging individual files instead. "
                "Ask the system administrators to set "
                "'bulk.allowed-directory-expansion=TARGETS' if directory staging is needed.",
                response_body=response.text,
            )
        raise AdaForbiddenError(
            f"Staging failed: {response.text[:200]}",
            response_body=response.text,
        )
