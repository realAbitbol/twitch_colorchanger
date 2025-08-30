import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Ensure canonical module identity for simple_irc during tests
import src.simple_irc  # type: ignore # noqa: F401
from src.bot import TwitchColorBot


@pytest.fixture
def bot_config():
    return {
        "token": "oauth:testtoken",
        "refresh_token": "refreshtoken",
        "client_id": "clientid",
        "client_secret": "clientsecret",
        "nick": "testuser",
        "channels": ["testchannel"],
        "is_prime_or_turbo": True,
        "config_file": None,
        "user_id": None
    }


def test_bot_init(bot_config):
    bot = TwitchColorBot(**bot_config)
    assert bot.username == "testuser"
    assert bot.access_token == "testtoken"
    assert bot.channels == ["testchannel"]
    assert bot.use_random_colors is True


def test_handle_irc_message_self_increments(bot_config):
    bot = TwitchColorBot(**bot_config)
    bot.messages_sent = 0

    # Mock event loop to be available and the change_color method
    with patch('asyncio.get_event_loop') as mock_get_loop, \
            patch.object(asyncio, "run_coroutine_threadsafe") as run_coro, \
            patch.object(bot, '_change_color', new_callable=AsyncMock):

        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop

        bot.handle_irc_message("testuser", "testchannel", "msg")
        assert bot.messages_sent == 1
        # Just verify that run_coroutine_threadsafe was called
        run_coro.assert_called_once()


def test_handle_irc_message_other_noop(bot_config):
    bot = TwitchColorBot(**bot_config)
    bot.messages_sent = 0
    bot.handle_irc_message("otheruser", "testchannel", "msg")
    assert bot.messages_sent == 0


def test_get_token_check_interval_default(bot_config):
    bot = TwitchColorBot(**bot_config)
    assert bot._get_token_check_interval() == 600


def test_has_token_expiry_false(bot_config):
    bot = TwitchColorBot(**bot_config)
    assert not bot._has_token_expiry()


def test_hours_until_expiry_inf(bot_config):
    bot = TwitchColorBot(**bot_config)
    assert bot._hours_until_expiry() == float("inf")


def test_stop_sets_running_false(bot_config):
    bot = TwitchColorBot(**bot_config)
    bot.running = True
    bot.irc = MagicMock()

    # Use asyncio.run instead of get_event_loop
    asyncio.run(bot.stop())
    assert not bot.running
    bot.irc.disconnect.assert_called()


# Additional comprehensive test cases

@pytest.fixture
def mock_irc():
    """Mock IRC connection"""
    mock_irc = MagicMock()
    mock_irc.connect = MagicMock()
    mock_irc.join_channel = MagicMock()
    mock_irc.set_message_handler = MagicMock()
    mock_irc.listen = MagicMock()
    mock_irc.disconnect = MagicMock()
    return mock_irc


@pytest.fixture
def mock_rate_limiter():
    """Mock rate limiter"""
    mock_rl = MagicMock()
    mock_rl.wait_if_needed = AsyncMock(return_value=None)
    mock_rl.update_from_headers = MagicMock()
    mock_rl.handle_429_error = MagicMock()
    mock_rl.user_bucket = MagicMock()
    mock_rl.user_bucket.remaining = 100
    mock_rl.user_bucket.limit = 800
    mock_rl.user_bucket.reset_timestamp = time.time() + 60
    mock_rl.user_bucket.last_updated = time.time()
    return mock_rl


def test_init_with_oauth_prefix(bot_config):
    """Test initialization with oauth: prefix in token"""
    config = dict(bot_config)
    config['token'] = 'oauth:test_token'
    bot = TwitchColorBot(**config)
    assert bot.access_token == 'test_token'


def test_init_without_oauth_prefix(bot_config):
    """Test initialization without oauth: prefix in token"""
    config = dict(bot_config)
    config['token'] = 'test_token'
    bot = TwitchColorBot(**config)
    assert bot.access_token == 'test_token'


@patch('src.bot.SimpleTwitchIRC')
@patch('src.bot.get_rate_limiter')
@patch('src.bot.asyncio.create_task')
@patch('src.bot.asyncio.get_event_loop')
@patch('src.bot.print_log')
async def test_start_success(
        mock_print_log,
        mock_get_loop,
        mock_create_task,
        mock_get_rate_limiter,
        mock_simple_irc_class,
        bot_config,
        mock_irc,
        mock_rate_limiter):
    """Test successful bot start"""
    bot = TwitchColorBot(**bot_config)
    # Setup mocks
    mock_simple_irc_class.return_value = mock_irc
    mock_get_rate_limiter.return_value = mock_rate_limiter
    mock_loop = MagicMock()
    mock_get_loop.return_value = mock_loop
    mock_token_task = MagicMock()
    mock_create_task.return_value = mock_token_task

    # Mock successful user info retrieval
    async def mock_get_user_info():
        await asyncio.sleep(0)  # Make it truly async
        return {'id': '12345'}

    async def mock_get_current_color():
        await asyncio.sleep(0)  # Make it truly async
        return '#FF0000'

    async def mock_check_and_refresh_token(force=False):
        await asyncio.sleep(0)  # Make it truly async
        return True

    async def mock_periodic_token_check():
        """Mock periodic token check - does nothing"""
        await asyncio.sleep(0)  # Make it truly async

    with patch.object(bot, '_get_user_info', side_effect=mock_get_user_info):
        with patch.object(bot, '_get_current_color', side_effect=mock_get_current_color):
            with patch.object(bot, '_check_and_refresh_token', side_effect=mock_check_and_refresh_token):
                with patch.object(bot, '_periodic_token_check', side_effect=mock_periodic_token_check):
                    # Mock gather to return immediately
                    async def mock_gather(*args, **kwargs):
                        await asyncio.sleep(0)  # Make it truly async
                        return [None, None]
                    with patch('src.bot.asyncio.gather', side_effect=mock_gather):
                        await bot.start()

    # Verify IRC setup
    mock_simple_irc_class.assert_called_once()
    mock_irc.connect.assert_called_once_with('testtoken', 'testuser', 'testchannel')
    mock_irc.join_channel.assert_called_once_with('testchannel')
    mock_irc.set_message_handler.assert_called_once_with(bot.handle_irc_message)

    # Verify background tasks
    mock_create_task.assert_called_once()
    mock_loop.run_in_executor.assert_called_once_with(None, mock_irc.listen)


@patch('src.bot.print_log')
async def test_start_no_user_id(mock_print_log, bot_config):
    """Test bot start when user ID retrieval fails"""
    bot = TwitchColorBot(**bot_config)
    with patch.object(bot, '_get_user_info', return_value=AsyncMock(return_value=None)):
        with patch.object(bot, '_check_and_refresh_token', return_value=AsyncMock(return_value=True)):
            await bot.start()

    # Should not proceed with IRC setup
    assert bot.irc is None


@patch('src.bot.SimpleTwitchIRC')
@patch('src.bot.get_rate_limiter')
@patch('src.bot.asyncio.create_task')
@patch('src.bot.asyncio.get_event_loop')
@patch('src.bot.print_log')
async def test_start_multiple_channels(
        mock_print_log,
        mock_get_loop,
        mock_create_task,
        mock_get_rate_limiter,
        mock_simple_irc_class,
        bot_config,
        mock_irc,
        mock_rate_limiter):
    """Test bot start with multiple channels"""
    # Setup bot with multiple channels
    config = bot_config.copy()
    config['channels'] = ['channel1', 'channel2', 'channel3']
    bot = TwitchColorBot(**config)

    # Setup mocks
    mock_simple_irc_class.return_value = mock_irc
    mock_get_rate_limiter.return_value = mock_rate_limiter
    mock_loop = MagicMock()
    mock_get_loop.return_value = mock_loop
    mock_token_task = MagicMock()
    mock_create_task.return_value = mock_token_task

    # Mock successful user info retrieval
    async def mock_get_user_info():
        await asyncio.sleep(0)  # Make it truly async
        return {'id': '12345'}

    async def mock_get_current_color():
        await asyncio.sleep(0)  # Make it truly async
        return '#FF0000'

    async def mock_check_and_refresh_token(force=False):
        await asyncio.sleep(0)  # Make it truly async
        return True

    async def mock_periodic_token_check():
        """Mock periodic token check - does nothing"""
        await asyncio.sleep(0)  # Make it truly async

    with patch.object(bot, '_get_user_info', side_effect=mock_get_user_info):
        with patch.object(bot, '_get_current_color', side_effect=mock_get_current_color):
            with patch.object(bot, '_check_and_refresh_token', side_effect=mock_check_and_refresh_token):
                with patch.object(bot, '_periodic_token_check', side_effect=mock_periodic_token_check):
                    # Mock gather to return immediately
                    async def mock_gather(*args, **kwargs):
                        await asyncio.sleep(0)  # Make it truly async
                        return [None, None]
                    with patch('src.bot.asyncio.gather', side_effect=mock_gather):
                        await bot.start()

    # Verify all channels are joined
    assert mock_irc.join_channel.call_count == 3
    mock_irc.join_channel.assert_any_call('channel1')
    mock_irc.join_channel.assert_any_call('channel2')
    mock_irc.join_channel.assert_any_call('channel3')


@patch('src.bot.print_log')
async def test_stop(mock_print_log, bot_config, mock_irc):
    """Test bot stop"""
    bot = TwitchColorBot(**bot_config)
    bot.irc = mock_irc
    bot.running = True

    # Create a custom awaitable mock task
    class MockAwaitableTask:
        def __init__(self):
            self.cancel = MagicMock()

        def done(self):
            return False

        def __await__(self):
            async def _await():
                await asyncio.sleep(0)  # Make it truly async
                return None
            return _await().__await__()

    mock_token_task = MockAwaitableTask()
    bot.token_task = mock_token_task

    mock_irc_task = MagicMock()
    mock_irc_task.done.return_value = False
    bot.irc_task = mock_irc_task

    with patch('src.bot.asyncio.wait_for', return_value=AsyncMock()):
        await bot.stop()

    # Verify cleanup
    assert bot.running is False
    mock_token_task.cancel.assert_called_once()
    mock_irc.disconnect.assert_called_once()


def test_handle_irc_message_case_insensitive(bot_config):
    """Test handling IRC message with case insensitive username matching"""
    bot = TwitchColorBot(**bot_config)
    bot.username = 'TestUser'

    with patch('src.bot.asyncio.get_event_loop') as mock_get_loop:
        with patch('src.bot.asyncio.run_coroutine_threadsafe') as mock_run_coroutine:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            bot.handle_irc_message('testuser', '#channel', 'Hello world!')

            # Should match case insensitively
            mock_run_coroutine.assert_called_once()


def test_handle_irc_message_runtime_error_fallback(bot_config):
    """Test handling IRC message with RuntimeError fallback"""
    bot = TwitchColorBot(**bot_config)
    bot.username = 'testuser'

    with patch('src.bot.asyncio.get_event_loop', side_effect=RuntimeError("No event loop")):
        with patch('src.bot.asyncio.run'):
            with patch('threading.Thread') as mock_thread:
                bot.handle_irc_message('testuser', '#channel', 'Hello world!')

                # Should create a thread as fallback
                mock_thread.assert_called_once()


def test_handle_message(bot_config):
    """Test _handle_message method for compatibility"""
    bot = TwitchColorBot(**bot_config)
    bot.username = 'testuser'

    with patch.object(bot, 'handle_irc_message') as mock_handle:
        bot._handle_message('testuser', 'Hello world!', '#channel')

        mock_handle.assert_called_once_with('testuser', '#channel', 'Hello world!')


@patch('src.bot.simple_retry')
async def test_get_user_info(mock_simple_retry, bot_config):
    """Test user info retrieval"""
    bot = TwitchColorBot(**bot_config)
    mock_simple_retry.return_value = {'id': '12345', 'login': 'testuser'}

    result = await bot._get_user_info()

    mock_simple_retry.assert_called_once_with(bot._get_user_info_impl, user='testuser')
    assert result == {'id': '12345', 'login': 'testuser'}


@patch('src.bot._make_api_request')
async def test_get_user_info_impl_success(
        mock_make_request,
        bot_config,
        mock_rate_limiter):
    """Test successful user info implementation"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    # Mock successful API response
    mock_make_request.return_value = (
        {'data': [{'id': '12345', 'login': 'testuser'}]},
        200,
        {'Ratelimit-Remaining': '799', 'Ratelimit-Limit': '800', 'Ratelimit-Reset': str(int(time.time()) + 60)}
    )

    result = await bot._get_user_info_impl()

    assert result == {'id': '12345', 'login': 'testuser'}
    mock_rate_limiter.wait_if_needed.assert_called_once_with(
        'get_user_info', is_user_request=True)
    mock_rate_limiter.update_from_headers.assert_called_once()


@patch('src.bot._make_api_request')
async def test_get_user_info_impl_401_error(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test user info implementation with 401 error"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    # Mock 401 response
    mock_make_request.return_value = ({}, 401, {})

    result = await bot._get_user_info_impl()

    assert result is None


@patch('src.bot._make_api_request')
async def test_get_user_info_impl_429_error(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test user info implementation with 429 error"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    # Mock 429 response
    mock_make_request.return_value = ({}, 429, {'Retry-After': '60'})

    result = await bot._get_user_info_impl()

    assert result is None
    mock_rate_limiter.handle_429_error.assert_called_once_with(
        {'Retry-After': '60'}, is_user_request=True)


@patch('src.bot.simple_retry')
async def test_get_current_color(mock_simple_retry, bot_config):
    """Test current color retrieval"""
    bot = TwitchColorBot(**bot_config)
    mock_simple_retry.return_value = '#FF0000'

    result = await bot._get_current_color()

    mock_simple_retry.assert_called_once_with(
        bot._get_current_color_impl, user='testuser')
    assert result == '#FF0000'


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_success(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test successful current color implementation"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock successful API response
    mock_make_request.return_value = (
        {'data': [{'color': '#FF0000'}]},
        200,
        {'Ratelimit-Remaining': '799', 'Ratelimit-Limit': '800', 'Ratelimit-Reset': str(int(time.time()) + 60)}
    )

    result = await bot._get_current_color_impl()

    assert result == '#FF0000'
    mock_rate_limiter.wait_if_needed.assert_called_once_with(
        'get_current_color', is_user_request=True)


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_no_color(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation when no color is set"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock response with no color data
    mock_make_request.return_value = ({'data': []}, 200, {})

    result = await bot._get_current_color_impl()

    assert result is None


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_429_error(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation with 429 error"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock 429 response
    mock_make_request.return_value = ({}, 429, {'Retry-After': '60'})

    result = await bot._get_current_color_impl()

    assert result is None
    mock_rate_limiter.handle_429_error.assert_called_once_with(
        {'Retry-After': '60'}, is_user_request=True)


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_server_error(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation with server error (covers line 375)"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock 500 response - this should trigger the fallback case
    mock_make_request.return_value = ({}, 500, {})

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_current_color_impl()

        assert result is None
        # Should log the fallback message - check the actual log output from capture
        mock_logger.info.assert_called_with(
            "No current color set (using default)", user="testuser")


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_no_color_in_response(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation when response has data but no color field (covers line 375)"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock response: 200 status, has data array with 1 element, but that element has no 'color' key
    # This should pass all conditions up to the color check, then hit the fallback
    mock_make_request.return_value = ({'data': [{'other_field': 'value'}]}, 200, {})

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_current_color_impl()

        assert result is None
        mock_logger.info.assert_called_with(
            "No current color set (using default)", user="testuser")


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_empty_color(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation when color field is empty (covers line 375)"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock response: 200 status, has data, color field exists but is empty/falsy
    mock_make_request.return_value = ({'data': [{'color': ''}]}, 200, {})

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_current_color_impl()

        assert result is None
        mock_logger.info.assert_called_with(
            "No current color set (using default)", user="testuser")


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_status_500_fallback(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation with non-200/401/429 status (covers line 375)"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock response with 500 status - should fall through to logging
    mock_make_request.return_value = ({}, 500, {})

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_current_color_impl()

        assert result is None
        mock_logger.info.assert_called_with(
            "No current color set (using default)", user="testuser")


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_401_error(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation with 401 error (covers 401 path)"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock 401 response - should return None without logging fallback message
    mock_make_request.return_value = ({}, 401, {})

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_current_color_impl()

        assert result is None
        # Should NOT call the fallback logger.info since 401 returns early
        mock_logger.info.assert_not_called()


def test_select_color_random(bot_config):
    """Test color selection for random colors"""
    bot = TwitchColorBot(**bot_config)
    bot.use_random_colors = True
    bot.last_color = '#FF0000'

    with patch('src.bot.generate_random_hex_color') as mock_generate:
        mock_generate.return_value = '#00FF00'

        result = bot._select_color()

        mock_generate.assert_called_once_with(exclude_color='#FF0000')
        assert result == '#00FF00'


def test_select_color_preset(bot_config):
    """Test color selection for preset colors"""
    bot = TwitchColorBot(**bot_config)
    bot.use_random_colors = False
    bot.last_color = 'Blue'

    with patch('src.bot.get_different_twitch_color') as mock_get_different:
        mock_get_different.return_value = 'Red'

        result = bot._select_color()

        mock_get_different.assert_called_once_with(exclude_color='Blue')
        assert result == 'Red'


@patch('src.bot._make_api_request')
async def test_attempt_color_change_success(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test successful color change attempt"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock successful API response
    mock_make_request.return_value = ({},
                                      204,
                                      {'Ratelimit-Remaining': '799',
                                       'Ratelimit-Limit': '800',
                                       'Ratelimit-Reset': str(int(time.time()) + 60)})

    result = await bot._attempt_color_change('#FF0000')

    assert result is True
    assert bot.colors_changed == 1
    assert bot.last_color == '#FF0000'


@patch('src.bot._make_api_request')
async def test_attempt_color_change_429_error(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test color change attempt with 429 error"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock 429 response
    mock_make_request.return_value = ({}, 429, {'Retry-After': '60'})

    result = await bot._attempt_color_change('#FF0000')

    assert result is False
    assert bot.colors_changed == 0
    mock_rate_limiter.handle_429_error.assert_called_once()


@patch('src.bot._make_api_request')
async def test_attempt_color_change_timeout(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test color change attempt with timeout"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock timeout
    mock_make_request.side_effect = asyncio.TimeoutError()

    result = await bot._attempt_color_change('#FF0000')

    assert result is False
    assert bot.colors_changed == 0


def test_handle_color_change_response_success(bot_config):
    """Test handling successful color change response"""
    bot = TwitchColorBot(**bot_config)
    result = bot._handle_color_change_response(204, '#FF0000')

    assert result is True
    assert bot.colors_changed == 1
    assert bot.last_color == '#FF0000'


def test_handle_color_change_response_429(bot_config, mock_rate_limiter):
    """Test handling 429 color change response"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    result = bot._handle_color_change_response(429, '#FF0000')

    assert result is False
    assert bot.colors_changed == 0
    mock_rate_limiter.handle_429_error.assert_called_once()


def test_handle_color_change_response_error(bot_config):
    """Test handling error color change response"""
    bot = TwitchColorBot(**bot_config)
    result = bot._handle_color_change_response(400, '#FF0000')

    assert result is False
    assert bot.colors_changed == 0


def test_handle_api_error_turbo_required(bot_config):
    """Test handling API error for Turbo/Prime requirement"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    error = APIError("Turbo or Prime user required for hex colors", 400)
    bot.use_random_colors = True

    with patch('src.bot.disable_random_colors_for_user', return_value=True):
        result = bot._handle_api_error(error)

        assert result is False
        assert bot.use_random_colors is False


def test_handle_api_error_other_error(bot_config):
    """Test handling other API errors"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    error = APIError("Some other error", 500)

    result = bot._handle_api_error(error)

    assert result is False
    assert bot.use_random_colors is True  # Should not change


@patch('src.bot._make_api_request')
async def test_try_preset_color_fallback_success(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test successful preset color fallback"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'
    bot.last_color = '#FF0000'

    # Mock successful API response
    mock_make_request.return_value = ({},
                                      204,
                                      {'Ratelimit-Remaining': '799',
                                       'Ratelimit-Limit': '800',
                                       'Ratelimit-Reset': str(int(time.time()) + 60)})

    with patch('src.bot.get_different_twitch_color', return_value='Blue'):
        result = await bot._try_preset_color_fallback()

        assert result is True
        assert bot.colors_changed == 1
        assert bot.last_color == 'Blue'


@patch('src.bot._make_api_request')
async def test_try_preset_color_fallback_failure(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test failed preset color fallback"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock failed API response
    mock_make_request.return_value = ({}, 400, {})

    result = await bot._try_preset_color_fallback()

    assert result is False
    assert bot.colors_changed == 0


@patch('src.bot._make_api_request')
async def test_change_color_with_hex(mock_make_request, bot_config, mock_rate_limiter):
    """Test color change with provided hex color"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock successful API response
    mock_make_request.return_value = ({}, 204, {})

    result = await bot._change_color('#FF0000')

    assert result is True
    assert bot.colors_changed == 1
    assert bot.last_color == '#FF0000'


@patch('src.bot._make_api_request')
async def test_change_color_auto_select(
        mock_make_request,
        bot_config,
        mock_rate_limiter):
    """Test color change with auto selection"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'
    bot.use_random_colors = True

    # Mock successful API response
    mock_make_request.return_value = ({}, 204, {})

    with patch.object(bot, '_select_color', return_value='#00FF00'):
        result = await bot._change_color()

        assert result is True
        assert bot.colors_changed == 1
        assert bot.last_color == '#00FF00'


@patch('src.bot._make_api_request')
async def test_change_color_fallback_to_preset(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test color change with fallback to preset colors"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'
    bot.use_random_colors = True

    # Mock first attempt failure, second success
    mock_make_request.side_effect = [
        ({}, 400, {}),  # First call fails
        ({}, 204, {})   # Second call succeeds
    ]

    with patch.object(bot, '_select_color', return_value='#00FF00'):
        with patch('src.bot.get_different_twitch_color', return_value='Blue'):
            result = await bot._change_color()

            assert result is True
            assert bot.colors_changed == 1
            assert bot.last_color == 'Blue'


def test_get_rate_limit_display_high_remaining(bot_config, mock_rate_limiter):
    """Test rate limit display with high remaining requests"""
    import time
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    mock_rate_limiter.user_bucket.remaining = 150
    mock_rate_limiter.user_bucket.limit = 800
    mock_rate_limiter.user_bucket.reset_timestamp = time.time() + 60
    mock_rate_limiter.user_bucket.last_updated = time.time()

    result = bot._get_rate_limit_display()

    assert "[150/800 reqs]" in result


def test_get_rate_limit_display_medium_remaining(bot_config, mock_rate_limiter):
    """Test rate limit display with medium remaining requests"""
    import time
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    mock_rate_limiter.user_bucket.remaining = 50
    mock_rate_limiter.user_bucket.limit = 800
    mock_rate_limiter.user_bucket.reset_timestamp = time.time() + 120
    mock_rate_limiter.user_bucket.last_updated = time.time()

    result = bot._get_rate_limit_display()

    assert "[50/800 reqs, reset in 120s]" in result


def test_get_rate_limit_display_low_remaining(bot_config, mock_rate_limiter):
    """Test rate limit display with low remaining requests"""
    import time
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    mock_rate_limiter.user_bucket.remaining = 5
    mock_rate_limiter.user_bucket.limit = 800
    mock_rate_limiter.user_bucket.reset_timestamp = time.time() + 60
    mock_rate_limiter.user_bucket.last_updated = time.time()

    result = bot._get_rate_limit_display()

    assert "⚠️" in result
    assert "5/800 reqs, reset in 60s" in result


def test_get_rate_limit_display_no_bucket(bot_config):
    """Test rate limit display with no bucket info"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = MagicMock()
    bot.rate_limiter.user_bucket = None

    result = bot._get_rate_limit_display()

    assert "[rate limit info pending]" in result


def test_get_rate_limit_display_stale_bucket(bot_config, mock_rate_limiter):
    """Test rate limit display with stale bucket info"""
    import time
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    mock_rate_limiter.user_bucket.last_updated = time.time() - 120  # 2 minutes ago

    result = bot._get_rate_limit_display()

    assert "[rate limit info stale]" in result


@patch('src.bot.simple_retry')
async def test_refresh_access_token(mock_simple_retry, bot_config):
    """Test access token refresh"""
    bot = TwitchColorBot(**bot_config)
    mock_simple_retry.return_value = True

    result = await bot._refresh_access_token()

    mock_simple_retry.assert_called_once_with(
        bot._refresh_access_token_impl, user='testuser')
    assert result is True


@patch('src.bot.aiohttp.ClientSession')
async def test_refresh_access_token_impl_success(mock_session_class, bot_config):
    """Test successful token refresh implementation"""
    bot = TwitchColorBot(**bot_config)
    # Mock the session and response
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        'access_token': 'new_access_token',
        'refresh_token': 'new_refresh_token',
        'expires_in': 3600
    })

    mock_session.post.return_value.__aenter__.return_value = mock_response
    mock_session_class.return_value.__aenter__.return_value = mock_session

    result = await bot._refresh_access_token_impl()

    assert result is True
    assert bot.access_token == 'new_access_token'
    assert bot.refresh_token == 'new_refresh_token'
    assert bot.token_expiry is not None


@patch('src.bot.aiohttp.ClientSession')
async def test_refresh_access_token_impl_failure(mock_session_class, bot_config):
    """Test failed token refresh implementation"""
    bot = TwitchColorBot(**bot_config)
    # Mock the session and response
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 400
    mock_response.text = AsyncMock(return_value='Invalid refresh token')

    mock_session.post.return_value.__aenter__.return_value = mock_response
    mock_session_class.return_value.__aenter__.return_value = mock_session

    result = await bot._refresh_access_token_impl()

    assert result is False


async def test_check_and_refresh_token_no_refresh_token(bot_config):
    """Test token check when no refresh token available"""
    bot = TwitchColorBot(**bot_config)
    bot.refresh_token = None

    with patch('src.bot.print_log') as mock_print_log:
        result = await bot._check_and_refresh_token()

        assert result is False
        mock_print_log.assert_called_once()


async def test_check_and_refresh_token_force_refresh(bot_config):
    """Test forced token refresh"""
    bot = TwitchColorBot(**bot_config)
    with patch.object(bot, '_force_token_refresh', return_value=True) as mock_force:
        result = await bot._check_and_refresh_token(force=True)

        mock_force.assert_called_once_with(initial=True)
        assert result is True


async def test_check_and_refresh_token_with_expiry(bot_config):
    """Test token check with expiry information"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(hours=0.5)  # 30 minutes from now

    with patch.object(bot, '_check_expiring_token', return_value=True) as mock_check:
        result = await bot._check_and_refresh_token()

        mock_check.assert_called_once()
        assert result is True


async def test_check_and_refresh_token_no_expiry_validate_api(bot_config):
    """Test token check without expiry using API validation"""
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = None

    with patch.object(bot, '_validate_token_via_api', return_value=True) as mock_validate:
        result = await bot._check_and_refresh_token()

        mock_validate.assert_called_once()
        assert result is True


async def test_check_and_refresh_token_validation_failed(bot_config):
    """Test token check when API validation fails"""
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = None

    with patch.object(bot, '_validate_token_via_api', return_value=False):
        with patch.object(bot, '_attempt_standard_refresh', return_value=True) as mock_attempt:
            result = await bot._check_and_refresh_token()

            mock_attempt.assert_called_once()
            assert result is True


def test_has_token_expiry_true(bot_config):
    """Test checking if token has expiry when it does"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(hours=1)

    assert bot._has_token_expiry() is True


def test_has_token_expiry_false_with_none_expiry(bot_config):
    """Test checking if token has expiry when it doesn't"""
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = None

    assert bot._has_token_expiry() is False


def test_hours_until_expiry_with_expiry(bot_config):
    """Test calculating hours until expiry"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(hours=2)

    hours = bot._hours_until_expiry()

    assert 1.9 <= hours <= 2.1  # Approximately 2 hours


def test_hours_until_expiry_no_expiry(bot_config):
    """Test calculating hours until expiry when no expiry set"""
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = None

    hours = bot._hours_until_expiry()

    assert hours == float('inf')


async def test_force_token_refresh_success(bot_config):
    """Test successful forced token refresh"""
    bot = TwitchColorBot(**bot_config)
    with patch.object(bot, '_refresh_access_token', return_value=True):
        with patch.object(bot, '_persist_token_changes'):
            with patch('src.bot.print_log') as mock_print_log:
                result = await bot._force_token_refresh(initial=True)

                assert result is True
                assert mock_print_log.call_count == 2  # Start and success messages


async def test_force_token_refresh_failure(bot_config):
    """Test failed forced token refresh"""
    bot = TwitchColorBot(**bot_config)
    with patch.object(bot, '_refresh_access_token', return_value=False):
        with patch('src.bot.print_log') as mock_print_log:
            result = await bot._force_token_refresh(initial=False)

            assert result is False
            assert mock_print_log.call_count == 2  # Start and failure messages


async def test_check_expiring_token_refresh_needed(bot_config):
    """Test checking expiring token when refresh is needed"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(minutes=30)  # 30 minutes from now

    with patch.object(bot, '_attempt_standard_refresh', return_value=True) as mock_attempt:
        with patch('src.bot.print_log'):
            result = await bot._check_expiring_token()

            mock_attempt.assert_called_once()
            assert result is True


async def test_check_expiring_token_no_refresh_needed(bot_config):
    """Test checking expiring token when no refresh is needed"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(hours=2)  # 2 hours from now

    with patch('src.bot.print_log') as mock_print_log:
        result = await bot._check_expiring_token()

        assert result is True
        # Should log that token is valid
        assert mock_print_log.call_count >= 1


async def test_validate_token_via_api_success(bot_config):
    """Test successful token validation via API"""
    bot = TwitchColorBot(**bot_config)
    with patch.object(bot, '_get_user_info', return_value=AsyncMock(return_value={'id': '12345'})):
        with patch('src.bot.print_log') as mock_print_log:
            result = await bot._validate_token_via_api()

            assert result is True
            mock_print_log.assert_called_once()


async def test_validate_token_via_api_failure(bot_config):
    """Test failed token validation via API"""
    bot = TwitchColorBot(**bot_config)
    with patch.object(bot, '_get_user_info', return_value=None):
        with patch('src.bot.print_log') as mock_print_log:
            result = await bot._validate_token_via_api()

            assert result is False
            mock_print_log.assert_called_once()


async def test_attempt_standard_refresh_success(bot_config):
    """Test successful standard token refresh attempt"""
    bot = TwitchColorBot(**bot_config)
    with patch.object(bot, '_refresh_access_token', return_value=True):
        with patch.object(bot, '_persist_token_changes'):
            with patch('src.bot.print_log') as mock_print_log:
                result = await bot._attempt_standard_refresh()

                assert result is True
                assert mock_print_log.call_count == 1  # Success message


async def test_attempt_standard_refresh_failure(bot_config):
    """Test failed standard token refresh attempt"""
    bot = TwitchColorBot(**bot_config)
    with patch.object(bot, '_refresh_access_token', return_value=False):
        with patch('src.bot.print_log') as mock_print_log:
            result = await bot._attempt_standard_refresh()

            assert result is False
            assert mock_print_log.call_count == 1  # Failure message


def test_get_token_check_interval_less_than_30_min(bot_config):
    """Test token check interval when expiry is less than 30 minutes"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(minutes=15)

    interval = bot._get_token_check_interval()

    assert interval == 180  # 3 minutes


def test_get_token_check_interval_less_than_1_hour(bot_config):
    """Test token check interval when expiry is less than 1 hour"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(minutes=45)

    interval = bot._get_token_check_interval()

    assert interval == 300  # 5 minutes


def test_get_token_check_interval_less_than_2_hours(bot_config):
    """Test token check interval when expiry is less than 2 hours"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(hours=1.5)

    interval = bot._get_token_check_interval()

    assert interval == 600  # 10 minutes


def test_get_token_check_interval_more_than_2_hours(bot_config):
    """Test token check interval when expiry is more than 2 hours"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(hours=3)

    interval = bot._get_token_check_interval()

    assert interval == 1800  # 30 minutes


def test_get_token_check_interval_no_expiry(bot_config):
    """Test token check interval when no expiry is set"""
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = None

    interval = bot._get_token_check_interval()

    assert interval == 600  # 10 minutes default


def test_get_token_check_interval_exception(bot_config):
    """Test token check interval when exception occurs"""
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = "invalid"  # This will cause an exception

    interval = bot._get_token_check_interval()

    assert interval == 600  # 10 minutes default on error


async def test_periodic_token_check_running(bot_config):
    """Test periodic token check while running"""
    bot = TwitchColorBot(**bot_config)
    bot.running = True

    # Mock check method to return immediately
    async def mock_check_token():
        await asyncio.sleep(0.01)
        return True

    with patch.object(bot, '_check_and_refresh_token', side_effect=mock_check_token):
        with patch.object(bot, '_get_token_check_interval', return_value=0.01):
            # Start the periodic check and let it run briefly
            task = asyncio.create_task(bot._periodic_token_check())
            await asyncio.sleep(0.05)  # Let it run briefly
            bot.running = False  # Stop the loop

            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()


async def test_periodic_token_check_cancelled(bot_config):
    """Test periodic token check when cancelled"""
    bot = TwitchColorBot(**bot_config)
    bot.running = True

    task = asyncio.create_task(bot._periodic_token_check())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_periodic_token_check_exception(bot_config):
    """Test periodic token check with exception handling"""
    bot = TwitchColorBot(**bot_config)
    bot.running = True

    # Mock check method to raise exception
    async def mock_check_token():
        raise RuntimeError("Test exception")

    with patch.object(bot, '_check_and_refresh_token', side_effect=mock_check_token):
        with patch.object(bot, '_get_token_check_interval', return_value=0.01):
            with patch('src.bot.print_log') as mock_print_log:
                # Start the periodic check and let it run briefly
                task = asyncio.create_task(bot._periodic_token_check())
                await asyncio.sleep(0.05)  # Let it run briefly
                bot.running = False  # Stop the loop

                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except asyncio.TimeoutError:
                    task.cancel()

                # Should have logged the exception
                mock_print_log.assert_called()


def test_persist_token_changes_success(bot_config):
    """Test successful token persistence"""
    bot = TwitchColorBot(**bot_config)
    bot.config_file = "/tmp/test_config.json"

    with patch('src.bot.update_user_in_config') as mock_update:
        with patch('src.bot.print_log') as mock_print_log:
            bot._persist_token_changes()

            mock_update.assert_called_once()
            mock_print_log.assert_called_once()


def test_persist_token_changes_failure(bot_config):
    """Test token persistence failure"""
    bot = TwitchColorBot(**bot_config)
    bot.config_file = "/tmp/test_config.json"

    with patch('src.bot.update_user_in_config', side_effect=RuntimeError("Save failed")):
        with patch('src.bot.print_log') as mock_print_log:
            bot._persist_token_changes()

            # Should log error
            assert mock_print_log.call_count >= 1


def test_persist_token_changes_no_config_file(bot_config):
    """Test token persistence when no config file is set"""
    bot = TwitchColorBot(**bot_config)
    bot.config_file = None

    with patch('src.bot.print_log') as mock_print_log:
        bot._persist_token_changes()

        # Should not attempt to save
        mock_print_log.assert_not_called()


def test_close(bot_config):
    """Test bot close method"""
    bot = TwitchColorBot(**bot_config)
    mock_irc = MagicMock()
    bot.irc = mock_irc

    with patch('src.bot.print_log') as mock_print_log:
        bot.close()

        mock_irc.disconnect.assert_called_once()
        mock_print_log.assert_called_once()
        assert bot.running is False
        assert bot.irc is None


def test_close_no_irc(bot_config):
    """Test bot close method when no IRC connection"""
    bot = TwitchColorBot(**bot_config)
    bot.irc = None

    with patch('src.bot.print_log') as mock_print_log:
        bot.close()

        mock_print_log.assert_called_once()
        assert bot.running is False


def test_print_statistics(bot_config):
    """Test printing bot statistics"""
    bot = TwitchColorBot(**bot_config)
    bot.colors_changed = 5
    bot.messages_sent = 10

    with patch('src.bot.print_log') as mock_print_log:
        bot.print_statistics()

        # Should log statistics
        assert mock_print_log.call_count >= 1

# Tests for _make_api_request function and error handling


@patch('src.bot.aiohttp.ClientSession')
async def test_make_api_request_success(mock_session_class):
    """Test successful API request"""
    # Mock the session and response
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={'data': [{'id': '12345'}]})
    mock_response.headers = {'Content-Type': 'application/json'}

    mock_session.request.return_value.__aenter__.return_value = mock_response
    mock_session_class.return_value.__aenter__.return_value = mock_session

    from src.bot import _make_api_request

    result = await _make_api_request('GET', 'users', 'token', 'client_id')

    assert result[0] == {'data': [{'id': '12345'}]}
    assert result[1] == 200
    assert 'Content-Type' in result[2]


@patch('src.bot.aiohttp.ClientSession')
async def test_make_api_request_json_decode_error(mock_session_class):
    """Test API request with JSON decode error"""
    import json

    # Mock the session and response
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        side_effect=json.JSONDecodeError(
            "Invalid JSON", "", 0))
    mock_response.headers = {'Content-Type': 'text/html'}

    mock_session.request.return_value.__aenter__.return_value = mock_response
    mock_session_class.return_value.__aenter__.return_value = mock_session

    from src.bot import _make_api_request

    result = await _make_api_request('GET', 'users', 'token', 'client_id')

    assert result[0] == {}  # Should return empty dict on JSON error
    assert result[1] == 200
    assert 'Content-Type' in result[2]


@patch('src.bot.aiohttp.ClientSession')
async def test_make_api_request_content_type_error(mock_session_class):
    """Test API request with content type error"""
    import aiohttp

    # Mock the session and response
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(side_effect=aiohttp.ContentTypeError(
        None, None, message="Invalid content type"))
    mock_response.headers = {'Content-Type': 'text/html'}

    mock_session.request.return_value.__aenter__.return_value = mock_response
    mock_session_class.return_value.__aenter__.return_value = mock_session

    from src.bot import _make_api_request

    result = await _make_api_request('GET', 'users', 'token', 'client_id')

    assert result[0] == {}  # Should return empty dict on content type error
    assert result[1] == 200
    assert 'Content-Type' in result[2]

# Test for KeyboardInterrupt in start method


@patch('src.bot.SimpleTwitchIRC')
@patch('src.bot.get_rate_limiter')
@patch('src.bot.asyncio.create_task')
@patch('src.bot.asyncio.get_event_loop')
@patch('src.bot.print_log')
async def test_start_keyboard_interrupt(
        mock_print_log,
        mock_get_loop,
        mock_create_task,
        mock_get_rate_limiter,
        mock_simple_irc_class,
        bot_config,
        mock_irc,
        mock_rate_limiter):
    """Test bot start with KeyboardInterrupt"""
    bot = TwitchColorBot(**bot_config)
    # Setup mocks
    mock_simple_irc_class.return_value = mock_irc
    mock_get_rate_limiter.return_value = mock_rate_limiter
    mock_loop = MagicMock()
    mock_get_loop.return_value = mock_loop
    mock_token_task = MagicMock()
    mock_create_task.return_value = mock_token_task

    # Mock successful user info retrieval
    async def mock_get_user_info():
        await asyncio.sleep(0)
        return {'id': '12345'}

    async def mock_get_current_color():
        await asyncio.sleep(0)
        return '#FF0000'

    async def mock_check_and_refresh_token(force=False):
        await asyncio.sleep(0)
        return True

    async def mock_gather(*args, **kwargs):
        raise KeyboardInterrupt("Test interrupt")

    with patch.object(bot, '_get_user_info', side_effect=mock_get_user_info):
        with patch.object(bot, '_get_current_color', side_effect=mock_get_current_color):
            with patch.object(bot, '_check_and_refresh_token', side_effect=mock_check_and_refresh_token):
                with patch.object(bot, '_periodic_token_check', return_value=AsyncMock()):
                    with patch('src.bot.asyncio.gather', side_effect=mock_gather):
                        with patch.object(bot, 'stop', return_value=AsyncMock()) as mock_stop:
                            await bot.start()
                            mock_stop.assert_called_once()

# Test for CancelledError in stop method


async def test_stop_cancelled_error(bot_config, mock_irc):
    """Test bot stop with CancelledError when cancelling token task"""
    bot = TwitchColorBot(**bot_config)
    bot.irc = mock_irc
    bot.running = True

    # Create a mock task that raises CancelledError when awaited
    class MockCancelledTask:
        def __init__(self):
            self.cancel = MagicMock()

        def done(self):
            return False

        def __await__(self):
            async def _await():
                raise asyncio.CancelledError()
            return _await().__await__()

    mock_token_task = MockCancelledTask()
    bot.token_task = mock_token_task

    mock_irc_task = MagicMock()
    mock_irc_task.done.return_value = False
    bot.irc_task = mock_irc_task

    with patch('src.bot.asyncio.wait_for', return_value=AsyncMock()):
        # CancelledError should be re-raised from token task cleanup
        with pytest.raises(asyncio.CancelledError):
            await bot.stop()

    # Verify cleanup occurred before the error
    mock_token_task.cancel.assert_called_once()
    # Note: disconnect might not be called due to CancelledError propagation

# Test timeout in stop method


async def test_stop_timeout(bot_config, mock_irc):
    """Test bot stop with timeout waiting for IRC task"""
    bot = TwitchColorBot(**bot_config)
    bot.irc = mock_irc
    bot.running = True

    mock_token_task = MagicMock()
    mock_token_task.done.return_value = True
    bot.token_task = mock_token_task

    mock_irc_task = MagicMock()
    mock_irc_task.done.return_value = False
    bot.irc_task = mock_irc_task

    with patch('src.bot.asyncio.wait_for', side_effect=asyncio.TimeoutError()):
        with patch('src.bot.print_log') as mock_print_log:
            await bot.stop()

            # Should log timeout warning
            mock_print_log.assert_called()

# Test exception in stop method


async def test_stop_exception(bot_config, mock_irc):
    """Test bot stop with exception waiting for IRC task"""
    bot = TwitchColorBot(**bot_config)
    bot.irc = mock_irc
    bot.running = True

    mock_token_task = MagicMock()
    mock_token_task.done.return_value = True
    bot.token_task = mock_token_task

    mock_irc_task = MagicMock()
    mock_irc_task.done.return_value = False
    bot.irc_task = mock_irc_task

    with patch('src.bot.asyncio.wait_for', side_effect=RuntimeError("Test error")):
        with patch('src.bot.print_log') as mock_print_log:
            await bot.stop()

            # Should log error warning
            mock_print_log.assert_called()

# Test API error handling in _change_color


async def test_change_color_api_error_handling(bot_config, mock_rate_limiter):
    """Test color change with API error that doesn't trigger fallback"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'
    bot.use_random_colors = False  # Use preset colors

    async def mock_attempt_color_change(color):
        await asyncio.sleep(0)
        raise APIError("Some other API error", 500)

    with patch.object(bot, '_attempt_color_change', side_effect=mock_attempt_color_change):
        with patch.object(bot, '_select_color', return_value='Blue'):
            result = await bot._change_color()

            # Should fail without changing random color setting
            assert bot.use_random_colors is False
            assert result is False

# Test API error handling in get_user_info_impl


@patch('src.bot._make_api_request')
async def test_get_user_info_impl_api_error_401_retry(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test user info with 401 APIError that triggers retry"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    # First call raises 401 APIError, second call succeeds
    call_count = 0

    async def mock_make_request_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(0)
            raise APIError("Unauthorized", 401)
        await asyncio.sleep(0)
        return (
            {'data': [{'id': '12345', 'login': 'testuser'}]},
            200,
            {'Ratelimit-Remaining': '799'}
        )

    mock_make_request.side_effect = mock_make_request_side_effect

    with patch.object(bot, '_check_and_refresh_token', return_value=True):
        result = await bot._get_user_info_impl()

    assert result == {'id': '12345', 'login': 'testuser'}
    assert call_count == 2  # Should retry after token refresh


@patch('src.bot._make_api_request')
async def test_get_user_info_impl_api_error_401_refresh_failed(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test user info with 401 APIError where refresh fails"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    mock_make_request.side_effect = APIError("Unauthorized", 401)

    with patch.object(bot, '_check_and_refresh_token', return_value=False):
        with pytest.raises(APIError, match="Token refresh failed"):
            await bot._get_user_info_impl()


@patch('src.bot._make_api_request')
async def test_get_user_info_impl_non_401_api_error(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test user info with non-401 APIError"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    mock_make_request.side_effect = APIError("Server Error", 500)

    with pytest.raises(APIError):
        await bot._get_user_info_impl()


@patch('src.bot._make_api_request')
async def test_get_user_info_impl_generic_exception(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test user info with generic exception"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    mock_make_request.side_effect = RuntimeError("Network error")

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_user_info_impl()

        assert result is None
        mock_logger.error.assert_called()


@patch('src.bot._make_api_request')
async def test_get_user_info_impl_other_status_codes(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test user info with various HTTP status codes"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter

    # Test 500 error
    mock_make_request.return_value = ({}, 500, {})

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_user_info_impl()

        assert result is None
        mock_logger.error.assert_called()

# Test urgent token refresh scenarios


async def test_check_expiring_token_urgent_refresh(bot_config):
    """Test checking expiring token when urgent refresh is needed (< 15 minutes)"""
    from datetime import datetime, timedelta
    bot = TwitchColorBot(**bot_config)
    bot.token_expiry = datetime.now() + timedelta(minutes=10)  # 10 minutes from now

    with patch.object(bot, '_attempt_standard_refresh', return_value=True) as mock_attempt:
        with patch('src.bot.print_log') as mock_print_log:
            result = await bot._check_expiring_token()

            mock_attempt.assert_called_once()
            # Should log urgent refresh message with FAIL color
            assert mock_print_log.call_count >= 1
            assert result is True

# Test exception handling in _check_expiring_token error path


async def test_validate_token_via_api_exception(bot_config):
    """Test token validation via API with exception"""
    bot = TwitchColorBot(**bot_config)

    with patch.object(bot, '_get_user_info', side_effect=RuntimeError("Network error")):
        with patch('src.bot.print_log') as mock_print_log:
            result = await bot._validate_token_via_api()

            assert result is False
            mock_print_log.assert_called_once()

# Test final missing lines for 100% coverage

# Test the exception branch in _get_current_color_impl


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_exception(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation with exception"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    mock_make_request.side_effect = RuntimeError("Network error")

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_current_color_impl()

        assert result is None
        mock_logger.warning.assert_called()

# Test API error in attempt_color_change


async def test_attempt_color_change_api_error(bot_config, mock_rate_limiter):
    """Test color change attempt with API error"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    async def mock_make_request(*args, **kwargs):
        raise APIError("Server Error", 500)

    with patch('src.bot._make_api_request', side_effect=mock_make_request):
        with patch.object(bot, '_handle_api_error', return_value=False) as mock_handle:
            result = await bot._attempt_color_change('#FF0000')

            assert result is False
            mock_handle.assert_called_once()

# Test _handle_api_error with config_file and disable success


def test_handle_api_error_with_config_disable_success(bot_config):
    """Test handling API error with successful config update"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    bot.use_random_colors = True
    bot.config_file = "/tmp/test_config.json"

    error = APIError("Turbo or Prime user required for hex colors", 400)

    with patch('src.bot.disable_random_colors_for_user', return_value=True):
        with patch('src.bot.logger') as mock_logger:
            result = bot._handle_api_error(error)

            assert result is False
            assert bot.use_random_colors is False
            mock_logger.info.assert_called()

# Test _handle_api_error with config_file and disable failure


def test_handle_api_error_with_config_disable_failure(bot_config):
    """Test handling API error with failed config update"""
    from src.error_handling import APIError

    bot = TwitchColorBot(**bot_config)
    bot.use_random_colors = True
    bot.config_file = "/tmp/test_config.json"

    error = APIError("Turbo or Prime user required for hex colors", 400)

    with patch('src.bot.disable_random_colors_for_user', return_value=False):
        with patch('src.bot.logger') as mock_logger:
            result = bot._handle_api_error(error)

            assert result is False
            assert bot.use_random_colors is False
            mock_logger.warning.assert_called()

# Test exception in _try_preset_color_fallback


async def test_try_preset_color_fallback_exception(bot_config, mock_rate_limiter):
    """Test preset color fallback with exception"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'
    bot.last_color = '#FF0000'

    with patch('src.bot.get_different_twitch_color', side_effect=RuntimeError("Test error")):
        with patch('src.bot.logger') as mock_logger:
            result = await bot._try_preset_color_fallback()

            assert result is False
            mock_logger.error.assert_called()

# Test exception in _refresh_access_token_impl


@patch('src.bot.aiohttp.ClientSession')
async def test_refresh_access_token_impl_exception(mock_session_class, bot_config):
    """Test token refresh implementation with exception"""
    bot = TwitchColorBot(**bot_config)

    mock_session_class.side_effect = RuntimeError("Network error")

    with patch('src.bot.logger') as mock_logger:
        result = await bot._refresh_access_token_impl()

        assert result is False
        mock_logger.error.assert_called()

# Test close() method (synchronous version)


def test_close_method(bot_config):
    """Test the close method"""
    bot = TwitchColorBot(**bot_config)
    mock_irc = MagicMock()
    bot.irc = mock_irc
    bot.running = True

    with patch('src.bot.print_log') as mock_print_log:
        bot.close()

        assert bot.running is False
        mock_irc.disconnect.assert_called_once()
        assert bot.irc is None  # IRC should be set to None after disconnect
        mock_print_log.assert_called_once()

# Test final 2 missing lines for 100% coverage


@patch('src.bot._make_api_request')
async def test_get_current_color_impl_api_success_but_no_color_data(
        mock_make_request, bot_config, mock_rate_limiter):
    """Test current color implementation when API succeeds but returns no color data"""
    bot = TwitchColorBot(**bot_config)
    bot.rate_limiter = mock_rate_limiter
    bot.user_id = '12345'

    # Mock response with 200 status but data that doesn't have color (e.g.,
    # empty color field)
    mock_make_request.return_value = (
        # data exists but no 'color' field
        {'data': [{'id': '12345', 'login': 'testuser'}]},
        200,
        {'Ratelimit-Remaining': '799'}
    )

    with patch('src.bot.logger') as mock_logger:
        result = await bot._get_current_color_impl()

        assert result is None
        # Should log that no current color is set (line 375)
        mock_logger.info.assert_called_with(
            "No current color set (using default)", user=bot.username)


def test_close_with_irc_sets_none(bot_config):
    """Test that close() sets self.irc to None after disconnecting"""
    bot = TwitchColorBot(**bot_config)
    mock_irc = MagicMock()
    bot.irc = mock_irc
    bot.running = True

    with patch('src.bot.print_log'):
        bot.close()

        # Verify that irc was disconnected and then set to None (line 605)
        mock_irc.disconnect.assert_called_once()
        # After close(), irc should be None
        assert bot.irc is None
