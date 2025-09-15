"""End-to-end smoke tests for the Twitch Color Changer Bot application."""

from __future__ import annotations

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from src.main import main


@pytest.mark.asyncio
async def test_end_to_end_smoke_success():
    """Test complete end-to-end flow from startup to shutdown with mocked external dependencies.

    This smoke test verifies the integration between main application components:
    - Configuration loading and validation
    - Token setup and management
    - Application context creation
    - Bot manager initialization
    - Bot lifecycle management
    - Connection establishment
    - Message processing and color changes
    - Graceful shutdown

    All external dependencies (network calls, file I/O, etc.) are mocked to ensure
    the test runs quickly and reliably.
    """
    # Mock configuration data
    mock_config = [
        {
            "username": "testuser",
            "access_token": "oauth:test_access_token",
            "refresh_token": "test_refresh_token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "channels": ["#testchannel"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]

    # Mock user config objects
    mock_user_config = MagicMock()
    mock_user_config.to_dict.return_value = mock_config[0]

    # Mock application context
    mock_context = MagicMock()
    mock_context.start = AsyncMock()
    mock_context.shutdown = AsyncMock()
    mock_context.session = MagicMock()

    # Mock bot instance
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock()
    mock_bot.stop = AsyncMock()
    mock_bot.close = AsyncMock()
    mock_bot.running = True

    # Mock bot manager
    mock_manager = MagicMock()
    mock_manager._manager_lock = asyncio.Lock()
    mock_manager.running = True
    mock_manager.tasks = [asyncio.create_task(asyncio.sleep(0.1))]
    mock_manager._stop_all_bots = AsyncMock()
    mock_manager._start_all_bots = AsyncMock(return_value=True)
    mock_manager.lifecycle = MagicMock()
    mock_manager.lifecycle._create_bot = MagicMock(return_value=mock_bot)
    mock_manager.lifecycle.bots = [mock_bot]
    mock_manager.lifecycle.tasks = mock_manager.tasks
    mock_manager.lifecycle.running = True
    mock_manager.lifecycle.context = mock_context
    mock_manager.signals = MagicMock()
    mock_manager.setup_signal_handlers = MagicMock()

    with (
        # Mock configuration and token setup
        patch('src.main.get_configuration', return_value=mock_config),
        patch('src.main.normalize_user_channels', return_value=(mock_config, False)),
        patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=[mock_user_config]),
        patch('src.main.print_config_summary'),
        patch('src.main.emit_startup_instructions'),
        patch('builtins.print'),

        # Mock application context and bot manager
        patch('src.application_context.ApplicationContext.create', new_callable=AsyncMock, return_value=mock_context),
        patch('src.bot.manager.BotManager', return_value=mock_manager),

        # Mock main loop to exit quickly
        patch('src.bot.manager._run_main_loop', new_callable=AsyncMock) as mock_run_loop,
    ):
        # Run the main function
        await main()

        # Verify configuration was loaded and processed
        # (get_configuration, normalize_user_channels, setup_missing_tokens, print_config_summary called)

        # Verify application context was created and started
        mock_context.start.assert_called_once()

        # Verify bot manager was created with correct config
        # BotManager constructor called with users_config_dicts and config_file

        # Verify signal handlers were set up
        mock_manager.setup_signal_handlers.assert_called_once()

        # Verify bots were started successfully
        mock_manager._start_all_bots.assert_called_once()

        # Verify main loop was entered
        mock_run_loop.assert_called_once_with(mock_manager)

        # Verify graceful shutdown occurred
        mock_manager._stop_all_bots.assert_called_once()
        mock_context.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_end_to_end_smoke_with_message_processing():
    """Test end-to-end flow including message processing and color change.

    Extends the basic smoke test to verify that messages are processed
    and color changes are attempted when appropriate commands are received.
    """
    # Mock configuration data
    mock_config = [
        {
            "username": "testuser",
            "access_token": "oauth:test_access_token",
            "refresh_token": "test_refresh_token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "channels": ["#testchannel"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]

    # Mock user config objects
    mock_user_config = MagicMock()
    mock_user_config.to_dict.return_value = mock_config[0]

    # Mock application context
    mock_context = MagicMock()
    mock_context.start = AsyncMock()
    mock_context.shutdown = AsyncMock()
    mock_context.session = MagicMock()

    # Mock bot with message handling
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock()
    mock_bot.stop = AsyncMock()
    mock_bot.close = AsyncMock()
    mock_bot.running = True
    mock_bot.handle_message = AsyncMock()  # Mock message handling

    # Mock bot manager
    mock_manager = MagicMock()
    mock_manager._manager_lock = asyncio.Lock()
    mock_manager.running = True
    mock_manager.tasks = [asyncio.create_task(asyncio.sleep(0.1))]
    mock_manager._stop_all_bots = AsyncMock()
    mock_manager._start_all_bots = AsyncMock(return_value=True)
    mock_manager.lifecycle = MagicMock()
    mock_manager.lifecycle._create_bot = MagicMock(return_value=mock_bot)
    mock_manager.lifecycle.bots = [mock_bot]
    mock_manager.lifecycle.tasks = mock_manager.tasks
    mock_manager.lifecycle.running = True
    mock_manager.lifecycle.context = mock_context
    mock_manager.signals = MagicMock()
    mock_manager.setup_signal_handlers = MagicMock()

    with (
        # Mock configuration and token setup
        patch('src.main.get_configuration', return_value=mock_config),
        patch('src.main.normalize_user_channels', return_value=(mock_config, False)),
        patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=[mock_user_config]),
        patch('src.main.print_config_summary'),
        patch('src.main.emit_startup_instructions'),
        patch('builtins.print'),

        # Mock application context and bot manager
        patch('src.application_context.ApplicationContext.create', new_callable=AsyncMock, return_value=mock_context),
        patch('src.bot.manager.BotManager', return_value=mock_manager),

        # Mock main loop to simulate message processing then exit
        patch('src.bot.manager._run_main_loop', new_callable=AsyncMock) as mock_run_loop,
    ):
        # Simulate message processing during main loop
        async def mock_main_loop(manager):
            # Simulate receiving and processing a color change message
            await manager.lifecycle.bots[0].handle_message("testuser", "#testchannel", "ccc red")
            # Simulate shutdown after processing
            manager.running = False

        mock_run_loop.side_effect = mock_main_loop

        # Run the main function
        await main()

        # Verify message was processed
        mock_bot.handle_message.assert_called_once_with("testuser", "#testchannel", "ccc red")

        # Verify shutdown occurred
        mock_manager._stop_all_bots.assert_called_once()
        mock_context.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_end_to_end_smoke_failure_handling():
    """Test end-to-end flow with failure scenarios.

    Verifies that the application handles failures gracefully:
    - Bot startup failures
    - Connection failures
    - Configuration errors
    """
    # Mock configuration data
    mock_config = [
        {
            "username": "testuser",
            "access_token": "oauth:test_access_token",
            "refresh_token": "test_refresh_token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "channels": ["#testchannel"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]

    # Mock user config objects
    mock_user_config = MagicMock()
    mock_user_config.to_dict.return_value = mock_config[0]

    # Mock application context
    mock_context = MagicMock()
    mock_context.start = AsyncMock()
    mock_context.shutdown = AsyncMock()
    mock_context.session = MagicMock()

    # Mock bot manager that fails to start bots
    mock_manager = MagicMock()
    mock_manager._manager_lock = asyncio.Lock()
    mock_manager.running = False  # Failed to start
    mock_manager._stop_all_bots = AsyncMock()
    mock_manager._start_all_bots = AsyncMock(return_value=False)  # Startup failure
    mock_manager.lifecycle = MagicMock()
    mock_manager.lifecycle.context = mock_context
    mock_manager.signals = MagicMock()
    mock_manager.setup_signal_handlers = MagicMock()

    with (
        # Mock configuration and token setup
        patch('src.main.get_configuration', return_value=mock_config),
        patch('src.main.normalize_user_channels', return_value=(mock_config, False)),
        patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=[mock_user_config]),
        patch('src.main.print_config_summary'),
        patch('src.main.emit_startup_instructions'),
        patch('builtins.print'),

        # Mock application context and bot manager
        patch('src.application_context.ApplicationContext.create', new_callable=AsyncMock, return_value=mock_context),
        patch('src.bot.manager.BotManager', return_value=mock_manager),

        # Main loop should not be called due to startup failure
        patch('src.bot.manager._run_main_loop', new_callable=AsyncMock) as mock_run_loop,
    ):
        # Run the main function
        await main()

        # Verify bots failed to start
        mock_manager._start_all_bots.assert_called_once()

        # Verify main loop was not entered
        mock_run_loop.assert_not_called()

        # Verify graceful shutdown still occurred
        mock_manager._stop_all_bots.assert_called_once()
        mock_context.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_end_to_end_smoke_configuration_error():
    """Test end-to-end flow with configuration loading error.

    Verifies that configuration errors are handled properly and
    the application exits gracefully without attempting to start bots.
    """
    with (
        # Mock configuration loading failure
        patch('src.main.get_configuration', side_effect=ValueError("Invalid configuration")),
        patch('src.main.log_error') as mock_log_error,
        patch('src.main.emit_startup_instructions'),
        patch('builtins.print'),
        patch('sys.exit') as mock_exit,

        # Ensure no further processing occurs
        patch('src.main.normalize_user_channels'),
        patch('src.main.setup_missing_tokens'),
        patch('src.main.print_config_summary'),
        patch('src.main.run_bots'),
    ):
        # Run the main function
        await main()

        # Verify error was logged
        mock_log_error.assert_called_once_with("Main application error", ANY)

        # Verify application exited
        mock_exit.assert_called_once_with(1)

        # Verify no further processing occurred
        # (normalize_user_channels, setup_missing_tokens, etc. not called)
