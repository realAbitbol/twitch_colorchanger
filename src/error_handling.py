"""
Simple error handling for the Twitch Color Changer bot
"""

import asyncio

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
        except Exception as e:
            if attempt == max_retries:
                log_error("Max retries exceeded", e, user)
                raise

            wait_time = delay * (2 ** attempt)
            user_context = f" [user={user}]" if user else ""
            logger.warning(
                f"Retry {
                    attempt + 1}/{max_retries} in {wait_time}s{user_context}: {e}")
            await asyncio.sleep(wait_time)


def log_error(message: str, error: Exception, user: str = None):
    """Log error with optional user context"""
    user_context = f" [user={user}]" if user else ""
    logger.error(f"{message}{user_context}: {error}")
