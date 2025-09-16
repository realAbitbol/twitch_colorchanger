"""ChannelResolver for resolving Twitch user IDs with caching and batch processing.

This module provides the ChannelResolver class that efficiently resolves Twitch
login names to user IDs using the Twitch Helix API, with integrated caching
for performance and graceful error handling.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..api.twitch import TwitchAPI
from ..chat.cache_manager import CacheManager
from ..errors.eventsub import CacheError, EventSubError
from .protocols import ChannelResolverProtocol

logger = logging.getLogger(__name__)


class ChannelResolver(ChannelResolverProtocol):
    """Resolves Twitch login names to user IDs with caching and batch processing.

    This class provides an efficient way to resolve multiple Twitch channel
    login names to their corresponding user IDs. It integrates local file-based
    caching for performance and handles API failures gracefully.

    Features:
    - Batch processing of multiple logins (up to Twitch API limits)
    - Local caching to reduce API calls
    - Concurrent processing for large batches
    - Graceful error handling with custom exceptions
    - Comprehensive logging for debugging

    Attributes:
        _twitch_api (TwitchAPI): The Twitch API client instance.
        _cache_manager (CacheManager): The cache manager for persistent storage.
        _max_concurrent_batches (int): Maximum concurrent API batches.

    Example:
        >>> resolver = ChannelResolver(twitch_api, cache_manager)
        >>> user_ids = await resolver.resolve_user_ids(
        ...     ["user1", "user2"], "token", "client_id"
        ... )
        >>> print(user_ids)
        {'user1': '12345', 'user2': '67890'}
    """

    def __init__(
        self,
        twitch_api: TwitchAPI,
        cache_manager: CacheManager,
        max_concurrent_batches: int = 3,
    ) -> None:
        """Initialize the ChannelResolver.

        Args:
            twitch_api (TwitchAPI): The Twitch API client for user resolution.
            cache_manager (CacheManager): The cache manager for storing user IDs.
            max_concurrent_batches (int): Maximum number of concurrent API batches.
                                       Defaults to 3 to balance performance and rate limits.

        Raises:
            ValueError: If twitch_api or cache_manager is None.
        """
        if not twitch_api:
            raise ValueError("twitch_api cannot be None")
        if not cache_manager:
            raise ValueError("cache_manager cannot be None")

        self._twitch_api = twitch_api
        self._cache_manager = cache_manager
        self._max_concurrent_batches = max_concurrent_batches

    async def resolve_user_ids(
        self,
        logins: list[str],
        access_token: str,
        client_id: str,
    ) -> dict[str, str]:
        """Resolve a list of Twitch login names to user IDs.

        This method first checks the cache for existing user IDs, then makes
        batched API calls for missing logins. Results are cached for future use.
        Failed resolutions are logged but don't stop the process.

        Args:
            logins (list[str]): List of Twitch login names to resolve.
            access_token (str): OAuth access token for Twitch API.
            client_id (str): Twitch application client ID.

        Returns:
            dict[str, str]: Mapping of lowercase login names to user IDs.
                           Unknown or failed logins are omitted.

        Raises:
            EventSubError: If the Twitch API call fails critically.
            CacheError: If cache operations fail.

        Example:
            >>> user_ids = await resolver.resolve_user_ids(
            ...     ["alice", "bob", "charlie"], "token", "client_id"
            ... )
            >>> print(user_ids)
            {'alice': '11111', 'bob': '22222'}
        """
        if not logins:
            return {}

        # Deduplicate logins case-insensitively
        seen: set[str] = set()
        unique_logins: list[str] = []
        for login in logins:
            lower_login = login.lower()
            if lower_login not in seen:
                seen.add(lower_login)
                unique_logins.append(login)

        logger.debug(f"Resolving {len(unique_logins)} unique logins")

        # Check cache first
        cached_results: dict[str, str] = {}
        uncached_logins: list[str] = []

        for login in unique_logins:
            try:
                cached_id = await self._cache_manager.get(login.lower())
                if cached_id is not None:
                    cached_results[login.lower()] = str(cached_id)
                else:
                    uncached_logins.append(login)
            except CacheError as e:
                logger.warning(f"Cache read failed for {login}: {e}")
                uncached_logins.append(login)

        logger.debug(
            f"Found {len(cached_results)} cached, {len(uncached_logins)} to resolve"
        )

        # Resolve uncached logins via API
        if uncached_logins:
            api_results = await self._resolve_via_api(
                uncached_logins, access_token, client_id
            )

            # Cache successful results
            for login_lower, user_id in api_results.items():
                try:
                    await self._cache_manager.set(login_lower, user_id)
                except CacheError as e:
                    logger.warning(f"Failed to cache {login_lower}: {e}")

            # Merge results
            cached_results.update(api_results)

        return cached_results

    async def _resolve_via_api(
        self,
        logins: list[str],
        access_token: str,
        client_id: str,
    ) -> dict[str, str]:
        """Resolve logins via Twitch API with concurrent batch processing.

        Args:
            logins (list[str]): List of login names to resolve.
            access_token (str): OAuth access token.
            client_id (str): Twitch client ID.

        Returns:
            dict[str, str]: Mapping of lowercase logins to user IDs.

        Raises:
            EventSubError: If API calls fail.
        """
        if not logins:
            return {}

        # Split into batches for concurrent processing
        batch_size = 100  # Twitch API limit per request
        batches = [
            logins[i : i + batch_size] for i in range(0, len(logins), batch_size)
        ]

        logger.debug(f"Processing {len(batches)} batches concurrently")

        # Create tasks for concurrent execution
        tasks = [
            self._twitch_api.get_users_by_login(
                access_token=access_token,
                client_id=client_id,
                logins=batch,
            )
            for batch in batches
        ]

        # Limit concurrency
        semaphore = asyncio.Semaphore(self._max_concurrent_batches)

        async def _limited_task(task):
            async with semaphore:
                return await task

        try:
            # Execute batches concurrently with limit
            results = await asyncio.gather(
                *[_limited_task(task) for task in tasks],
                return_exceptions=True,
            )
        except Exception as e:
            raise EventSubError(
                f"Failed to resolve user IDs: {e}",
                operation_type="resolve_user_ids",
            ) from e

        # Process results
        api_results: dict[str, str] = {}
        failed_batches = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Batch {i} failed: {result}")
                failed_batches += 1
                continue
            elif isinstance(result, dict):
                api_results.update(result)
            else:
                logger.warning(f"Unexpected result type from batch {i}: {type(result)}")

        logger.debug(f"Resolved {len(api_results)} users via API")

        # If all batches failed, raise error
        if failed_batches == len(batches) and logins:
            raise EventSubError(
                f"All {failed_batches} API batches failed to resolve {len(logins)} logins",
                operation_type="resolve_user_ids",
            )

        return api_results

    async def invalidate_cache(self, login: str) -> None:
        """Invalidate the cache entry for a specific login.

        Args:
            login (str): The login name to invalidate.

        Raises:
            CacheError: If cache deletion fails.
        """
        try:
            await self._cache_manager.delete(login.lower())
            logger.debug(f"Invalidated cache for {login}")
        except CacheError as e:
            raise CacheError(
                f"Failed to invalidate cache for {login}: {e}",
                operation_type="invalidate_cache",
            ) from e

    async def clear_cache(self) -> None:
        """Clear all cached user ID mappings.

        Raises:
            CacheError: If cache clearing fails.
        """
        try:
            await self._cache_manager.clear()
            logger.debug("Cleared all user ID cache")
        except CacheError as e:
            raise CacheError(
                f"Failed to clear cache: {e}",
                operation_type="clear_cache",
            ) from e

    async def __aenter__(self) -> ChannelResolver:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        # No specific cleanup needed for ChannelResolver
        pass
