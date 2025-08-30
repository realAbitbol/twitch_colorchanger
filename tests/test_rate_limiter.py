import time
from unittest.mock import patch

import pytest

from src.rate_limiter import RateLimitInfo, TwitchRateLimiter


@pytest.fixture
def rate_limiter():
    return TwitchRateLimiter(client_id="test_client", username="test_user")


def test_init(rate_limiter):
    assert rate_limiter.client_id == "test_client"
    assert rate_limiter.username == "test_user"
    assert rate_limiter.app_bucket is None
    assert rate_limiter.user_bucket is None
    assert hasattr(rate_limiter, "_lock")
    assert rate_limiter.safety_buffer == 5
    import pytest
    assert rate_limiter.min_delay == pytest.approx(0.1)


def test_get_bucket_key(rate_limiter):
    assert rate_limiter._get_bucket_key(True) == "user:test_user"
    assert rate_limiter._get_bucket_key(False) == "app:test_client"


def test_update_from_headers_valid(rate_limiter):
    headers = {
        "Ratelimit-Limit": "800",
        "Ratelimit-Remaining": "799",
        "Ratelimit-Reset": str(int(time.time()) + 10)
    }
    rate_limiter.update_from_headers(headers, is_user_request=True)
    assert rate_limiter.user_bucket is not None
    assert rate_limiter.user_bucket.limit == 800
    assert rate_limiter.user_bucket.remaining == 799


def test_update_from_headers_invalid(rate_limiter):
    headers = {"Ratelimit-Limit": "not_an_int"}
    rate_limiter.update_from_headers(headers, is_user_request=True)
    # Should not raise, bucket remains None
    assert rate_limiter.user_bucket is None


def test_log_rate_limit_headers(rate_limiter, capsys):
    import os
    from unittest.mock import patch
    headers = {"Ratelimit-Limit": "800", "Other-Header": "value"}
    with patch.dict(os.environ, {"DEBUG": "true"}):
        rate_limiter._log_rate_limit_headers(headers, True)
        out = capsys.readouterr().out
        assert "API Headers" in out or "No rate limit headers" in out


def test_parse_rate_limit_headers(rate_limiter):
    headers = {
        "Ratelimit-Limit": "800",
        "Ratelimit-Remaining": "799",
        "Ratelimit-Reset": str(int(time.time()) + 10)
    }
    info = rate_limiter._parse_rate_limit_headers(headers)
    assert isinstance(info, RateLimitInfo)
    assert info.limit == 800
    assert info.remaining == 799
    assert info.reset_timestamp > time.time()


def test_parse_rate_limit_headers_missing(rate_limiter):
    headers = {}
    info = rate_limiter._parse_rate_limit_headers(headers)
    assert info is None


def test_update_rate_limit_bucket(rate_limiter):
    now = time.time()
    info = RateLimitInfo(
        limit=800,
        remaining=799,
        reset_timestamp=now + 10,
        last_updated=now)
    rate_limiter._update_rate_limit_bucket(info, True)
    assert rate_limiter.user_bucket == info
    rate_limiter._update_rate_limit_bucket(info, False)
    assert rate_limiter.app_bucket == info


def test_log_rate_limit_update(rate_limiter, capsys):
    import os
    from unittest.mock import patch
    now = time.time()
    info = RateLimitInfo(
        limit=800,
        remaining=799,
        reset_timestamp=now + 10,
        last_updated=now)
    with patch.dict(os.environ, {"DEBUG": "true"}):
        rate_limiter._log_rate_limit_update(info, True)
        out = capsys.readouterr().out
        assert "Rate limit updated" in out


def test_get_delay(rate_limiter):
    now = time.time()
    info = RateLimitInfo(
        limit=800,
        remaining=799,
        reset_timestamp=now + 10,
        last_updated=now)
    rate_limiter.user_bucket = info
    delay = rate_limiter.get_delay(is_user_request=True)
    assert delay >= 0.1
    rate_limiter.user_bucket.remaining = 0
    delay = rate_limiter.get_delay(is_user_request=True)
    assert delay > 0.1


def test_get_delay_no_bucket(rate_limiter):
    rate_limiter.user_bucket = None
    delay = rate_limiter.get_delay(is_user_request=True)
    import pytest
    assert delay == pytest.approx(0.1)


def test_is_rate_limited(rate_limiter):
    now = time.time()
    info = RateLimitInfo(
        limit=800,
        remaining=0,
        reset_timestamp=now + 10,
        last_updated=now)
    rate_limiter.user_bucket = info
    assert rate_limiter.is_rate_limited(is_user_request=True)
    info.remaining = 10
    rate_limiter.user_bucket = info
    assert not rate_limiter.is_rate_limited(is_user_request=True)


def test_get_rate_limit_display(rate_limiter):
    now = time.time()
    info = RateLimitInfo(
        limit=800,
        remaining=799,
        reset_timestamp=now + 10,
        last_updated=now)
    rate_limiter.user_bucket = info
    display = rate_limiter.get_rate_limit_display(is_user_request=True)
    assert "Rate limit" in display
    rate_limiter.user_bucket = None
    display = rate_limiter.get_rate_limit_display(is_user_request=True)
    assert "No rate limit bucket" in display


# Tests for missing functionality

def test_is_rate_limited_no_bucket(rate_limiter):
    """Test is_rate_limited when bucket is None (covers line 35)"""
    assert rate_limiter.is_rate_limited(is_user_request=True) is False
    assert rate_limiter.is_rate_limited(is_user_request=False) is False


def test_update_from_headers_exception_handling(rate_limiter):
    """Test exception handling in update_from_headers (covers lines 92-94)"""
    headers = {
        "Ratelimit-Limit": "invalid_value",  # Will cause ValueError
        "Ratelimit-Remaining": "also_invalid",
        "Ratelimit-Reset": "not_a_number"
    }

    with patch('src.rate_limiter.print_log') as mock_log:
        rate_limiter.update_from_headers(headers, is_user_request=True)
        # Should log twice: once for headers, once for exception
        assert mock_log.call_count == 2
        calls = mock_log.call_args_list
        assert any("Failed to parse rate limit headers" in str(call) for call in calls)


def test_log_rate_limit_headers_no_rate_headers(rate_limiter):
    """Test _log_rate_limit_headers when no rate limit headers present (covers line 103)"""
    headers = {"Content-Type": "application/json", "Other-Header": "value"}

    with patch('src.rate_limiter.print_log') as mock_log:
        rate_limiter._log_rate_limit_headers(headers, is_user_request=True)
        mock_log.assert_called_once()
        assert "No rate limit headers found" in str(mock_log.call_args)


def test_parse_rate_limit_headers_all_missing(rate_limiter):
    """Test _parse_rate_limit_headers with all headers missing (covers lines 154-155)"""
    headers = {}
    result = rate_limiter._parse_rate_limit_headers(headers)
    assert result is None


def test_parse_rate_limit_headers_partial_missing(rate_limiter):
    """Test _parse_rate_limit_headers with some headers missing"""
    headers = {"Ratelimit-Limit": "800"}  # Missing remaining and reset
    result = rate_limiter._parse_rate_limit_headers(headers)
    assert result is None


def test_calculate_delay_no_points_available(rate_limiter):
    """Test _calculate_delay when no points available (covers lines 172-181)"""
    now = time.time()
    bucket = RateLimitInfo(
        limit=800,
        remaining=5,  # Less than safety_buffer (5)
        reset_timestamp=now + 10,
        last_updated=now
    )

    delay = rate_limiter._calculate_delay(bucket, points_needed=1)
    # Should return time until reset since no points available
    assert delay == pytest.approx(10, abs=0.1)


def test_calculate_delay_with_available_points(rate_limiter):
    """Test _calculate_delay with available points (covers lines 172-181)"""
    now = time.time()
    bucket = RateLimitInfo(
        limit=800,
        remaining=0,  # No points remaining, should wait until reset
        reset_timestamp=now + 10,
        last_updated=now
    )

    delay = rate_limiter._calculate_delay(bucket, points_needed=1)
    # remaining (0) < points_needed (1), so wait until reset
    # Should return reset_delay + 0.1 buffer = 10 + 0.1
    assert delay == pytest.approx(10.1, abs=0.1)


@pytest.mark.asyncio
async def test_wait_if_needed_no_bucket(rate_limiter):
    """Test wait_if_needed when no bucket available (covers lines 192-225)"""
    with patch('src.rate_limiter.print_log') as mock_log, \
            patch('asyncio.sleep') as mock_sleep:

        await rate_limiter.wait_if_needed("test_endpoint", is_user_request=True)

        mock_log.assert_called_once()
        assert "No rate limit info yet" in str(mock_log.call_args)
        mock_sleep.assert_called_once_with(0.1)  # min_delay


@pytest.mark.asyncio
async def test_wait_if_needed_with_delay(rate_limiter):
    """Test wait_if_needed when delay is required (covers lines 192-225)"""
    now = time.time()
    bucket = RateLimitInfo(
        limit=800,
        remaining=5,  # Will require delay
        reset_timestamp=now + 10,
        last_updated=now
    )
    rate_limiter.user_bucket = bucket

    with patch('src.rate_limiter.print_log') as mock_log, \
            patch('asyncio.sleep') as mock_sleep:

        await rate_limiter.wait_if_needed("test_endpoint", is_user_request=True, points_cost=1)

        # Should log the delay and sleep
        mock_log.assert_called()
        mock_sleep.assert_called_once()
        # Should update bucket remaining
        assert rate_limiter.user_bucket.remaining == 4  # 5 - 1 point cost


@pytest.mark.asyncio
async def test_wait_if_needed_brief_delay(rate_limiter):
    """Test wait_if_needed with brief delay (covers debug logging branch)"""
    # Mock _calculate_delay to return a brief delay (< 1s) to trigger debug logging
    with patch.object(rate_limiter, '_calculate_delay', return_value=0.5), \
            patch('src.rate_limiter.print_log') as mock_log, \
            patch('asyncio.sleep'):

        # Need a bucket to exist for the calculation
        rate_limiter.user_bucket = RateLimitInfo(
            800, 100, time.time() + 60, time.time())

        await rate_limiter.wait_if_needed("test_endpoint", is_user_request=True, points_cost=1)

        # Should use debug logging for brief delays (< 1s)
        mock_log.assert_called()
        calls = [str(call) for call in mock_log.call_args_list]
        assert any("Brief delay" in call for call in calls)


def test_handle_429_error(rate_limiter):
    """Test handle_429_error functionality (covers lines 235-267)"""
    headers = {
        "Ratelimit-Limit": "800",
        "Ratelimit-Remaining": "0",  # Exhausted
        "Ratelimit-Reset": str(int(time.time()) + 60)
    }

    with patch('src.rate_limiter.print_log') as mock_log:
        rate_limiter.handle_429_error(headers, is_user_request=True)

        # Should update bucket and log
        assert rate_limiter.user_bucket is not None
        assert rate_limiter.user_bucket.remaining == 0
        mock_log.assert_called()
        assert "Rate limit exceeded (429)" in str(mock_log.call_args)


def test_handle_429_error_no_headers(rate_limiter):
    """Test handle_429_error with missing headers"""
    headers = {}

    with patch('src.rate_limiter.print_log') as mock_log:
        rate_limiter.handle_429_error(headers, is_user_request=True)

        # Should still log the 429 error even without headers
        mock_log.assert_called()


def test_app_bucket_functionality(rate_limiter):
    """Test app bucket vs user bucket functionality"""
    # Test app bucket selection
    app_delay = rate_limiter.get_delay(is_user_request=False, points_needed=1)
    assert isinstance(app_delay, float)

    # Test app bucket rate limiting
    app_limited = rate_limiter.is_rate_limited(is_user_request=False, points_needed=1)
    assert isinstance(app_limited, bool)


def test_stale_bucket_info():
    """Test _calculate_delay with stale bucket info (covers lines 154-155)"""
    rate_limiter = TwitchRateLimiter("test_client", "test_user")

    # Create a bucket with stale last_updated (> 60 seconds ago)
    old_time = time.time() - 70  # 70 seconds ago
    bucket = RateLimitInfo(
        limit=800,
        remaining=100,
        reset_timestamp=time.time() + 60,
        last_updated=old_time
    )

    with patch('src.rate_limiter.print_log') as mock_log:
        delay = rate_limiter._calculate_delay(bucket, points_needed=1)

        # Should return 1.0 for stale info
        assert delay == pytest.approx(1.0)
        mock_log.assert_called_once()
        assert "stale" in str(mock_log.call_args)


def test_proportional_delay_calculation():
    """Test proportional delay calculation (covers lines 177-178)"""
    rate_limiter = TwitchRateLimiter("test_client", "test_user")
    rate_limiter.safety_buffer = 1

    now = time.time()
    bucket = RateLimitInfo(
        limit=800,
        remaining=2,
        reset_timestamp=now + 10,
        last_updated=now
    )

    # This should hit the proportional delay calculation path
    # remaining (2) >= points_needed (2)? Yes
    # points_available = remaining (2) - safety_buffer (1) = 1 > 0
    # optimal_delay = time_until_reset / points_available = 10 / 1 = 10
    delay = rate_limiter._calculate_delay(bucket, points_needed=2)
    assert delay == pytest.approx(10, abs=0.1)


def test_handle_429_error_app_bucket():
    """Test handle_429_error with app bucket (covers line 260)"""
    rate_limiter = TwitchRateLimiter("test_client", "test_user")
    headers = {
        "Ratelimit-Reset": str(int(time.time() + 60))
    }

    with patch('src.rate_limiter.print_log') as mock_log:
        rate_limiter.handle_429_error(headers, is_user_request=False)

        # Should create app bucket and log
        assert rate_limiter.app_bucket is not None
        assert rate_limiter.app_bucket.remaining == 0
        mock_log.assert_called()


def test_get_rate_limiter_function():
    """Test get_rate_limiter global function (covers lines 285-290)"""
    # Clear any existing limiters
    import src.rate_limiter
    from src.rate_limiter import get_rate_limiter
    src.rate_limiter._rate_limiters.clear()

    # Test creating new limiter
    limiter1 = get_rate_limiter("client1", "user1")
    assert isinstance(limiter1, TwitchRateLimiter)
    assert limiter1.client_id == "client1"
    assert limiter1.username == "user1"

    # Test getting existing limiter (should return same instance)
    limiter2 = get_rate_limiter("client1", "user1")
    assert limiter1 is limiter2

    # Test app-only limiter (no username)
    app_limiter = get_rate_limiter("client1", None)
    assert isinstance(app_limiter, TwitchRateLimiter)
    assert app_limiter.client_id == "client1"
    assert app_limiter.username is None

    # Should be different from user limiter
    assert app_limiter is not limiter1


# Branch Coverage Tests - targeting specific uncovered branches
class TestRateLimiterBranchCoverage:
    """Test missing branch coverage in rate_limiter.py"""

    @pytest.mark.asyncio
    async def test_wait_if_needed_brief_delay_no_log_branch(self):
        """Test branch when delay < 1 second - lines 236->254"""
        limiter = TwitchRateLimiter('client123', username='testuser')
        
        # Set up rate limit bucket with very small delay
        limiter.user_bucket = RateLimitInfo(
            limit=100,
            remaining=99,
            reset_timestamp=time.time() + 0.1,  # Very small delay
            last_updated=time.time()
        )
        
        with patch('asyncio.sleep'), \
             patch('src.rate_limiter.print_log') as mock_log:
            
            # This should create a very small delay (< 1 second)
            await limiter.wait_if_needed(endpoint='test', is_user_request=True, points_cost=1)
            
            # Should not log for brief delays since delay < 1 second
            mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_if_needed_no_bucket_early_exit(self):
        """Test early exit when no bucket exists - lines 223->224"""
        limiter = TwitchRateLimiter('client123', username='testuser')
        
        # Ensure no bucket exists
        limiter.user_bucket = None
        limiter.app_bucket = None
        
        with patch('asyncio.sleep'):
            # This should exit early since no bucket exists
            await limiter.wait_if_needed(endpoint='test', is_user_request=True, points_cost=1)
            
            # Should not raise any exception, just return early
            assert limiter.user_bucket is None

    @pytest.mark.asyncio 
    async def test_wait_if_needed_no_bucket_prediction_update(self):
        """Test branch when bucket is None in prediction update - line 254->exit"""
        limiter = TwitchRateLimiter('client123', username='testuser')
        
        # Set up rate limiter with no bucket for user requests
        limiter.user_bucket = None
        
        with patch('time.time', return_value=1000.0):
            # Should not crash and should handle missing bucket gracefully
            await limiter.wait_if_needed(endpoint='test', is_user_request=True, points_cost=1)
            
        # Test with app bucket as None too
        limiter.app_bucket = None
        await limiter.wait_if_needed(endpoint='test', is_user_request=False, points_cost=1)

    @pytest.mark.asyncio
    async def test_wait_if_needed_bucket_none_line_254(self):
        """Test rate_limiter.py line 254: if bucket -> False when bucket is None"""
        limiter = TwitchRateLimiter("test_client")
        limiter.user_bucket = None  # Make bucket None/False
        
        # This should hit line 254 and take the False branch
        await limiter.wait_if_needed(endpoint="test", is_user_request=True, points_cost=1)

    @pytest.mark.asyncio
    async def test_wait_if_needed_falsy_bucket_object_line_254(self):
        """Provide a bucket object that evaluates False to hit 'if bucket:' false branch at line 254."""
        limiter = TwitchRateLimiter("client_id", username="user")

        class FalsyBucket:
            limit = 100
            remaining = 40
            reset_timestamp = time.time() + 5
            last_updated = time.time()
            def __bool__(self):
                return False

        fb = FalsyBucket()
        limiter.user_bucket = fb

        with patch.object(limiter, "_calculate_delay", return_value=0), \
             patch("src.rate_limiter.print_log"):
            await limiter.wait_if_needed(endpoint="ep", is_user_request=True, points_cost=5)

        # Because bucket evaluated False, prediction update block skipped
        assert fb.remaining == 40
