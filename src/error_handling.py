"""
Simple error handling for the Twitch Color Changer bot
"""

import asyncio
import logging

from .logger import logger


class APIError(Exception):
    """API request error with optional status code"""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


async def simple_retry(func, max_retries=3, delay=1, user=None):
    """Simple retry with exponential backoff"""
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as e:  # noqa: BLE001
            if attempt == max_retries:
                log_error("Max retries exceeded", e, user)
                raise
            wait_time = delay * (2**attempt)
            logger.log_event(
                "retry",
                "attempt",
                level=logging.WARNING,
                attempt=attempt + 1,
                max_retries=max_retries,
                wait_time=wait_time,
                user=user,
                error=str(e),
            )
            await asyncio.sleep(wait_time)


def log_error(message: str, error: Exception, user: str = None):
    """Log error with optional user context via structured event"""
    logger.log_event(
        "error",
        "logged",
        level=logging.ERROR,
        message=message,
        user=user,
        error=str(error),
    )
