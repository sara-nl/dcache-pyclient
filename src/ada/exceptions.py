"""Exception hierarchy for ADA.

All exceptions inherit from :class:`AdaError`, so you can catch all
ADA errors at once, or only specific ones::

    AdaError
    ├── AdaConfigError
    ├── AdaSecurityError
    ├── AdaAuthError
    │   ├── AdaTokenExpiredError
    │   └── AdaTokenPermissionError
    ├── AdaAuthenticationError
    ├── AdaAPIError
    │   ├── AdaNotFoundError
    │   └── AdaForbiddenError
    ├── AdaPathError
    ├── AdaTransferError
    └── AdaValidationError

Note that :class:`AdaAuthError` is about your credentials before they
are sent (e.g. an expired token), while :class:`AdaAuthenticationError`
means dCache rejected them.

Example::

    from ada import AdaClient
    from ada.exceptions import AdaError, AdaNotFoundError

    try:
        with AdaClient(tokenfile="~/macaroon.conf") as client:
            client.list("/pnfs/example.org/data/run1")
    except AdaNotFoundError:
        print("Directory not found")
    except AdaError as exc:
        print(f"ADA error: {exc}")
"""

from __future__ import annotations


class AdaError(Exception):
    """Base class for all ADA errors."""


class AdaConfigError(AdaError):
    """The configuration is invalid, e.g. an API URL without ``https://``."""


class AdaSecurityError(AdaError):
    """A credentials or config file is readable or writable by others.

    Fix the file permissions, e.g. with ``chmod 600 <file>``.
    """


class AdaAuthError(AdaError):
    """The credentials can't be used: none were found, a file is missing,
    or a token can't be decoded."""


class AdaTokenExpiredError(AdaAuthError):
    """The token or proxy has expired, or expires within 60 seconds.

    Attributes:
        seconds_ago: How many seconds ago it expired; 0 if it has not
            expired yet but is about to.
    """

    def __init__(self, message: str, seconds_ago: int = 0) -> None:
        super().__init__(message)
        self.seconds_ago = seconds_ago


class AdaTokenPermissionError(AdaAuthError):
    """The token does not allow the operation, e.g. a macaroon without
    the ``STAGE`` activity, or an OIDC token without the
    ``storage.stage`` scope, when staging."""


class AdaAuthenticationError(AdaError):
    """dCache rejected the credentials (HTTP 401)."""


class AdaAPIError(AdaError):
    """The dCache API returned an error.

    Attributes:
        status_code: The HTTP status code, e.g. 400 or 500; 0 if the
            error didn't come with one.
        response_body: The body of the API response, which often
            explains the error.
    """

    def __init__(
        self, message: str, status_code: int = 0, response_body: str = ""
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class AdaNotFoundError(AdaAPIError):
    """The file, directory or request does not exist (HTTP 404).

    Attributes:
        url: The full API URL that returned the 404; empty if unknown.
    """

    def __init__(self, message: str, url: str = "") -> None:
        super().__init__(message, status_code=404)
        self.url = url


class AdaForbiddenError(AdaAPIError):
    """dCache refused the operation (HTTP 403), e.g. because your
    credentials don't give access to the path."""

    def __init__(self, message: str, response_body: str = "") -> None:
        super().__init__(message, status_code=403, response_body=response_body)


class AdaPathError(AdaError):
    """A path can't be used for the operation, e.g. a directory where a
    file is expected, a target that already exists, or a missing parent
    directory."""


class AdaTransferError(AdaError):
    """An upload or download could not be done.

    For example: no WebDAV door could be found, a redirect was refused,
    the checksums don't match, or the file is only on tape and must be
    staged first.
    """


class AdaValidationError(AdaError):
    """An argument is invalid, e.g. a lifetime in the wrong format, or
    both or neither of two alternative arguments are given."""
