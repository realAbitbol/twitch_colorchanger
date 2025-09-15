import aiohttp

from src.utils.retry import retry_async


def fast_backoff(attempt):
    return 0


async def fast_retry_async(operation, max_attempts=6):
    """Retry async operation with fast backoff."""
    return await retry_async(operation, max_attempts)


async def no_sleep_retry_async(operation, max_attempts=6, backoff_func=None):
    """Retry async operation without sleeping."""
    for attempt in range(max_attempts):
        try:
            result, should_retry = await operation(attempt)
            if not should_retry:
                return result
        except (RuntimeError, ValueError, OSError, aiohttp.ClientError):
            should_retry = attempt < max_attempts - 1
            if not should_retry:
                raise
        # No sleep
    return None
