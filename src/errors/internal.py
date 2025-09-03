"""Centralized internal error hierarchy.

These exceptions provide semantic categories for retry logic and higher-level
error handling. Only raise these inside application/network boundaries – never
directly surface raw aiohttp / JSON errors to retry code; wrap them instead.

Classes:
  InternalError        – Base for all internal errors.
  NetworkError         – Transient network/IO issues (safe to retry).
  OAuthError           – Authentication / authorization related failures.
  ParsingError         – Response parsing / schema validation issues.
  RateLimitError       – Explicit rate limiting signalled by remote service.

Each subclass sets the transient flag indicating whether automated retry
policies should consider another attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class InternalError(Exception):
    """Base internal exception with optional metadata and transience flag."""

    transient: bool = False  # Override in subclasses if appropriate

    def __init__(self, message: str, *, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.data = data or {}

    def is_transient(self) -> bool:  # Small convenience helper
        return getattr(self, "transient", False)


class NetworkError(InternalError):
    """Network / transport layer error (timeouts, connection resets)."""

    transient = True


class OAuthError(InternalError):
    """Authentication / authorization failures (usually non‑transient)."""

    transient = False


class ParsingError(InternalError):
    """Response body parsing or schema mismatch (usually non‑transient)."""

    transient = False


@dataclass
class RateLimitContext:
    reset_in: float | None = None
    limit: int | None = None
    remaining: int | None = None


class RateLimitError(InternalError):
    """Explicit rate limiting encountered.

    Depending on policy this may be retried after a delay; we mark transient
    so retry strategies can apply backoff or defer to a rate limiter component.
    """

    transient = True

    def __init__(
        self, message: str = "Rate limited", *, context: RateLimitContext | None = None
    ):
        super().__init__(message, data={"rate_limit": context})


__all__ = [
    "InternalError",
    "NetworkError",
    "OAuthError",
    "ParsingError",
    "RateLimitError",
    "RateLimitContext",
]
