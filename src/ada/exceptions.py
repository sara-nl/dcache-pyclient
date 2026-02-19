"""Exception hierarchy for ADA.

All exceptions inherit from AdaError, allowing callers to catch
broad or specific error categories as needed.
"""

from __future__ import annotations


class AdaError(Exception):
    """Base exception for all ADA errors."""


class AdaConfigError(AdaError):
    """Configuration is missing or invalid."""


class AdaSecurityError(AdaError):
    """Security violation (e.g., world-readable credentials)."""


class AdaAuthError(AdaError):
    """Authentication setup error (missing file, invalid format)."""


class AdaTokenExpiredError(AdaAuthError):
    """Token has expired or is about to expire."""

    def __init__(self, message: str, seconds_ago: int = 0) -> None:
        super().__init__(message)
        self.seconds_ago = seconds_ago


class AdaTokenPermissionError(AdaAuthError):
    """Token lacks required permissions (e.g., storage.stage)."""


class AdaAuthenticationError(AdaError):
    """Server rejected credentials (HTTP 401)."""


class AdaAPIError(AdaError):
    """dCache API returned an error."""

    def __init__(
        self, message: str, status_code: int = 0, response_body: str = ""
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class AdaNotFoundError(AdaAPIError):
    """Resource not found (HTTP 404)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class AdaForbiddenError(AdaAPIError):
    """Access forbidden (HTTP 403)."""

    def __init__(self, message: str, response_body: str = "") -> None:
        super().__init__(message, status_code=403, response_body=response_body)


class AdaPathError(AdaError):
    """Invalid path or path type mismatch."""


class AdaValidationError(AdaError):
    """Input validation error."""
