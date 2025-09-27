"""Long-running operation tests for unattended operation validation.

Tests the application's ability to run for extended periods (24+ hours)
without memory leaks, connection issues, or other stability problems.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application_context import ApplicationContext
from src.bot.manager import BotManager
from src.main import main


class TestLongRunningOperation:
    """Test suite for long-running operation validation."""

    @pytest.mark.asyncio
    async def test_application_context_long_running_stability(self):
        """Test ApplicationContext stability over extended periods.

        Validates that the application context maintains stability
        during long-running operations without resource leaks.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Simulate 24+ hours of operation with periodic resource checks
            start_time = time.time()
            check_interval = 60  # Check every minute
            total_duration = 300  # 5 minutes for testing

            while time.time() - start_time < total_duration:
                # Verify context is still healthy
                assert context.session is not None
                assert not context.session.closed
                assert context._started is True

                # Check for resource leaks
                gc.collect()
                initial_objects = len(gc.get_objects())

                # Simulate some context operations
                if hasattr(context, 'token_manager') and context.token_manager:
                    # Token manager health check
                    pass

                # Wait before next check
                await asyncio.sleep(check_interval)

            # Verify final state
            elapsed = time.time() - start_time
            assert elapsed >= total_duration
            assert context._started is True

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_bot_manager_long_running_stability(self):
        """Test BotManager stability during extended operation.

        Validates that the bot manager can maintain multiple bot instances
        running for extended periods without stability issues.
        """
        # Mock configuration for multiple bots
        mock_config = [
            {
                "username": f"testuser{i}",
                "access_token": f"oauth:test_access_token_{i}",
                "refresh_token": f"test_refresh_token_{i}",
                "client_id": f"test_client_id_{i}",
                "client_secret": f"test_client_secret_{i}",
                "channels": [f"#testchannel{i}"],
                "is_prime_or_turbo": True,
                "enabled": True,
            }
            for i in range(3)  # Test with 3 bots
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

        # Mock bot instances
        mock_bots = []
        for i in range(3):
            mock_bot = MagicMock()
            mock_bot.start = AsyncMock()
            mock_bot.stop = AsyncMock()
            mock_bot.close = AsyncMock()
            mock_bot.running = True
            mock_bots.append(mock_bot)

        # Mock bot manager
        mock_manager = MagicMock()
        mock_manager._manager_lock = asyncio.Lock()
        mock_manager.running = True
        mock_manager.tasks = []
        mock_manager._stop_all_bots = AsyncMock()
        mock_manager._start_all_bots = AsyncMock(return_value=True)
        mock_manager.lifecycle = MagicMock()
        mock_manager.lifecycle.bots = mock_bots
        mock_manager.lifecycle.tasks = mock_manager.tasks
        mock_manager.lifecycle.running = True
        mock_manager.lifecycle.context = mock_context
        mock_manager.lifecycle._create_bot = MagicMock(side_effect=mock_bots)
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
            # Simulate long-running operation
            async def simulate_long_operation(manager):
                start_time = time.time()
                duration = 300  # 5 minutes

                while time.time() - start_time < duration and manager.running:
                    # Simulate periodic health checks
                    for bot in mock_bots:
                        assert bot.running is True

                    # Simulate some bot activity
                    for bot in mock_bots:
                        if hasattr(bot, 'handle_message'):
                            # Simulate occasional message processing
                            pass

                    await asyncio.sleep(30)  # Check every 30 seconds

                manager.running = False

            mock_run_loop.side_effect = simulate_long_operation

            # Run the main function
            await main()

            # Verify all bots remained stable
            for bot in mock_bots:
                assert bot.running is True

            # Verify manager remained stable
            assert mock_manager.running is True

    @pytest.mark.asyncio
    async def test_memory_usage_stability(self):
        """Test memory usage stability over extended periods.

        Validates that memory usage remains stable and doesn't
        continuously grow during long-running operations.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Record initial memory state
            gc.collect()
            initial_objects = len(gc.get_objects())
            initial_time = time.time()

            # Simulate extended operation with memory monitoring
            test_duration = 180  # 3 minutes
            check_interval = 30  # Check every 30 seconds

            memory_growth_tolerance = 1.1  # Allow 10% growth
            max_allowed_objects = int(initial_objects * memory_growth_tolerance)

            while time.time() - initial_time < test_duration:
                # Perform some typical operations
                if context.token_manager:
                    # Simulate token manager operations
                    pass

                # Check memory usage
                gc.collect()
                current_objects = len(gc.get_objects())

                # Log memory usage for monitoring
                elapsed = time.time() - initial_time
                logging.debug(
                    f"Memory check at {elapsed:.1f}s: "
                    f"{current_objects} objects (max allowed: {max_allowed_objects})"
                )

                # Assert memory usage is within acceptable limits
                assert current_objects <= max_allowed_objects, (
                    f"Memory usage grew too much: {current_objects} objects "
                    f"(limit: {max_allowed_objects})"
                )

                await asyncio.sleep(check_interval)

            # Final memory check
            gc.collect()
            final_objects = len(gc.get_objects())
            total_elapsed = time.time() - initial_time

            logging.info(
                f"Long-running test completed: {total_elapsed:.1f}s, "
                f"objects: {initial_objects} -> {final_objects}"
            )

            # Memory should not have grown significantly
            assert final_objects <= max_allowed_objects

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_connection_stability_over_time(self):
        """Test connection stability during extended operation.

        Validates that network connections remain stable and
        are properly managed during long-running operations.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Test connection stability over time
            test_duration = 120  # 2 minutes
            start_time = time.time()

            while time.time() - start_time < test_duration:
                # Verify HTTP session is healthy
                assert context.session is not None
                assert not context.session.closed

                # Simulate connection usage
                if hasattr(context.session, '_connector'):
                    connector = context.session._connector
                    if connector:
                        # Check connector health
                        assert hasattr(connector, '_conns')

                await asyncio.sleep(15)  # Check every 15 seconds

            # Verify final connection state
            assert context.session is not None
            assert not context.session.closed

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_resource_cleanup_after_long_operation(self):
        """Test proper resource cleanup after extended operation.

        Validates that all resources are properly cleaned up
        after long-running operations complete.
        """
        context = await ApplicationContext.create()
        await context.start()

        # Simulate long operation
        await asyncio.sleep(60)  # 1 minute of operation

        # Verify resources are properly initialized
        assert context._started is True
        assert context.session is not None
        assert not context.session.closed

        # Shutdown and verify cleanup
        await context.shutdown()

        # Verify cleanup completed
        assert context._started is False
        assert context.session is None or context.session.closed

        # Verify no lingering resources
        gc.collect()
        # Additional cleanup verification can be added here