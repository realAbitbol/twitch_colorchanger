import math
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.color_changer import CHAT_COLOR_ENDPOINT, ColorChanger
from src.color.models import ColorRequestResult, ColorRequestStatus


class MockBot:
    """Mock bot for testing ColorChanger."""

    def __init__(self):
        self.username = "testuser"
        self.config_file = "test_config.json"
        self.user_id = "12345"
        self.api = MagicMock()
        self.access_token = "test_token"
        self.client_id = "test_client_id"
        self._color_service = None
        self.last_color = None
        self._last_color_change_payload = None
        self.use_random_colors = False

    def _build_user_config(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "is_prime_or_turbo": True,
            "config_file": self.config_file,
        }


# Cache behavior tests
@pytest.mark.asyncio
async def test_init_color_cache():
    """Test color cache initialization."""
    bot = MockBot()
    changer = ColorChanger(bot)
    assert hasattr(changer, "_cache_lock")
    assert hasattr(changer, "_current_color_cache")
    assert math.isclose(changer._cache_ttl, 30.0)
    assert isinstance(changer._current_color_cache, dict)


@pytest.mark.asyncio
async def test_current_color_cache_hit():
    """Test cache hit for current color fetch."""
    bot = MockBot()
    changer = ColorChanger(bot)
    bot.user_id = "test_user"
    changer._current_color_cache["test_user"] = {
        "color": "red",
        "timestamp": time.time(),
    }

    with patch.object(changer, "_make_color_request", new_callable=AsyncMock) as mock_request:
        result = await changer._get_current_color_impl()
        assert result == "red"
        mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_current_color_cache_miss():
    """Test cache miss for current color fetch."""
    bot = MockBot()
    changer = ColorChanger(bot)
    changer.user_id = "test_user"

    with patch.object(changer, "_make_color_request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = ({"data": [{"color": "blue"}]}, 200)
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = "blue"
            result = await changer._get_current_color_impl()
            assert result == "blue"
            mock_retry.assert_called_once()


# Retry logic tests
@pytest.mark.asyncio
async def test_user_info_retry_on_429():
    """Test retry logic on 429 for user info."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch.object(changer, "_make_user_info_request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = [
            (None, 429),
            ({"data": [{"id": "123"}]}, 200),
        ]
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = {"id": "123"}
            result = await changer._get_user_info_impl()
            assert result == {"id": "123"}
            mock_retry.assert_called_once()


@pytest.mark.asyncio
async def test_user_info_retry_on_500():
    """Test retry logic on 500 for user info."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch.object(changer, "_make_user_info_request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = [
            (None, 500),
            ({"data": [{"id": "123"}]}, 200),
        ]
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = {"id": "123"}
            result = await changer._get_user_info_impl()
            assert result == {"id": "123"}
            mock_retry.assert_called_once()


@pytest.mark.asyncio
async def test_current_color_retry_on_429():
    """Test retry logic on 429 for current color."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch.object(changer, "_make_color_request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = [
            (None, 429),
            ({"data": [{"color": "red"}]}, 200),
        ]
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = "red"
            result = await changer._get_current_color_impl()
            assert result == "red"
            mock_retry.assert_called_once()


@pytest.mark.asyncio
async def test_current_color_retry_on_500():
    """Test retry logic on 500 for current color."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch.object(changer, "_make_color_request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = [
            (None, 500),
            ({"data": [{"color": "blue"}]}, 200),
        ]
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = "blue"
            result = await changer._get_current_color_impl()
            assert result == "blue"
            mock_retry.assert_called_once()


@pytest.mark.asyncio
async def test_color_request_retry_on_429():
    """Test retry logic on 429 for color request."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch.object(changer, "api") as mock_api:
        mock_api.request.side_effect = [
            ({}, 429, {}),
            ({}, 204, {}),
        ]
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204)
            result = await changer._perform_color_request({"color": "green"}, action="test")
            assert result.status == ColorRequestStatus.SUCCESS
            mock_retry.assert_called_once()


# Error response handling tests
@pytest.mark.asyncio
async def test_handle_color_response_success():
    """Test handling of successful color change responses."""
    bot = MockBot()
    changer = ColorChanger(bot)

    result = changer._handle_color_response(204, 1)
    assert result.status == ColorRequestStatus.SUCCESS
    assert result.http_status == 204

    result = changer._handle_color_response(200, 1)
    assert result.status == ColorRequestStatus.SUCCESS
    assert result.http_status == 200


@pytest.mark.asyncio
async def test_handle_color_response_unauthorized():
    """Test handling of unauthorized color change responses."""
    bot = MockBot()
    changer = ColorChanger(bot)

    result = changer._handle_color_response(401, 1)
    assert result.status == ColorRequestStatus.UNAUTHORIZED
    assert result.http_status == 401


@pytest.mark.asyncio
async def test_handle_color_response_rate_limit():
    """Test handling of rate limit color change responses."""
    bot = MockBot()
    changer = ColorChanger(bot)

    # Should retry on first attempt
    result = changer._handle_color_response(429, 1)
    assert result is None

    # Should fail after max attempts
    result = changer._handle_color_response(429, 6)
    assert result.status == ColorRequestStatus.RATE_LIMIT
    assert result.http_status == 429


@pytest.mark.asyncio
async def test_handle_color_response_server_error():
    """Test handling of server error color change responses."""
    bot = MockBot()
    changer = ColorChanger(bot)

    # Should retry on first attempt
    result = changer._handle_color_response(500, 1)
    assert result is None

    # Should fail after max attempts
    result = changer._handle_color_response(500, 6)
    assert result.status == ColorRequestStatus.HTTP_ERROR
    assert result.http_status == 500


@pytest.mark.asyncio
async def test_handle_color_response_unknown_error():
    """Test handling of unknown error color change responses."""
    bot = MockBot()
    changer = ColorChanger(bot)

    result = changer._handle_color_response(418, 1)  # I'm a teapot
    assert result.status == ColorRequestStatus.HTTP_ERROR
    assert result.http_status == 418


# Response parsing failures tests
@pytest.mark.asyncio
async def test_process_user_info_response_invalid_data():
    """Test processing invalid user info response data."""
    bot = MockBot()
    changer = ColorChanger(bot)

    # Invalid data structure
    result = changer._process_user_info_response(None, 200, 1)
    assert result is None

    result = changer._process_user_info_response({}, 200, 1)
    assert result is None

    result = changer._process_user_info_response({"data": []}, 200, 1)
    assert result is None


@pytest.mark.asyncio
async def test_process_user_info_response_missing_id():
    """Test processing user info response with missing id."""
    bot = MockBot()
    changer = ColorChanger(bot)

    result = changer._process_user_info_response({"data": [{}]}, 200, 1)
    assert result == {}

    result = changer._process_user_info_response({"data": [{"name": "test"}]}, 200, 1)
    assert result == {"name": "test"}


@pytest.mark.asyncio
async def test_process_color_response_invalid_data():
    """Test processing invalid color response data."""
    bot = MockBot()
    changer = ColorChanger(bot)

    # Invalid data structure
    result = changer._process_color_response(None, 200, 1)
    assert result is None

    result = changer._process_color_response({}, 200, 1)
    assert result is None

    result = changer._process_color_response({"data": []}, 200, 1)
    assert result is None


@pytest.mark.asyncio
async def test_process_color_response_missing_color():
    """Test processing color response with missing color field."""
    bot = MockBot()
    changer = ColorChanger(bot)

    result = changer._process_color_response({"data": [{}]}, 200, 1)
    assert result is None

    result = changer._process_color_response({"data": [{"name": "test"}]}, 200, 1)
    assert result is None


@pytest.mark.asyncio
async def test_extract_color_error_snippet():
    """Test extraction of error snippets from color change responses."""
    bot = MockBot()
    changer = ColorChanger(bot)

    # No payload
    result = changer._extract_color_error_snippet()
    assert result is None

    # Payload with message
    changer._last_color_change_payload = {"message": "Test error"}
    result = changer._extract_color_error_snippet()
    assert result == "Test error"

    # Payload with error
    changer._last_color_change_payload = {"error": "Another error"}
    result = changer._extract_color_error_snippet()
    assert result == "Another error"

    # Payload with neither
    changer._last_color_change_payload = {"status": "failed"}
    result = changer._extract_color_error_snippet()
    assert result == "{'status': 'failed'}"

    # Long message truncation
    long_message = "x" * 300
    changer._last_color_change_payload = {"message": long_message}
    result = changer._extract_color_error_snippet()
    assert len(result) == 200


# Persistent prime detection tests
@pytest.mark.asyncio
async def test_on_persistent_prime_detection_no_config():
    """Test persistent prime detection with no config file."""
    bot = MockBot()
    changer = ColorChanger(bot)
    changer.config_file = None

    # Should not raise or do anything
    await changer.on_persistent_prime_detection()
    # No assertions needed, just ensure no exceptions


@pytest.mark.asyncio
async def test_on_persistent_prime_detection_success():
    """Test successful persistent prime detection."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch("src.bot.color_changer.queue_user_update", new_callable=AsyncMock) as mock_queue:
        await changer.on_persistent_prime_detection()
        mock_queue.assert_called_once()
        args = mock_queue.call_args[0]
        assert args[0]["is_prime_or_turbo"] is False


@pytest.mark.asyncio
async def test_on_persistent_prime_detection_error():
    """Test persistent prime detection with persistence error."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch("src.bot.color_changer.queue_user_update", side_effect=OSError("Disk full")):
        # Should not raise, just log warning
        await changer.on_persistent_prime_detection()


@pytest.mark.asyncio
async def test_prime_color_state_with_color():
    """Test initializing last_color with current color."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch.object(changer, "_get_current_color", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = "purple"
        await changer._prime_color_state()
        assert changer.last_color == "purple"


@pytest.mark.asyncio
async def test_prime_color_state_no_color():
    """Test initializing last_color when no color is returned."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch.object(changer, "_get_current_color", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        await changer._prime_color_state()
        assert changer.last_color is None


@pytest.mark.asyncio
async def test_perform_color_request_cache_hit():
    """Test that successful color request updates cache for subsequent get_current_color."""
    bot = MockBot()
    changer = ColorChanger(bot)
    bot.user_id = "test_user"

    with patch.object(changer, "api") as mock_api:
        mock_api.request.return_value = ({}, 204, {})
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204)
            result = await changer._perform_color_request({"color": "blue"}, action="test")
            assert result.status == ColorRequestStatus.SUCCESS
            # Cache should be updated
            assert changer._current_color_cache["test_user"]["color"] == "blue"

    # Now get_current_color should hit cache
    with patch.object(changer, "_make_color_request", new_callable=AsyncMock) as mock_request:
        color = await changer._get_current_color_impl()
        assert color == "blue"
        mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_perform_color_request_rate_limit():
    """Test rate limit handling in color request."""
    bot = MockBot()
    changer = ColorChanger(bot)

    with patch.object(changer, "api") as mock_api:
        # First call returns 429, should retry
        mock_api.request.side_effect = [
            ({}, 429, {}),
            ({}, 204, {}),
        ]
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204)
            result = await changer._perform_color_request({"color": "red"}, action="test")
            assert result.status == ColorRequestStatus.SUCCESS


@pytest.mark.asyncio
async def test_get_current_color_cache_miss():
    """Test cache miss when cache entry is stale."""
    bot = MockBot()
    changer = ColorChanger(bot)
    bot.user_id = "test_user"
    # Set stale cache (old timestamp)
    changer._current_color_cache["test_user"] = {
        "color": "old_color",
        "timestamp": time.time() - changer._cache_ttl - 1,  # Stale
    }

    with patch.object(changer, "_make_color_request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = ({"data": [{"color": "new_color"}]}, 200)
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = "new_color"
            result = await changer._get_current_color_impl()
            assert result == "new_color"
            mock_retry.assert_called_once()


@pytest.mark.asyncio
async def test_change_color_no_color_service():
    """Test _change_color when color service is not initialized."""
    bot = MockBot()
    changer = ColorChanger(bot)
    bot._color_service = None  # Ensure it's None

    with patch("src.color.ColorChangeService") as mock_service_class, \
         patch.object(changer, "api") as mock_api:
        mock_api.request = AsyncMock(return_value=({}, 204, {}))
        mock_service = MagicMock()
        mock_service.change_color = AsyncMock(return_value=True)
        mock_service_class.return_value = mock_service

        result = await changer._change_color("green")
        assert result is True
        mock_service_class.assert_called_once_with(changer)
        mock_service.change_color.assert_called_once_with("green")

@pytest.mark.asyncio
async def test_ensure_user_id_success():
    """Test _ensure_user_id when user_id is successfully retrieved."""
    bot = MockBot()
    changer = ColorChanger(bot)
    bot.user_id = None
    with patch.object(changer, "_get_user_info", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"id": "12345"}
        result = await changer._ensure_user_id()
        assert result is True
        assert changer.user_id == "12345"


@pytest.mark.asyncio
async def test_ensure_user_id_failure():
    """Test _ensure_user_id when retrieval fails."""
    bot = MockBot()
    changer = ColorChanger(bot)
    bot.user_id = None
    with patch.object(changer, "_get_user_info", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        result = await changer._ensure_user_id()
        assert result is False
        assert changer.user_id is None


@pytest.mark.asyncio
async def test_get_user_info_direct():
    """Test _get_user_info calls _get_user_info_impl."""
    bot = MockBot()
    changer = ColorChanger(bot)
    with patch.object(changer, "_get_user_info_impl", new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = {"id": "123"}
        result = await changer._get_user_info()
        assert result == {"id": "123"}
        mock_impl.assert_called_once()


@pytest.mark.asyncio
async def test_make_user_info_request():
    """Test _make_user_info_request makes correct API call."""
    bot = MockBot()
    changer = ColorChanger(bot)
    with patch.object(changer, "api") as mock_api:
        mock_api.request = AsyncMock(return_value=({"data": [{"id": "123"}]}, 200, {}))
        data, status = await changer._make_user_info_request()
        assert data == {"data": [{"id": "123"}]}
        assert status == 200
        mock_api.request.assert_called_once_with(
            "GET",
            "users",
            access_token="test_token",
            client_id="test_client_id",
        )


@pytest.mark.asyncio
async def test_get_current_color_direct():
    """Test _get_current_color calls _get_current_color_impl."""
    bot = MockBot()
    changer = ColorChanger(bot)
    with patch.object(changer, "_get_current_color_impl", new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = "blue"
        result = await changer._get_current_color()
        assert result == "blue"
        mock_impl.assert_called_once()


@pytest.mark.asyncio
async def test_make_color_request():
    """Test _make_color_request makes correct API call."""
    bot = MockBot()
    changer = ColorChanger(bot)
    changer.user_id = "12345"
    with patch.object(changer, "api") as mock_api:
        mock_api.request = AsyncMock(return_value=({"data": [{"color": "red"}]}, 200, {}))
        data, status = await changer._make_color_request()
        assert data == {"data": [{"color": "red"}]}
        assert status == 200
        mock_api.request.assert_called_once_with(
            "GET",
            CHAT_COLOR_ENDPOINT,
            access_token="test_token",
            client_id="test_client_id",
            params={"user_id": "12345"},
        )


@pytest.mark.asyncio
async def test_perform_color_request_network_error():
    """Test _perform_color_request handles network errors."""
    bot = MockBot()
    changer = ColorChanger(bot)
    import aiohttp
    with patch("src.bot.color_changer.handle_retryable_error", side_effect=aiohttp.ClientError("Network error")):
        result = await changer._perform_color_request({"color": "green"}, action="test")
        assert result.status == ColorRequestStatus.INTERNAL_ERROR
        assert "Max retries exceeded" in result.error


@pytest.mark.asyncio
async def test_get_user_info_impl_network_error():
    """Test _get_user_info_impl handles network errors."""
    bot = MockBot()
    changer = ColorChanger(bot)
    import aiohttp
    with patch("src.bot.color_changer.handle_retryable_error", side_effect=aiohttp.ClientError("Network error")):
        result = await changer._get_user_info_impl()
        assert result is None


@pytest.mark.asyncio
async def test_get_current_color_impl_network_error():
    """Test _get_current_color_impl handles network errors."""
    bot = MockBot()
    changer = ColorChanger(bot)
    import aiohttp
    with patch("src.bot.color_changer.handle_retryable_error", side_effect=aiohttp.ClientError("Network error")):
        result = await changer._get_current_color_impl()
        assert result is None


@pytest.mark.asyncio
async def test_cache_concurrent_access():
    """Test cache handles concurrent access."""
    bot = MockBot()
    changer = ColorChanger(bot)
    bot.user_id = "test_user"
    async def access_cache():
        async with changer._cache_lock:
            changer._current_color_cache["test_user"] = {"color": "blue", "timestamp": time.time()}
        return await changer._get_current_color_impl()
    with patch.object(changer, "_make_color_request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = ({"data": [{"color": "red"}]}, 200)
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = "red"
            result = await access_cache()
            assert result == "blue"


@pytest.mark.asyncio
async def test_process_user_info_response_edge_cases():
    """Test _process_user_info_response with edge cases."""
    bot = MockBot()
    changer = ColorChanger(bot)
    # Non-dict first item
    result = changer._process_user_info_response({"data": ["not_dict"]}, 200, 1)
    assert result is None
    # Empty data
    result = changer._process_user_info_response({"data": []}, 200, 1)
    assert result is None


@pytest.mark.asyncio
async def test_process_color_response_edge_cases():
    """Test _process_color_response with edge cases."""
    bot = MockBot()
    changer = ColorChanger(bot)
    # Non-dict first item
    result = changer._process_color_response({"data": ["not_dict"]}, 200, 1)
    assert result is None
    # Non-str color
    result = changer._process_color_response({"data": [{"color": 123}]}, 200, 1)
    assert result is None


@pytest.mark.asyncio
async def test_handle_color_response_edge_cases():
    """Test _handle_color_response with edge cases."""
    bot = MockBot()
    changer = ColorChanger(bot)
    # 400 error
    result = changer._handle_color_response(400, 1)
    assert result.status == ColorRequestStatus.HTTP_ERROR
    assert result.http_status == 400
    # 502 error retry then fail
    result = changer._handle_color_response(502, 1)
    assert result is None
    result = changer._handle_color_response(502, 6)
    assert result.status == ColorRequestStatus.HTTP_ERROR


@pytest.mark.asyncio
async def test_extract_color_error_snippet_exceptions():
    """Test _extract_color_error_snippet with exceptions."""
    bot = MockBot()
    changer = ColorChanger(bot)
    # Invalid payload
    changer._last_color_change_payload = "string"
    result = changer._extract_color_error_snippet()
    assert result is None
    changer._last_color_change_payload = None
    result = changer._extract_color_error_snippet()
    assert result is None


@pytest.mark.asyncio
async def test_properties_access():
    """Test property access."""
    bot = MockBot()
    changer = ColorChanger(bot)
    assert changer.username == "testuser"
    assert changer.config_file == "test_config.json"
    assert changer.user_id == "12345"
    assert changer.api == bot.api
    assert changer.access_token == "test_token"
    assert changer.client_id == "test_client_id"
    assert changer._color_service is None
    assert changer.last_color is None
    assert changer._last_color_change_payload is None
    assert changer.use_random_colors is False


@pytest.mark.asyncio
async def test_change_color_with_existing_service():
    """Test _change_color with existing service."""
    bot = MockBot()
    changer = ColorChanger(bot)
    mock_service = MagicMock()
    mock_service.change_color = AsyncMock(return_value=True)
    bot._color_service = mock_service
    result = await changer._change_color("yellow")
    assert result is True
    mock_service.change_color.assert_called_once_with("yellow")


@pytest.mark.asyncio
async def test_prime_color_state_with_existing_last_color():
    """Test _prime_color_state overwrites existing last_color."""
    bot = MockBot()
    changer = ColorChanger(bot)
    bot.last_color = "existing"
    with patch.object(changer, "_get_current_color", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = "new"
        await changer._prime_color_state()
        assert changer.last_color == "new"
