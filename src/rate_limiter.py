"""
Advanced rate limiter that uses Twitch Helix API rate limiting headers
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional

from .colors import BColors
from .utils import print_log


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

    def __init__(self, client_id: str, username: str = None):
        self.client_id = client_id
        self.username = username

        # Separate buckets for app access and user access requests
        self.app_bucket: Optional[RateLimitInfo] = None
        self.user_bucket: Optional[RateLimitInfo] = None

        # Lock to prevent race conditions
        self._lock = asyncio.Lock()

        # Safety margins
        self.safety_buffer = 5  # Keep 5 points as safety buffer
        self.min_delay = 0.1  # Minimum delay between requests (100ms)

        # Hysteresis parameters to avoid oscillation
        self.hysteresis_threshold = (
            10  # Extra buffer when switching to conservative mode
        )
        self.is_conservative_mode = False

    def get_delay(self, is_user_request: bool = True, points_needed: int = 1) -> float:
        """Return the optimal delay before the next request."""
        bucket = self.user_bucket if is_user_request else self.app_bucket
        if bucket is None:
            return self.min_delay
        return max(self.min_delay, self._calculate_delay(bucket, points_needed))

    def is_rate_limited(
        self, is_user_request: bool = True, points_needed: int = 1
    ) -> bool:
        """Return True if rate limited (not enough points for request)."""
        bucket = self.user_bucket if is_user_request else self.app_bucket
        if bucket is None:
            return False
        return bucket.remaining < points_needed + self.safety_buffer

    def get_rate_limit_display(self, is_user_request: bool = True) -> str:
        """Return a string describing the current rate limit status."""
        bucket = self.user_bucket if is_user_request else self.app_bucket
        if bucket is None:
            return "No rate limit bucket available."
        reset_in = max(0, bucket.reset_timestamp - time.time())
        return (
            f"Rate limit: {bucket.remaining}/{bucket.limit} points remaining. "
            f"Resets in {reset_in:.0f}s."
        )

    def _get_bucket_key(self, is_user_request: bool) -> str:
        """Get the bucket identifier for logging"""
        if is_user_request and self.username:
            return f"user:{self.username}"
        return f"app:{self.client_id}"

    def update_from_headers(
        self, headers: Dict[str, str], is_user_request: bool = True
    ):
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
            rate_info = self._parse_rate_limit_headers(headers)
            if rate_info:
                # Update appropriate bucket
                self._update_rate_limit_bucket(rate_info, is_user_request)
                # Log successful update
                self._log_rate_limit_update(rate_info, is_user_request)

        except (ValueError, TypeError) as e:
            bucket_key = self._get_bucket_key(is_user_request)
            print_log(
                f"⚠️ {bucket_key}: Failed to parse rate limit headers: {e}",
                BColors.WARNING,
                debug_only=True,
            )

    def _log_rate_limit_headers(
        self, headers: Dict[str, str], is_user_request: bool
    ) -> None:
        """Log rate limit headers for debugging"""
        bucket_key = self._get_bucket_key(is_user_request)
        rate_headers = {k: v for k, v in headers.items() if "ratelimit" in k.lower()}
        if rate_headers:
            print_log(
                f"🔍 {bucket_key}: API Headers: {rate_headers}",
                BColors.OKBLUE,
                debug_only=True,
            )
        else:
            print_log(
                f"⚠️ {bucket_key}: No rate limit headers found in response",
                BColors.WARNING,
                debug_only=True,
            )

    def _parse_rate_limit_headers(
        self, headers: Dict[str, str]
    ) -> Optional[RateLimitInfo]:
        """Parse rate limit headers into RateLimitInfo object"""
        # Extract rate limit headers (case-insensitive)
        limit = headers.get("ratelimit-limit") or headers.get("Ratelimit-Limit")
        remaining = headers.get("ratelimit-remaining") or headers.get(
            "Ratelimit-Remaining"
        )
        reset = headers.get("ratelimit-reset") or headers.get("Ratelimit-Reset")

        if limit and remaining and reset:
            return RateLimitInfo(
                limit=int(limit),
                remaining=int(remaining),
                reset_timestamp=float(reset),
                last_updated=time.time(),
                monotonic_last_updated=time.monotonic(),
            )
        return None

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
        print_log(
            f"🔄 {bucket_key}: Rate limit updated - "
            f"{rate_info.remaining}/{rate_info.limit} points remaining "
            f"(resets in {reset_in:.0f}s)",
            BColors.OKBLUE,
            debug_only=True,
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
        current_monotonic = time.monotonic()

        # Use monotonic time for elapsed calculations to avoid clock drift
        if hasattr(bucket, "monotonic_last_updated"):
            elapsed_monotonic = current_monotonic - bucket.monotonic_last_updated
            # Update reset timestamp based on monotonic elapsed time
            adjusted_reset = (
                bucket.reset_timestamp
                - (current_time - bucket.last_updated)
                + elapsed_monotonic
            )
        else:
            # Fallback for old bucket format
            adjusted_reset = bucket.reset_timestamp
            elapsed_monotonic = current_time - bucket.last_updated

        # If bucket info is stale (older than 60 seconds), be conservative
        if elapsed_monotonic > 60:
            print_log(
                "⚠️ Rate limit info is stale, using conservative delay",
                BColors.WARNING,
                debug_only=True,
            )
            return 1.0

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

        # If we have enough points (including safety buffer), no delay needed
        if bucket.remaining >= points_needed + effective_safety_buffer:
            return 0

        # If we're completely out of points, wait until reset
        if bucket.remaining < points_needed:
            reset_delay = max(0, adjusted_reset - current_time)
            print_log(
                f"⏰ Rate limit exceeded, waiting {reset_delay:.1f}s until reset",
                BColors.WARNING,
            )
            return reset_delay + 0.1  # Add small buffer

        # Speculative tracking: estimate points that will be available
        time_until_reset = max(1, adjusted_reset - current_time)
        points_available = bucket.remaining - effective_safety_buffer

        # Calculate regeneration rate (points per second)
        if time_until_reset > 0:
            regeneration_rate = bucket.limit / time_until_reset

            # Estimate when we'll have enough points
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
    ):
        """
        Wait if necessary to respect rate limits before making a request

        Args:
            endpoint: API endpoint being called (for logging/tracking)
            is_user_request: True if using user access token, False for app token
            points_cost: Points cost of this request (default 1)
        """
        async with self._lock:
            # Get appropriate bucket
            bucket = self.user_bucket if is_user_request else self.app_bucket

            # If we don't have rate limit info yet, use minimal delay
            if bucket is None:
                print_log(
                    f"🔄 No rate limit info yet, using minimal delay for {endpoint}",
                    BColors.OKBLUE,
                    debug_only=True,
                )
                await asyncio.sleep(self.min_delay)
                return

            # Calculate required delay
            delay = self._calculate_delay(bucket, points_cost)

            if delay > 0:
                bucket_key = self._get_bucket_key(is_user_request)
                if delay > 1:
                    print_log(
                        f"⏳ {bucket_key}: Waiting {delay:.1f}s before {endpoint} "
                        f"({bucket.remaining} points remaining)",
                        BColors.WARNING,
                    )
                else:
                    print_log(
                        f"⏳ {bucket_key}: Brief delay {delay:.1f}s for {endpoint}",
                        BColors.OKBLUE,
                        debug_only=True,
                    )

                await asyncio.sleep(delay)

            # Update bucket prediction (subtract points we're about to use)
            if bucket:
                bucket.remaining = max(0, bucket.remaining - points_cost)
                bucket.last_updated = time.time()

    def handle_429_error(self, headers: Dict[str, str], is_user_request: bool = True):
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
        print_log(
            f"🔍 {bucket_key}: 429 Error Headers: {rate_headers}",
            BColors.FAIL,
            debug_only=True,
        )

        reset_header = headers.get("ratelimit-reset") or headers.get("Ratelimit-Reset")

        if reset_header:
            reset_time = float(reset_header)
            wait_time = max(0, reset_time - time.time())
            print_log(
                f"❌ {bucket_key}: Rate limit exceeded (429), will reset in {
                    wait_time:.1f}s",
                BColors.FAIL,
            )

            # Update bucket to reflect we're out of points
            if is_user_request:
                self.user_bucket = RateLimitInfo(
                    limit=800,  # Default user limit
                    remaining=0,
                    reset_timestamp=reset_time,
                    last_updated=time.time(),
                    monotonic_last_updated=time.monotonic(),
                )
            else:
                self.app_bucket = RateLimitInfo(
                    limit=800,  # Default app limit
                    remaining=0,
                    reset_timestamp=reset_time,
                    last_updated=time.time(),
                    monotonic_last_updated=time.monotonic(),
                )
        else:
            print_log(
                f"❌ {bucket_key}: Rate limit exceeded (429), no reset time provided",
                BColors.FAIL,
            )


# Global rate limiter instances (one per client_id/username combination)
_rate_limiters: Dict[str, TwitchRateLimiter] = {}


def get_rate_limiter(client_id: str, username: str = None) -> TwitchRateLimiter:
    """
    Get or create a rate limiter for a specific client_id/username combination

    Args:
        client_id: Twitch application client ID
        username: Username for user-specific rate limiting (optional)

    Returns:
        TwitchRateLimiter instance
    """
    key = f"{client_id}:{username or 'app'}"

    if key not in _rate_limiters:
        _rate_limiters[key] = TwitchRateLimiter(client_id, username)

    return _rate_limiters[key]
