"""Staging service — tape staging and unstaging operations.

Handles bringing files from tape to disk (staging), releasing disk copies
(unstaging), and managing bulk requests.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from ada.exceptions import (
    AdaAPIError,
    AdaForbiddenError,
    AdaValidationError,
)
from ada.models import BulkRequest, BulkRequestStatus, FileType
from ada.utils import encode_path, parse_lifetime, read_file_list

if TYPE_CHECKING:
    from ada.core.api import DcacheAPI
    from ada.services.namespace import NamespaceService

logger = logging.getLogger("ada.services.staging")


class StagingService:
    """Stage/unstage operations for dCache tape-backed storage."""

    def __init__(self, api: DcacheAPI, namespace: Optional[NamespaceService] = None) -> None:
        self._api = api
        self._namespace = namespace

    def _get_namespace(self) -> NamespaceService:
        if self._namespace is None:
            from ada.services.namespace import NamespaceService
            self._namespace = NamespaceService(self._api)
        return self._namespace

    def stage(
        self,
        paths: str | list[str],
        recursive: bool = False,
        lifetime: str = "7D",
        from_file: Optional[str] = None,
    ) -> BulkRequest:
        """Stage files from tape to disk.

        Args:
            paths: File or directory path(s) to stage.
            recursive: If True, stage files recursively in directories.
            lifetime: How long to keep files online (e.g., '7D', '24H').
            from_file: Path to a file containing one path per line.

        Returns:
            BulkRequest with the request ID and details.
        """
        lifetime_value, lifetime_unit = parse_lifetime(lifetime)

        # Determine expand mode based on recursive flag
        if recursive:
            expand = "ALL"
        else:
            # Check if any path is a directory
            target_paths = self._resolve_paths(paths, from_file)
            ns = self._get_namespace()
            has_dir = any(ns.is_dir(p) for p in target_paths)
            expand = "TARGETS" if has_dir else "NONE"

        target_paths = self._resolve_paths(paths, from_file)
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
        request_url = response.headers.get("Location", "")
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
        paths: str | list[str],
        recursive: bool = False,
        request_id: Optional[str] = None,
        from_file: Optional[str] = None,
    ) -> BulkRequest:
        """Unstage files — release pins so dCache can purge disk copies.

        Args:
            paths: File or directory path(s) to unstage.
            recursive: If True, unstage files recursively.
            request_id: Specific bulk request ID to unpin.
            from_file: Path to a file containing one path per line.

        Returns:
            BulkRequest with details.
        """
        target_paths = self._resolve_paths(paths, from_file)

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

        request_url = response.headers.get("Location", "")
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
            request_id: The bulk request ID.

        Returns:
            BulkRequestStatus with target details.
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
            request_id: The bulk request ID to delete.
        """
        self._api.delete(f"bulk-requests/{request_id}")

    # ---- Internal ----

    def _resolve_paths(
        self, paths: str | list[str], from_file: Optional[str] = None
    ) -> list[str]:
        """Resolve paths from arguments or file list."""
        if from_file:
            return read_file_list(from_file)
        if isinstance(paths, str):
            return [paths]
        return list(paths)

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
        elif expand == "TARGETS":
            raise AdaForbiddenError(
                "Staging failed. Staging a directory may be prohibited by the server. "
                "Try staging individual files instead. "
                "Ask the system administrators to set "
                "'bulk.allowed-directory-expansion=TARGETS' if directory staging is needed.",
                response_body=response.text,
            )
        else:
            raise AdaForbiddenError(
                f"Staging failed: {response.text[:200]}",
                response_body=response.text,
            )
