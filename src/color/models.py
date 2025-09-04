"""Models for color change operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ColorRequestStatus(Enum):
    SUCCESS = "success"
    RATE_LIMIT = "rate_limit"
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"
    HTTP_ERROR = "http_error"


@dataclass(slots=True)
class ColorRequestResult:
    status: ColorRequestStatus
    http_status: int | None = None
    error: str | None = None


__all__ = ["ColorRequestStatus", "ColorRequestResult"]
