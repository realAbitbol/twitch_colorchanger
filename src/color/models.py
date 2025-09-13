"""Models for color change operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ColorRequestStatus(Enum):
    """Enumeration of possible statuses for color change requests.

    Attributes:
        SUCCESS: The color change was successful.
        RATE_LIMIT: The request was rate limited.
        UNAUTHORIZED: The request was unauthorized.
        TIMEOUT: The request timed out.
        INTERNAL_ERROR: An internal error occurred.
        HTTP_ERROR: An HTTP error occurred.
    """

    SUCCESS = "success"
    RATE_LIMIT = "rate_limit"
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"
    HTTP_ERROR = "http_error"


@dataclass(slots=True)
class ColorRequestResult:
    """Result of a color change request.

    Attributes:
        status (ColorRequestStatus): The status of the request.
        http_status (int | None): The HTTP status code, if applicable.
        error (str | None): Error message, if any.
    """

    status: ColorRequestStatus
    http_status: int | None = None
    error: str | None = None


__all__ = ["ColorRequestStatus", "ColorRequestResult"]
