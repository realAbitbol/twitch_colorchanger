"""Advanced rate limiter that uses Twitch Helix API rate limiting headers"""

import asyncio
import logging
import time
from dataclasses import dataclass

from ..constants import (
    DEFAULT_BUCKET_LIMIT,
    RATE_LIMIT_SAFETY_BUFFER,
    STALE_BUCKET_AGE,
)
from ..logs.logger import logger
from .backoff_strategy import AdaptiveBackoff
from .rate_limit_headers import parse_rate_limit_headers


@dataclass
class RateLimitInfo:
    """Rate limit information from Twitch API headers"""

    limit: int  # Rate at which points are added to bucket
    remaining: int  # Number of points remaining in bucket
    reset_timestamp: float  # Unix timestamp when bucket resets to full
    last_updated: float  # When this info was last updated
    monotonic_last_updated: float  # Monotonic time when last updated


class TwitchRateLimiter:
    """Manages Twitch API rate limiting with separate buckets for app and user
    access."""

    def __init__(self, client_id: str, username: str | None = None) -> None:
        self.client_id = client_id
        self.username = username
        # Buckets
        self.app_bucket: RateLimitInfo | None = None
        self.user_bucket: RateLimitInfo | None = None
        # Lock
        self._lock = asyncio.Lock()
        # Safety / timing
        self.safety_buffer = RATE_LIMIT_SAFETY_BUFFER
        self.min_delay = 0.1
        # Hysteresis
        self.hysteresis_threshold = 10
        self.is_conservative_mode = False
        # Adaptive backoff
        self._backoff = AdaptiveBackoff()

    # --------------------------- Introspection --------------------------- #
    def snapshot(self) -> dict[str, object]:
        """Return a serializable snapshot of limiter state for debugging."""

        def bucket_view(bucket: RateLimitInfo | None) -> dict[str, object] | None:
            if not bucket:
                return None
            return {
                "limit": bucket.limit,
                "remaining": bucket.remaining,
                "reset_timestamp": bucket.reset_timestamp,
                "reset_in": max(0, bucket.reset_timestamp - time.time()),
                "last_updated": bucket.last_updated,
                "age": time.time() - bucket.last_updated,
            }

        return {
            "client_id": self.client_id,
            "username": self.username,
            "conservative_mode": self.is_conservative_mode,
            "safety_buffer": self.safety_buffer,
            "hysteresis_threshold": self.hysteresis_threshold,
            "app_bucket": bucket_view(self.app_bucket),
            "user_bucket": bucket_view(self.user_bucket),
            "backoff": self._backoff.snapshot(),
        }

    # Removed unused introspection helpers get_delay / is_rate_limited /
    # get_rate_limit_display.

    def _get_bucket_key(self, is_user_request: bool) -> str:
        """Get the bucket identifier for logging"""
        if is_user_request and self.username:
            return f"user:{self.username}"
        return f"app:{self.client_id}"

    def update_from_headers(
        self, headers: dict[str, str], is_user_request: bool = True
    ) -> None:
        """
        Update rate limit info from API response headers

        Args:
            headers: Response headers from Twitch API
            is_user_request: True if request used user access token, False for app token
        """
        try:
            # Debug: Show all headers that might contain rate limit info (debug mode
            # only)
            self._log_rate_limit_headers(headers, is_user_request)

            # Parse rate limit information from headers
            parsed = parse_rate_limit_headers(headers)
            if parsed:
                rate_info = RateLimitInfo(
                    limit=parsed.limit,
                    remaining=parsed.remaining,
                    reset_timestamp=parsed.reset_timestamp,
                    last_updated=parsed.last_updated,
                    monotonic_last_updated=parsed.monotonic_last_updated,
                )
                # Update appropriate bucket
                self._update_rate_limit_bucket(rate_info, is_user_request)
                # Log successful update
                self._log_rate_limit_update(rate_info, is_user_request)

        except (ValueError, TypeError) as e:
            bucket_key = self._get_bucket_key(is_user_request)
            logger.log_event(
                "rate_limit",
                "parse_headers_failed",
                level=logging.WARNING,
                bucket=bucket_key,
                error=str(e),
                error_type=type(e).__name__,
            )

    def _log_rate_limit_headers(
        self, headers: dict[str, str], is_user_request: bool
    ) -> None:
        """Log rate limit headers for debugging"""
        bucket_key = self._get_bucket_key(is_user_request)
        rate_headers = {k: v for k, v in headers.items() if "ratelimit" in k.lower()}
        if rate_headers:
            logger.log_event(
                "rate_limit",
                "headers",
                level=logging.DEBUG,
                bucket=bucket_key,
                headers=str(rate_headers),
            )
        else:
            logger.log_event(
                "rate_limit",
                "headers_missing",
                level=logging.DEBUG,
                bucket=bucket_key,
            )

    # Header parsing moved to rate_limit_headers.parse_rate_limit_headers

    def _update_rate_limit_bucket(
        self, rate_info: RateLimitInfo, is_user_request: bool
    ) -> None:
        """Update the appropriate rate limit bucket"""
        if is_user_request:
            self.user_bucket = rate_info
        else:
            self.app_bucket = rate_info

    def _log_rate_limit_update(
        self, rate_info: RateLimitInfo, is_user_request: bool
    ) -> None:
        """Log successful rate limit update"""
        bucket_key = self._get_bucket_key(is_user_request)
        reset_in = max(0, rate_info.reset_timestamp - time.time())
        logger.log_event(
            "rate_limit",
            "update",
            level=logging.DEBUG,
            bucket=bucket_key,
            remaining=rate_info.remaining,
            limit=rate_info.limit,
            resets_in=int(reset_in),
        )

    def _calculate_delay(self, bucket: RateLimitInfo, points_needed: int = 1) -> float:
        """
        Calculate optimal delay before next request using monotonic timing

        Args:
            bucket: Current rate limit info
            points_needed: Points required for the next request

        Returns:
            Delay in seconds (0 if no delay needed)
        """
        current_time = time.time()
        adjusted_reset = self._get_adjusted_reset_time(bucket, current_time)

        # Check if bucket info is stale
        if self._is_bucket_stale(bucket):
            return 1.0

        # Update conservative mode and get effective safety buffer
        effective_safety_buffer = self._update_conservative_mode(bucket, points_needed)

        # Check if we can make the request immediately
        if bucket.remaining >= points_needed + effective_safety_buffer:
            return 0

        # Calculate delay based on remaining points and time
        return self._calculate_delay_for_insufficient_points(
            bucket, points_needed, effective_safety_buffer, adjusted_reset, current_time
        )

    def _get_adjusted_reset_time(
        self, bucket: RateLimitInfo, current_time: float
    ) -> float:
        """Get adjusted reset time accounting for monotonic time drift"""
        current_monotonic = time.monotonic()

        if hasattr(bucket, "monotonic_last_updated"):
            elapsed_monotonic = current_monotonic - bucket.monotonic_last_updated
            return (
                bucket.reset_timestamp
                - (current_time - bucket.last_updated)
                + elapsed_monotonic
            )

        # Fallback for old bucket format
        return bucket.reset_timestamp

    def _is_bucket_stale(self, bucket: RateLimitInfo) -> bool:
        """Check if bucket info is too old to be reliable"""
        current_monotonic = time.monotonic()

        if hasattr(bucket, "monotonic_last_updated"):
            elapsed_monotonic = current_monotonic - bucket.monotonic_last_updated
        else:
            elapsed_monotonic = time.time() - bucket.last_updated

        if elapsed_monotonic > STALE_BUCKET_AGE:
            logger.log_event("rate_limit", "bucket_stale", level=logging.DEBUG)
            return True
        return False

    def _update_conservative_mode(
        self, bucket: RateLimitInfo, points_needed: int
    ) -> float:
        """Update conservative mode and return effective safety buffer"""
        # Apply hysteresis to avoid oscillation between modes
        effective_safety_buffer = self.safety_buffer
        if self.is_conservative_mode:
            effective_safety_buffer += self.hysteresis_threshold

        # Check if we can exit conservative mode
        if (
            self.is_conservative_mode
            and bucket.remaining > effective_safety_buffer + points_needed + 5
        ):
            self.is_conservative_mode = False
            effective_safety_buffer = self.safety_buffer

        # Check if we need to enter conservative mode
        if (
            not self.is_conservative_mode
            and bucket.remaining < self.safety_buffer + points_needed
        ):
            self.is_conservative_mode = True
            effective_safety_buffer = self.safety_buffer + self.hysteresis_threshold

        return effective_safety_buffer

    def _calculate_delay_for_insufficient_points(
        self,
        bucket: RateLimitInfo,
        points_needed: int,
        effective_safety_buffer: float,
        adjusted_reset: float,
        current_time: float,
    ) -> float:
        """Calculate delay when we don't have enough points available"""
        # If we're completely out of points, wait until reset
        if bucket.remaining < points_needed:
            reset_delay = max(0, adjusted_reset - current_time)
            logger.log_event(
                "rate_limit",
                "wait_until_reset",
                level=logging.WARNING,
                wait_seconds=round(reset_delay, 1),
            )
            return reset_delay + 0.1  # Add small buffer

        # Calculate delay based on regeneration rate
        time_until_reset = max(1, adjusted_reset - current_time)
        points_available = bucket.remaining - effective_safety_buffer

        if time_until_reset > 0:
            regeneration_rate = bucket.limit / time_until_reset
            points_deficit = points_needed - points_available

            if points_deficit > 0:
                estimated_wait = points_deficit / regeneration_rate
                return max(self.min_delay, estimated_wait)

        if points_available > 0:
            # Calculate delay to spread remaining points over remaining time
            optimal_delay = time_until_reset / points_available
            return max(self.min_delay, optimal_delay)

        # Fallback: wait until reset
        return max(0, adjusted_reset - current_time)

    async def wait_if_needed(
        self,
        endpoint: str = "default",
        is_user_request: bool = True,
        points_cost: int = 1,
    ) -> None:
        """
        Wait if necessary to respect rate limits before making a request

        Args:
            endpoint: API endpoint being called (for logging/tracking)
            is_user_request: True if using user access token, False for app token
            points_cost: Points cost of this request (default 1)
        """
        async with self._lock:
            # Adaptive backoff enforcement (applies before bucket logic)
            remaining = self._backoff.active_delay()
            if remaining > 0:
                logger.log_event(
                    "rate_limit",
                    "backoff_applied",
                    level=logging.WARNING if remaining > 1 else logging.DEBUG,
                    remaining=round(remaining, 2),
                    endpoint=endpoint,
                )
                await asyncio.sleep(remaining)

            # Get appropriate bucket
            bucket = self.user_bucket if is_user_request else self.app_bucket

            # If we don't have rate limit info yet, use minimal delay
            if bucket is None:
                logger.log_event(
                    "rate_limit",
                    "no_bucket_min_delay",
                    level=logging.DEBUG,
                    endpoint=endpoint,
                )
                await asyncio.sleep(self.min_delay)
                return

            # Calculate required delay
            delay = self._calculate_delay(bucket, points_cost)

            if delay > 0:
                bucket_key = self._get_bucket_key(is_user_request)
                if delay > 1:
                    logger.log_event(
                        "rate_limit",
                        "waiting",
                        level=logging.WARNING,
                        bucket=bucket_key,
                        delay_seconds=round(delay, 1),
                        remaining=bucket.remaining,
                        endpoint=endpoint,
                    )
                else:
                    logger.log_event(
                        "rate_limit",
                        "brief_delay",
                        level=logging.DEBUG,
                        bucket=bucket_key,
                        delay_seconds=round(delay, 1),
                        endpoint=endpoint,
                    )

                await asyncio.sleep(delay)

            # Update bucket prediction (subtract points we're about to use)
            if bucket:
                bucket.remaining = max(0, bucket.remaining - points_cost)
                bucket.last_updated = time.time()

    def handle_429_error(
        self, headers: dict[str, str], is_user_request: bool = True
    ) -> None:
        """
        Handle a 429 Too Many Requests error by updating rate limit info

        Args:
            headers: Response headers from the 429 response
            is_user_request: True if request used user access token
        """
        bucket_key = self._get_bucket_key(is_user_request)

        # Debug: Show all headers in 429 response
        rate_headers = {
            k: v
            for k, v in headers.items()
            if "ratelimit" in k.lower() or k.lower() in ["retry-after"]
        }
        logger.log_event(
            "rate_limit",
            "429_headers",
            level=logging.ERROR,
            bucket=bucket_key,
            headers=str(rate_headers),
        )

        reset_header = headers.get("ratelimit-reset") or headers.get("Ratelimit-Reset")

        if reset_header:
            reset_time = float(reset_header)
            wait_time = max(0, reset_time - time.time())
            logger.log_event(
                "rate_limit",
                "429_reset_known",
                level=logging.ERROR,
                bucket=bucket_key,
                wait_seconds=round(wait_time, 1),
            )

            # Reset adaptive backoff if active
            if self._backoff.active_delay() > 0:
                self._backoff.reset()

            # Update bucket to reflect we're out of points
            if is_user_request:
                self.user_bucket = RateLimitInfo(
                    limit=DEFAULT_BUCKET_LIMIT,  # Default user limit
                    remaining=0,
                    reset_timestamp=reset_time,
                    last_updated=time.time(),
                    monotonic_last_updated=time.monotonic(),
                )
            else:
                self.app_bucket = RateLimitInfo(
                    limit=DEFAULT_BUCKET_LIMIT,  # Default app limit
                    remaining=0,
                    reset_timestamp=reset_time,
                    last_updated=time.time(),
                    monotonic_last_updated=time.monotonic(),
                )
        else:
            logger.log_event(
                "rate_limit",
                "429_reset_unknown",
                level=logging.ERROR,
                bucket=bucket_key,
            )
            self._backoff.increase()

    # --------------------------- Adaptive Backoff --------------------------- #
    # Backoff logic moved to AdaptiveBackoff


# Legacy global registry removed: rate limiters are now provided by ApplicationContext
