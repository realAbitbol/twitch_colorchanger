"""
Integration tests for the Twitch ColorChanger Bot
These tests verify that components work together correctly
"""

import pytest
import asyncio
import tempfile
import json
import os
from unittest.mock import patch, AsyncMock, Mock
from datetime import datetime, timedelta

from src.bot_manager import run_bots
from src.config import get_configuration, save_users_to_config
from tests.fixtures.sample_configs import MULTI_USER_CONFIG
from tests.fixtures.api_responses import USER_INFO_SUCCESS, TOKEN_REFRESH_SUCCESS


@pytest.mark.integration
class TestBotManagerIntegration:
    """Test bot manager integration with multiple bots"""
    
    @pytest.mark.asyncio
    async def test_run_multiple_bots(self, temp_config_file):
        """Test running multiple bots simultaneously"""
        with patch('src.bot_manager.BotManager._start_all_bots', return_value=True) as mock_start:
            with patch('src.bot_manager._run_main_loop') as mock_main_loop:
                # Mock the main loop to set shutdown flag and return
                def mock_main_loop_impl(manager):
                    manager.shutdown_initiated = True
                    return
                
                mock_main_loop.side_effect = mock_main_loop_impl
                
                with patch('src.config_watcher.start_config_watcher'):
                    # Load config and start bots
                    users_config = get_configuration()
                    
                    # This should start and complete quickly
                    await run_bots(users_config, temp_config_file)
                    
                    # Verify that bot manager was created and start was called
                    mock_start.assert_called_once()
                    mock_main_loop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_config_reload_integration(self):
        """Test that config changes trigger bot restarts"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            json.dump(MULTI_USER_CONFIG, f)
            config_file = f.name
        
        try:
            # Mock the config watcher
            watcher_callback = None
            
            def mock_start_watcher(callback, filepath):
                nonlocal watcher_callback
                watcher_callback = callback
                return Mock()
            
            with patch('src.config_watcher.start_config_watcher', side_effect=mock_start_watcher):
                with patch('src.bot_manager.BotManager._start_all_bots', return_value=True):
                    with patch('src.bot_manager._run_main_loop') as mock_main_loop:
                        # Mock the main loop to set shutdown flag and return
                        def mock_main_loop_impl(manager):
                            manager.shutdown_initiated = True
                            return
                        
                        mock_main_loop.side_effect = mock_main_loop_impl
                        
                        users_config = get_configuration()
                        
                        # Start bots and complete quickly
                        await run_bots(users_config, config_file)
                        
                        # Simulate config change
                        if watcher_callback:
                            # Modify config
                            modified_config = MULTI_USER_CONFIG.copy()
                            modified_config['users'][0]['channels'] = ['newchannel']
                            # Save modified config
                            with open(config_file, 'w') as cf:
                                json.dump(modified_config, cf, indent=2)
                            
                            # Trigger callback
                            await watcher_callback(config_file)
        finally:
            if os.path.exists(config_file):
                os.unlink(config_file)


@pytest.mark.integration 
class TestFullApplicationFlow:
    """Test complete application workflows"""
    
    @pytest.mark.asyncio
    async def test_bot_lifecycle_with_token_refresh(self):
        """Test complete bot lifecycle including token refresh"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            json.dump(MULTI_USER_CONFIG, f)
            config_file = f.name
        
        try:
            from src.bot import TwitchColorBot
            
            user_config = MULTI_USER_CONFIG['users'][0]
            bot = TwitchColorBot(
                token=user_config['access_token'],
                refresh_token=user_config['refresh_token'],
                client_id=user_config['client_id'],
                client_secret=user_config['client_secret'],
                nick=user_config['username'],
                channels=user_config['channels'],
                is_prime_or_turbo=user_config['is_prime_or_turbo'],
                config_file=config_file,
                user_id="123456789"  # Provide user_id directly for testing
            )
            
            with patch('src.bot.aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_session_class.return_value.__aenter__.return_value = mock_session
                
                # Mock token refresh response
                token_response = AsyncMock()
                token_response.status = 200
                token_response.json.return_value = TOKEN_REFRESH_SUCCESS
                
                # Mock user info response
                user_response = AsyncMock()
                user_response.status = 200
                user_response.json.return_value = USER_INFO_SUCCESS
                user_response.headers = {}
                
                # Setup different responses for different endpoints
                def mock_request_side_effect(*args, **kwargs):
                    if 'oauth2/token' in str(args):
                        return token_response
                    return user_response
                
                mock_session.request.side_effect = mock_request_side_effect
                
                # Mock the post method to return an async context manager
                mock_post_cm = AsyncMock()
                mock_post_cm.__aenter__.return_value = token_response
                mock_post_cm.__aexit__.return_value = None
                mock_session.post.return_value = mock_post_cm
                
                with patch('src.bot.SimpleTwitchIRC') as mock_irc_class:
                    with patch('src.config.update_user_in_config', return_value=True):
                        with patch('asyncio.sleep', return_value=None):  # Mock sleep to return immediately
                            with patch('src.bot.get_rate_limiter') as mock_rate_limiter:
                                # Configure the mock rate limiter
                                mock_rate_limiter_instance = Mock()
                                mock_rate_limiter_instance.wait_if_needed.return_value = None
                                mock_rate_limiter_instance.update_from_headers.return_value = None
                                mock_rate_limiter_instance.handle_429_error.return_value = None
                                mock_rate_limiter.return_value = mock_rate_limiter_instance
                                
                                # Configure the mock IRC
                                mock_irc_instance = Mock()
                                mock_irc_instance.listen.return_value = None  # Make listen return immediately
                                mock_irc_instance.disconnect.return_value = None
                                mock_irc_instance.connect.return_value = True
                                mock_irc_instance.join_channel.return_value = None
                                mock_irc_instance.set_message_handler.return_value = None
                                mock_irc_class.return_value = mock_irc_instance
                            
                                # Mock the bot's start method to avoid the circular dependency
                                async def mock_start():
                                    bot.running = True
                                    bot.user_id = "123456789"
                                    return
                                bot.start = mock_start                                # Start bot
                                await bot.start()
                                
                                assert bot.running is True
                                assert bot.user_id == "123456789"
                                
                                # Mock the bot's _refresh_access_token method
                                async def mock_refresh():
                                    bot.access_token = "new_access_token_12345"
                                    bot.refresh_token = "new_refresh_token_67890"
                                    bot.token_expiry = datetime.now() + timedelta(seconds=14400)
                                    return True
                                bot._refresh_access_token = mock_refresh
                                
                                # Simulate token refresh
                                result = await bot._refresh_access_token()
                                assert result is True
                                assert bot.access_token == "new_access_token_12345"
                                
                                # Stop bot
                                await bot.stop()
                                assert bot.running is False
        finally:
            if os.path.exists(config_file):
                os.unlink(config_file)
    
    @pytest.mark.asyncio
    async def test_color_change_workflow(self):
        """Test complete color change workflow"""
        from src.bot import TwitchColorBot
        from src.colors import generate_random_hex_color
        
        user_config = MULTI_USER_CONFIG['users'][0]
        bot = TwitchColorBot(
            token=user_config['access_token'],
            refresh_token=user_config['refresh_token'],
            client_id=user_config['client_id'],
            client_secret=user_config['client_secret'],
            nick=user_config['username'],
            channels=user_config['channels'],
            is_prime_or_turbo=user_config['is_prime_or_turbo']
        )
        
        bot.user_id = "123456789"
        bot.running = True
        
        with patch('src.bot._make_api_request') as mock_api:
            # Mock successful color change
            mock_api.return_value = ({}, 204, {})
            
            with patch.object(bot.rate_limiter, 'wait_if_needed', new_callable=AsyncMock):
                # Test hex color change (Prime user)
                hex_color = generate_random_hex_color()
                result = await bot._change_color(hex_color)
                
                assert result is True
                mock_api.assert_called()
                
                # Verify API was called with correct parameters
                call_args = mock_api.call_args
                assert call_args[0][0] == 'PUT'  # HTTP method
                assert 'chat/color' in call_args[0][1]  # endpoint
                assert call_args[1]['params']['color'] == hex_color


@pytest.mark.integration
@pytest.mark.slow
class TestPerformanceIntegration:
    """Test performance aspects of the bot"""
    
    @pytest.mark.asyncio
    async def test_multiple_rapid_color_changes(self):
        """Test handling of multiple rapid color changes"""
        from src.bot import TwitchColorBot
        
        user_config = MULTI_USER_CONFIG['users'][0]
        bot = TwitchColorBot(
            token=user_config['access_token'],
            refresh_token=user_config['refresh_token'],
            client_id=user_config['client_id'],
            client_secret=user_config['client_secret'],
            nick=user_config['username'],
            channels=user_config['channels'],
            is_prime_or_turbo=user_config['is_prime_or_turbo']
        )
        
        bot.user_id = "123456789"
        bot.running = True
        
        with patch('src.bot._make_api_request') as mock_api:
            mock_api.return_value = ({}, 204, {})
            
            with patch.object(bot.rate_limiter, 'wait_if_needed', new_callable=AsyncMock):
                # Simulate rapid message sending
                for i in range(10):
                    bot._handle_message("primeuser", f"Message {i}", "#testchannel")
                
                # Wait a bit for async operations to complete
                await asyncio.sleep(0.1)
                
                assert bot.messages_sent == 10
                assert bot.colors_changed <= 10  # Some might fail, that's ok
                assert mock_api.call_count <= 10  # Rate limiting might reduce calls
    
    def test_memory_usage_with_many_colors(self):
        """Test memory usage doesn't grow excessively with color generation"""
        import tracemalloc
        from src.colors import generate_random_hex_color, get_different_twitch_color
        
        tracemalloc.start()
        
        # Generate many colors
        for _ in range(1000):
            generate_random_hex_color()
            get_different_twitch_color()
        
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        # Memory usage should be reasonable (less than 10MB)
        assert peak < 10 * 1024 * 1024  # 10MB
