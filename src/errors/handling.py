"""Legacy simple retry utilities (deprecated in favor of retry_policies).

simple_retry now delegates to run_with_retry for backward compatibility. New
code should import RetryPolicy / run_with_retry directly.
"""

from __future__ import annotations

import logging

## Removed legacy simple_retry wrapper (superseded by run_with_retry)  # noqa: ERA001


def log_error(
    message: str, error: Exception, user: str | None = None
) -> None:  # pragma: no cover
    logging.error(f"💥 Error: {message} user={user} details={str(error)}")
