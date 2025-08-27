"""
Advanced rate limiter that uses Twitch Helix API rate limiting headers
"""

import asyncio
import time
from typing import Dict, Optional
from dataclasses import dataclass

from .utils import print_log
from .colors import bcolors


@dataclass
class RateLimitInfo:
    """Rate limit information from Twitch API headers"""
    limit: int  # Rate at which points are added to bucket
    remaining: int  # Number of points remaining in bucket
    reset_timestamp: float  # Unix timestamp when bucket resets to full
    last_updated: float  # When this info was last updated


class TwitchRateLimiter:
    """
    Advanced rate limiter that uses Twitch Helix API rate limiting headers
    to dynamically adjust delays and prevent 429 errors
    """
    
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
        
    def _get_bucket_key(self, is_user_request: bool) -> str:
        """Get the bucket identifier for logging"""
        if is_user_request and self.username:
            return f"user:{self.username}"
        return f"app:{self.client_id}"
    
    def update_from_headers(self, headers: Dict[str, str], is_user_request: bool = True):
        """
        Update rate limit info from API response headers

        Args:
            headers: Response headers from Twitch API
            is_user_request: True if request used user access token, False for app token
        """
        try:
            # Debug: Show all headers that might contain rate limit info (debug mode only)
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
            print_log(f"⚠️ {bucket_key}: Failed to parse rate limit headers: {e}", bcolors.WARNING, debug_only=True)

    def _log_rate_limit_headers(self, headers: Dict[str, str], is_user_request: bool) -> None:
        """Log rate limit headers for debugging"""
        bucket_key = self._get_bucket_key(is_user_request)
        rate_headers = {k: v for k, v in headers.items() if 'ratelimit' in k.lower()}
        if rate_headers:
            print_log(f"🔍 {bucket_key}: API Headers: {rate_headers}", bcolors.OKBLUE, debug_only=True)
        else:
            print_log(f"⚠️ {bucket_key}: No rate limit headers found in response", bcolors.WARNING, debug_only=True)

    def _parse_rate_limit_headers(self, headers: Dict[str, str]) -> Optional[RateLimitInfo]:
        """Parse rate limit headers into RateLimitInfo object"""
        # Extract rate limit headers (case-insensitive)
        limit = headers.get('ratelimit-limit') or headers.get('Ratelimit-Limit')
        remaining = headers.get('ratelimit-remaining') or headers.get('Ratelimit-Remaining')
        reset = headers.get('ratelimit-reset') or headers.get('Ratelimit-Reset')

        if limit and remaining and reset:
            return RateLimitInfo(
                limit=int(limit),
                remaining=int(remaining),
                reset_timestamp=float(reset),
                last_updated=time.time()
            )
        return None

    def _update_rate_limit_bucket(self, rate_info: RateLimitInfo, is_user_request: bool) -> None:
        """Update the appropriate rate limit bucket"""
        if is_user_request:
            self.user_bucket = rate_info
        else:
            self.app_bucket = rate_info

    def _log_rate_limit_update(self, rate_info: RateLimitInfo, is_user_request: bool) -> None:
        """Log successful rate limit update"""
        bucket_key = self._get_bucket_key(is_user_request)
        reset_in = max(0, rate_info.reset_timestamp - time.time())
        print_log(
            f"🔄 {bucket_key}: Rate limit updated - {rate_info.remaining}/{rate_info.limit} points remaining "
            f"(resets in {reset_in:.0f}s)",
            bcolors.OKBLUE,
            debug_only=True
        )
    
    def _calculate_delay(self, bucket: RateLimitInfo, points_needed: int = 1) -> float:
        """
        Calculate optimal delay before next request
        
        Args:
            bucket: Current rate limit info
            points_needed: Points required for the next request
            
        Returns:
            Delay in seconds (0 if no delay needed)
        """
        current_time = time.time()
        
        # If bucket info is stale (older than 60 seconds), be conservative
        if current_time - bucket.last_updated > 60:
            print_log("⚠️ Rate limit info is stale, using conservative delay", bcolors.WARNING, debug_only=True)
            return 1.0
        
        # If we have enough points (including safety buffer), no delay needed
        if bucket.remaining >= points_needed + self.safety_buffer:
            return 0
        
        # If we're completely out of points, wait until reset
        if bucket.remaining < points_needed:
            reset_delay = max(0, bucket.reset_timestamp - current_time)
            print_log(
                f"⏰ Rate limit exceeded, waiting {reset_delay:.1f}s until reset", 
                bcolors.WARNING
            )
            return reset_delay + 0.1  # Add small buffer
        
        # If we're running low but not empty, calculate proportional delay
        # This spreads remaining requests over remaining time
        time_until_reset = max(1, bucket.reset_timestamp - current_time)
        points_available = bucket.remaining - self.safety_buffer
        
        if points_available > 0:
            # Calculate delay to spread remaining points over remaining time
            optimal_delay = time_until_reset / points_available
            return max(self.min_delay, optimal_delay)
        
        # Fallback: wait until reset
        return max(0, bucket.reset_timestamp - current_time)
    
    async def wait_if_needed(self, endpoint: str = "default", is_user_request: bool = True, points_cost: int = 1):
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
                print_log(f"🔄 No rate limit info yet, using minimal delay for {endpoint}", bcolors.OKBLUE, debug_only=True)
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
                        bcolors.WARNING
                    )
                else:
                    print_log(
                        f"⏳ {bucket_key}: Brief delay {delay:.1f}s for {endpoint}", 
                        bcolors.OKBLUE, 
                        debug_only=True
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
        rate_headers = {k: v for k, v in headers.items() if 'ratelimit' in k.lower() or k.lower() in ['retry-after']}
        print_log(f"🔍 {bucket_key}: 429 Error Headers: {rate_headers}", bcolors.FAIL, debug_only=True)
        
        reset_header = headers.get('ratelimit-reset') or headers.get('Ratelimit-Reset')
        
        if reset_header:
            reset_time = float(reset_header)
            wait_time = max(0, reset_time - time.time())
            print_log(
                f"❌ {bucket_key}: Rate limit exceeded (429), will reset in {wait_time:.1f}s", 
                bcolors.FAIL
            )
            
            # Update bucket to reflect we're out of points
            if is_user_request:
                self.user_bucket = RateLimitInfo(
                    limit=800,  # Default user limit
                    remaining=0,
                    reset_timestamp=reset_time,
                    last_updated=time.time()
                )
            else:
                self.app_bucket = RateLimitInfo(
                    limit=800,  # Default app limit  
                    remaining=0,
                    reset_timestamp=reset_time,
                    last_updated=time.time()
                )
        else:
            print_log(f"❌ {bucket_key}: Rate limit exceeded (429), no reset time provided", bcolors.FAIL)


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
