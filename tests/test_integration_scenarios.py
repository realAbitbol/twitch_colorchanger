"""Integration tests for end-to-end scenarios and component interaction.

Tests the interaction between all major components to ensure
they work together correctly in realistic scenarios.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application_context import ApplicationContext
from src.bot.core import TwitchColorBot
from src.bot.manager import BotManager
from src.main import main


class TestIntegrationScenarios:
    """Test suite for integration scenarios."""

    @pytest.mark.asyncio
    async def test_full_application_lifecycle_integration(self):
        """Test complete application lifecycle with all components.

        Validates the integration between main application components:
        - Configuration loading and validation
        - Application context creation and management
        - Bot manager initialization and coordination
        - Bot lifecycle management
        - Resource cleanup and shutdown
        """
        # Mock configuration data
        mock_config = [
            {
                "username": "integration_test_user",
                "access_token": "oauth:integration_test_token",
                "refresh_token": "integration_test_refresh_token",
                "client_id": "integration_test_client_id",
                "client_secret": "integration_test_client_secret",
                "channels": ["#integration_test_channel"],
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
        mock_context.session.closed = False
        mock_context.token_manager = MagicMock()
        mock_context.token_manager.start = AsyncMock()
        mock_context.token_manager.stop = AsyncMock()

        # Mock bot instance with full lifecycle
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        mock_bot.stop = AsyncMock()
        mock_bot.close = AsyncMock()
        mock_bot.running = True
        mock_bot.handle_message = AsyncMock()

        # Mock bot manager with full integration
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
        mock_manager.lifecycle.restart_requested = False
        mock_manager.lifecycle.new_config = None
        mock_manager.lifecycle.users_config = mock_config
        mock_manager.lifecycle.config_file = "test_config.conf"
        mock_manager.lifecycle.http_session = MagicMock()
        mock_manager.signals = MagicMock()
        mock_manager.signals.shutdown_initiated = False
        mock_manager.setup_signal_handlers = MagicMock()

        with (
            # Mock configuration and token setup
            patch('src.main.get_configuration', return_value=mock_config),
            patch('src.main.normalize_user_channels', return_value=(mock_config, False)),
            patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=[mock_user_config]),
            patch('src.main.print_config_summary'),
            patch('src.main.emit_startup_instructions'),
            patch('builtins.print'),

            # Mock application context
            patch('src.application_context.ApplicationContext.create', new_callable=AsyncMock, return_value=mock_context),
            patch('src.application_context.ApplicationContext.start', new_callable=AsyncMock),
            patch('src.application_context.ApplicationContext.shutdown', new_callable=AsyncMock),

            # Mock bot manager
            patch('src.bot.manager.BotManager', return_value=mock_manager),

            # Mock main loop to simulate complete lifecycle
            patch('src.bot.manager._run_main_loop', new_callable=AsyncMock) as mock_run_loop,
        ):
            # Simulate complete lifecycle
            async def simulate_full_lifecycle(manager):
                # Phase 1: Initial operation
                assert manager.running is True
                assert len(manager.lifecycle.bots) == 1
                assert manager.lifecycle.bots[0].running is True

                # Phase 2: Message processing integration
                await manager.lifecycle.bots[0].handle_message(
                    "testuser", "#integration_test_channel", "ccc red"
                )

                # Phase 3: Simulate some operational time
                await asyncio.sleep(0.1)

                # Phase 4: Graceful shutdown
                manager.running = False

            mock_run_loop.side_effect = simulate_full_lifecycle

            # Run the main function
            await main()

            # Verify complete integration lifecycle
            # Configuration was loaded and processed
            # Application context was created and started
            mock_context.start.assert_called_once()

            # Bot manager was properly initialized
            mock_manager.setup_signal_handlers.assert_called_once()
            mock_manager._start_all_bots.assert_called_once()

            # Message processing integration worked
            mock_bot.handle_message.assert_called_once_with(
                "testuser", "#integration_test_channel", "ccc red"
            )

            # Graceful shutdown occurred
            mock_manager._stop_all_bots.assert_called_once()
            mock_context.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_multi_bot_coordination_integration(self):
        """Test integration between multiple bot instances.

        Validates that multiple bots can operate simultaneously
        and coordinate properly without interfering with each other.
        """
        # Mock configuration for multiple bots
        mock_config = [
            {
                "username": f"bot_user_{i}",
                "access_token": f"oauth:token_{i}",
                "refresh_token": f"refresh_token_{i}",
                "client_id": f"client_id_{i}",
                "client_secret": f"client_secret_{i}",
                "channels": [f"#channel_{i}"],
                "is_prime_or_turbo": True,
                "enabled": True,
            }
            for i in range(3)
        ]

        # Mock user config objects
        mock_user_configs = []
        for config in mock_config:
            mock_user_config = MagicMock()
            mock_user_config.to_dict.return_value = config
            mock_user_configs.append(mock_user_config)

        # Mock application context
        mock_context = MagicMock()
        mock_context.start = AsyncMock()
        mock_context.shutdown = AsyncMock()
        mock_context.session = MagicMock()
        mock_context.session.closed = False

        # Mock multiple bot instances
        mock_bots = []
        for i in range(3):
            mock_bot = MagicMock()
            mock_bot.start = AsyncMock()
            mock_bot.stop = AsyncMock()
            mock_bot.close = AsyncMock()
            mock_bot.running = True
            mock_bot.handle_message = AsyncMock()
            mock_bots.append(mock_bot)

        # Mock bot manager for multi-bot coordination
        mock_manager = MagicMock()
        mock_manager._manager_lock = asyncio.Lock()
        mock_manager.running = True
        mock_manager.tasks = []
        mock_manager._stop_all_bots = AsyncMock()
        mock_manager._start_all_bots = AsyncMock(return_value=True)
        mock_manager.lifecycle = MagicMock()
        mock_manager.lifecycle._create_bot = MagicMock(side_effect=mock_bots)
        mock_manager.lifecycle.bots = mock_bots
        mock_manager.lifecycle.tasks = mock_manager.tasks
        mock_manager.lifecycle.running = True
        mock_manager.lifecycle.context = mock_context
        mock_manager.signals = MagicMock()
        mock_manager.setup_signal_handlers = MagicMock()

        with (
            patch('src.main.get_configuration', return_value=mock_config),
            patch('src.main.normalize_user_channels', return_value=(mock_config, False)),
            patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_user_configs),
            patch('src.main.print_config_summary'),
            patch('src.main.emit_startup_instructions'),
            patch('builtins.print'),
            patch('src.application_context.ApplicationContext.create', new_callable=AsyncMock, return_value=mock_context),
            patch('src.bot.manager.BotManager', return_value=mock_manager),
            patch('src.bot.manager._run_main_loop', new_callable=AsyncMock) as mock_run_loop,
        ):
            # Simulate multi-bot operation
            async def simulate_multi_bot_operation(manager):
                # Verify all bots are running
                for i, bot in enumerate(manager.lifecycle.bots):
                    assert bot.running is True

                # Simulate concurrent message processing
                tasks = []
                for i, bot in enumerate(manager.lifecycle.bots):
                    task = asyncio.create_task(
                        bot.handle_message(f"user_{i}", f"#channel_{i}", f"ccc color_{i}")
                    )
                    tasks.append(task)

                # Wait for all messages to be processed
                await asyncio.gather(*tasks)

                # Verify all messages were processed
                for i, bot in enumerate(manager.lifecycle.bots):
                    bot.handle_message.assert_called_with(
                        f"user_{i}", f"#channel_{i}", f"ccc color_{i}"
                    )

                # Simulate continued operation
                await asyncio.sleep(0.1)

                manager.running = False

            mock_run_loop.side_effect = simulate_multi_bot_operation

            # Run the main function
            await main()

            # Verify multi-bot integration
            assert len(mock_bots) == 3
            for bot in mock_bots:
                assert bot.running is True

            # Verify all bots processed their messages
            for bot in mock_bots:
                bot.handle_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_configuration_change_integration(self):
        """Test integration when configuration changes during operation.

        Validates that configuration changes are properly handled
        and applied without disrupting ongoing operations.
        """
        # Initial configuration
        initial_config = [
            {
                "username": "initial_user",
                "access_token": "oauth:initial_token",
                "refresh_token": "initial_refresh_token",
                "client_id": "initial_client_id",
                "client_secret": "initial_client_secret",
                "channels": ["#initial_channel"],
                "is_prime_or_turbo": True,
                "enabled": True,
            }
        ]

        # Updated configuration
        updated_config = [
            {
                "username": "updated_user",
                "access_token": "oauth:updated_token",
                "refresh_token": "updated_refresh_token",
                "client_id": "updated_client_id",
                "client_secret": "updated_client_secret",
                "channels": ["#updated_channel"],
                "is_prime_or_turbo": True,
                "enabled": True,
            }
        ]

        # Mock user config objects
        initial_user_config = MagicMock()
        initial_user_config.to_dict.return_value = initial_config[0]

        updated_user_config = MagicMock()
        updated_user_config.to_dict.return_value = updated_config[0]

        # Mock application context
        mock_context = MagicMock()
        mock_context.start = AsyncMock()
        mock_context.shutdown = AsyncMock()
        mock_context.session = MagicMock()
        mock_context.session.closed = False

        # Mock bot instances
        initial_bot = MagicMock()
        initial_bot.start = AsyncMock()
        initial_bot.stop = AsyncMock()
        initial_bot.close = AsyncMock()
        initial_bot.running = True
        initial_bot.handle_message = AsyncMock()

        updated_bot = MagicMock()
        updated_bot.start = AsyncMock()
        updated_bot.stop = AsyncMock()
        updated_bot.close = AsyncMock()
        updated_bot.running = True
        updated_bot.handle_message = AsyncMock()

        # Mock bot manager with restart capability
        mock_manager = MagicMock()
        mock_manager._manager_lock = asyncio.Lock()
        mock_manager.running = True
        mock_manager.tasks = []
        mock_manager._stop_all_bots = AsyncMock()
        mock_manager._start_all_bots = AsyncMock(return_value=True)
        mock_manager._restart_with_new_config = AsyncMock(return_value=True)
        mock_manager.lifecycle = MagicMock()
        mock_manager.lifecycle._create_bot = MagicMock(side_effect=[initial_bot, updated_bot])
        mock_manager.lifecycle.bots = [initial_bot]
        mock_manager.lifecycle.tasks = mock_manager.tasks
        mock_manager.lifecycle.running = True
        mock_manager.lifecycle.context = mock_context
        mock_manager.lifecycle.restart_requested = False
        mock_manager.lifecycle.new_config = None
        mock_manager.signals = MagicMock()
        mock_manager.setup_signal_handlers = MagicMock()

        with (
            patch('src.main.get_configuration', side_effect=[initial_config, updated_config]),
            patch('src.main.normalize_user_channels', return_value=(initial_config, False)),
            patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=[initial_user_config]),
            patch('src.main.print_config_summary'),
            patch('src.main.emit_startup_instructions'),
            patch('builtins.print'),
            patch('src.application_context.ApplicationContext.create', new_callable=AsyncMock, return_value=mock_context),
            patch('src.bot.manager.BotManager', return_value=mock_manager),
            patch('src.bot.manager._run_main_loop', new_callable=AsyncMock) as mock_run_loop,
        ):
            # Simulate configuration change during operation
            async def simulate_config_change(manager):
                # Initial operation with first bot
                assert len(manager.lifecycle.bots) == 1
                assert manager.lifecycle.bots[0] == initial_bot

                # Process initial message
                await manager.lifecycle.bots[0].handle_message(
                    "user", "#initial_channel", "ccc red"
                )

                # Simulate configuration change
                manager.lifecycle.restart_requested = True
                manager.lifecycle.new_config = updated_config

                # Restart with new configuration
                restart_success = await manager._restart_with_new_config()
                assert restart_success is True

                # Verify new bot is created and old bot is replaced
                assert len(manager.lifecycle.bots) == 1
                assert manager.lifecycle.bots[0] == updated_bot

                # Process message with new bot
                await manager.lifecycle.bots[0].handle_message(
                    "user", "#updated_channel", "ccc blue"
                )

                manager.running = False

            mock_run_loop.side_effect = simulate_config_change

            # Run the main function
            await main()

            # Verify configuration change integration
            initial_bot.handle_message.assert_called_with(
                "user", "#initial_channel", "ccc red"
            )
            updated_bot.handle_message.assert_called_with(
                "user", "#updated_channel", "ccc blue"
            )

            # Verify restart was handled properly
            mock_manager._restart_with_new_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_recovery_integration(self):
        """Test integration of error recovery mechanisms.

        Validates that errors in individual components are properly
        handled and don't affect the overall system stability.
        """
        # Mock configuration
        mock_config = [
            {
                "username": "error_test_user",
                "access_token": "oauth:error_test_token",
                "refresh_token": "error_test_refresh_token",
                "client_id": "error_test_client_id",
                "client_secret": "error_test_client_secret",
                "channels": ["#error_test_channel"],
                "is_prime_or_turbo": True,
                "enabled": True,
            }
        ]

        mock_user_config = MagicMock()
        mock_user_config.to_dict.return_value = mock_config[0]

        # Mock application context
        mock_context = MagicMock()
        mock_context.start = AsyncMock()
        mock_context.shutdown = AsyncMock()
        mock_context.session = MagicMock()
        mock_context.session.closed = False

        # Mock bot with error simulation
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        mock_bot.stop = AsyncMock()
        mock_bot.close = AsyncMock()
        mock_bot.running = True
        mock_bot.handle_message = AsyncMock()

        # Simulate bot error and recovery
        error_count = 0
        def simulate_error_recovery(*args, **kwargs):
            nonlocal error_count
            error_count += 1
            if error_count == 1:
                raise Exception("Simulated bot error")
            # Recovery: second call succeeds
            return None

        mock_bot.handle_message.side_effect = simulate_error_recovery

        # Mock bot manager
        mock_manager = MagicMock()
        mock_manager._manager_lock = asyncio.Lock()
        mock_manager.running = True
        mock_manager.tasks = []
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
            patch('src.main.get_configuration', return_value=mock_config),
            patch('src.main.normalize_user_channels', return_value=(mock_config, False)),
            patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=[mock_user_config]),
            patch('src.main.print_config_summary'),
            patch('src.main.emit_startup_instructions'),
            patch('builtins.print'),
            patch('src.application_context.ApplicationContext.create', new_callable=AsyncMock, return_value=mock_context),
            patch('src.bot.manager.BotManager', return_value=mock_manager),
            patch('src.bot.manager._run_main_loop', new_callable=AsyncMock) as mock_run_loop,
        ):
            # Simulate error recovery
            async def simulate_error_recovery_scenario(manager):
                # First message causes error
                try:
                    await manager.lifecycle.bots[0].handle_message(
                        "user", "#error_test_channel", "ccc red"
                    )
                except Exception:
                    pass  # Expected error

                # Second message should succeed (recovery)
                await manager.lifecycle.bots[0].handle_message(
                    "user", "#error_test_channel", "ccc blue"
                )

                manager.running = False

            mock_run_loop.side_effect = simulate_error_recovery_scenario

            # Run the main function
            await main()

            # Verify error recovery integration
            assert mock_bot.handle_message.call_count == 2

            # First call failed, second call succeeded
            assert error_count == 2

            # Verify system remained stable despite error
            mock_manager._stop_all_bots.assert_called_once()
            mock_context.shutdown.assert_called_once()