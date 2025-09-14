import math
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.color_changer import ColorChanger
from src.color.models import ColorRequestResult, ColorRequestStatus


class TestColorChanger(ColorChanger):
    """Test implementation of ColorChanger mixin with required attributes."""

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()
    assert hasattr(changer, "_cache_lock")
    assert hasattr(changer, "_current_color_cache")
    assert hasattr(changer, "_successful_color_cache")
    assert math.isclose(changer._cache_ttl, 30.0)
    assert isinstance(changer._current_color_cache, dict)
    assert isinstance(changer._successful_color_cache, dict)


@pytest.mark.asyncio
async def test_current_color_cache_hit():
    """Test cache hit for current color fetch."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()
    changer.user_id = "test_user"
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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()
    changer.user_id = "test_user"

    with patch.object(changer, "_make_color_request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = ({"data": [{"color": "blue"}]}, 200)
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = "blue"
            result = await changer._get_current_color_impl()
            assert result == "blue"
            mock_retry.assert_called_once()


@pytest.mark.asyncio
async def test_successful_color_cache_hit():
    """Test cache hit for successful color change."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()
    changer.user_id = "test_user"
    changer._successful_color_cache["test_user"] = {"red"}

    with patch.object(changer, "api") as mock_api:
        result = await changer._perform_color_request({"color": "red"}, action="test")
        assert result.status == ColorRequestStatus.SUCCESS
        mock_api.request.assert_not_called()


@pytest.mark.asyncio
async def test_successful_color_cache_miss():
    """Test cache miss for successful color change."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()
    changer.user_id = "test_user"

    with patch.object(changer, "api") as mock_api:
        mock_api.request.return_value = ({}, 204, {})
        with patch("src.bot.color_changer.handle_retryable_error", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204)
            result = await changer._perform_color_request({"color": "blue"}, action="test")
            assert result.status == ColorRequestStatus.SUCCESS
            assert "blue" in changer._successful_color_cache["test_user"]


# Retry logic tests
@pytest.mark.asyncio
async def test_user_info_retry_on_429():
    """Test retry logic on 429 for user info."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    result = changer._handle_color_response(204, 1)
    assert result.status == ColorRequestStatus.SUCCESS
    assert result.http_status == 204

    result = changer._handle_color_response(200, 1)
    assert result.status == ColorRequestStatus.SUCCESS
    assert result.http_status == 200


@pytest.mark.asyncio
async def test_handle_color_response_unauthorized():
    """Test handling of unauthorized color change responses."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    result = changer._handle_color_response(401, 1)
    assert result.status == ColorRequestStatus.UNAUTHORIZED
    assert result.http_status == 401


@pytest.mark.asyncio
async def test_handle_color_response_rate_limit():
    """Test handling of rate limit color change responses."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    result = changer._handle_color_response(418, 1)  # I'm a teapot
    assert result.status == ColorRequestStatus.HTTP_ERROR
    assert result.http_status == 418


# Response parsing failures tests
@pytest.mark.asyncio
async def test_process_user_info_response_invalid_data():
    """Test processing invalid user info response data."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    result = changer._process_user_info_response({"data": [{}]}, 200, 1)
    assert result == {}

    result = changer._process_user_info_response({"data": [{"name": "test"}]}, 200, 1)
    assert result == {"name": "test"}


@pytest.mark.asyncio
async def test_process_color_response_invalid_data():
    """Test processing invalid color response data."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    result = changer._process_color_response({"data": [{}]}, 200, 1)
    assert result is None

    result = changer._process_color_response({"data": [{"name": "test"}]}, 200, 1)
    assert result is None


@pytest.mark.asyncio
async def test_extract_color_error_snippet():
    """Test extraction of error snippets from color change responses."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    # No payload
    changer._last_color_change_payload = None
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
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()
    changer.config_file = None

    # Should not raise or do anything
    await changer.on_persistent_prime_detection()
    # No assertions needed, just ensure no exceptions


@pytest.mark.asyncio
async def test_on_persistent_prime_detection_success():
    """Test successful persistent prime detection."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    with patch("src.bot.color_changer.queue_user_update", new_callable=AsyncMock) as mock_queue:
        await changer.on_persistent_prime_detection()
        mock_queue.assert_called_once()
        args = mock_queue.call_args[0]
        assert args[0]["is_prime_or_turbo"] is False


@pytest.mark.asyncio
async def test_on_persistent_prime_detection_error():
    """Test persistent prime detection with persistence error."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    with patch("src.bot.color_changer.queue_user_update", side_effect=OSError("Disk full")):
        # Should not raise, just log warning
        await changer.on_persistent_prime_detection()


@pytest.mark.asyncio
async def test_prime_color_state_with_color():
    """Test initializing last_color with current color."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    with patch.object(changer, "_get_current_color", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = "purple"
        await changer._prime_color_state()
        assert changer.last_color == "purple"


@pytest.mark.asyncio
async def test_prime_color_state_no_color():
    """Test initializing last_color when no color is returned."""
    changer = TestColorChanger()
    changer.username = "testuser"
    changer.config_file = "test_config.json"
    changer.user_id = "12345"
    changer.api = MagicMock()
    changer.access_token = "test_token"
    changer.client_id = "test_client_id"
    changer._color_service = None
    changer.last_color = None
    changer._last_color_change_payload = None
    changer._init_color_cache()

    with patch.object(changer, "_get_current_color", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        await changer._prime_color_state()
        assert changer.last_color is None
