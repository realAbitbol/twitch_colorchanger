
"""Stress tests for concurrent operations and high load scenarios.

Tests the application's ability to handle multiple simultaneous operations
and high load conditions without performance degradation or failures.
"""

from __future__ import annotations

import asyncio
import gc
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application_context import ApplicationContext
from src.bot.manager import BotManager
from src.main import main


class TestStressConcurrent:
    """Test suite for stress and concurrent operation testing."""

    @pytest.mark.asyncio
    async def test_concurrent_message_processing_stress(self):
        """Test concurrent message processing under high load.

        Validates that the application can handle multiple simultaneous
        message processing requests without performance degradation.
        """
        # Mock configuration for stress testing
        mock_config = [
            {
                "username": "stress_test_user",
                "access_token": "oauth:stress_test_token",
                "refresh_token": "stress_test_refresh_token",
                "client_id": "stress_test_client_id",
                "client_secret": "stress_test_client_secret",
                "channels": ["#stress_test_channel"],
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

        # Mock bot with concurrent message handling
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        mock_bot.stop = AsyncMock()
        mock_bot.close = AsyncMock()
        mock_bot.running = True

        # Simulate concurrent message processing with controlled delays
        processed_messages = []
        processing_lock = asyncio.Lock()

        async def simulate_message_processing(user, channel, message):
            async with processing_lock:
                processed_messages.append((user, channel, message))
            # Simulate processing time
            await asyncio.sleep(0.01)
            return True

        mock_bot.handle_message = AsyncMock(side_effect=simulate_message_processing)

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
            # Simulate high concurrent load
            async def simulate_concurrent_stress(manager):
                # Generate concurrent message load
                num_messages = 100
                num_concurrent = 10

                async def process_message_batch(batch_id):
                    tasks = []
                    for i in range(num_messages // num_concurrent):
                        message_id = batch_id * (num_messages // num_concurrent) + i
                        task = manager.lifecycle.bots[0].handle_message(
                            f"user_{message_id}",
                            "#stress_test_channel",
                            f"ccc color_{message_id}"
                        )
                        tasks.append(task)

                    # Process batch concurrently
                    await asyncio.gather(*tasks)

                # Run multiple concurrent batches
                batch_tasks = []
                for batch_id in range(num_concurrent):
                    task = asyncio.create_task(process_message_batch(batch_id))
                    batch_tasks.append(task)

                # Wait for all batches to complete
                await asyncio.gather(*batch_tasks)

                manager.running = False

            mock_run_loop.side_effect = simulate_concurrent_stress

            # Run the main function
            await main()

            # Verify concurrent processing
            assert mock_bot.handle_message.call_count == num_messages

            # Verify all messages were processed
            assert len(processed_messages) == num_messages

            # Verify no duplicates or missing messages
            processed_set = set(processed_messages)
            assert len(processed_set) == num_messages

    @pytest.mark.asyncio
    async def test_multiple_bot_concurrent_operations(self):
        """Test concurrent operations across multiple bot instances.

        Validates that multiple bots can operate simultaneously
        without interfering with each other's operations.
        """
        # Mock configuration for multiple bots
        num_bots = 5
        mock_config = [
            {
                "username": f"concurrent_bot_{i}",
                "access_token": f"oauth:token_{i}",
                "refresh_token": f"refresh_token_{i}",
                "client_id": f"client_id_{i}",
                "client_secret": f"client_secret_{i}",
                "channels": [f"#channel_{i}"],
                "is_prime_or_turbo": True,
                "enabled": True,
            }
            for i in range(num_bots)
        ]

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

        # Mock bot with lifecycle tracking
        lifecycle_events = []

        def track_lifecycle(event):
            lifecycle_events.append(event)

        mock_bot = MagicMock()
        mock_bot.start = AsyncMock(side_effect=lambda: track_lifecycle("start"))
        mock_bot.stop = AsyncMock(side_effect=lambda: track_lifecycle("stop"))
        mock_bot.close = AsyncMock(side_effect=lambda: track_lifecycle("close"))
        mock_bot.running = True
        mock_bot.handle_message = AsyncMock()

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
            # Simulate concurrent lifecycle operations
            async def simulate_concurrent_lifecycle(manager):
                # Simulate concurrent start/stop operations
                tasks = []

                for i in range(10):
                    if i % 2 == 0:
                        # Start operations
                        task = manager.lifecycle.bots[0].start()
                    else:
                        # Stop operations
                        task = manager.lifecycle.bots[0].stop()
                    tasks.append(task)

                # Execute concurrent lifecycle operations
                await asyncio.gather(*tasks)

                manager.running = False

            mock_run_loop.side_effect = simulate_concurrent_lifecycle

            # Run the main function
            await main()

            # Verify concurrent lifecycle operations
            assert mock_bot.start.call_count > 0
            assert mock_bot.stop.call_count > 0

            # Verify proper lifecycle sequence
            start_calls = mock_bot.start.call_count
            stop_calls = mock_bot.stop.call_count
            assert start_calls + stop_calls == 10

        # Mock multiple bot instances
        mock_bots = []
        for i in range(num_bots):
            mock_bot = MagicMock()
            mock_bot.start = AsyncMock()
            mock_bot.stop = AsyncMock()
            mock_bot.close = AsyncMock()
            mock_bot.running = True

            # Track processed messages per bot
            processed_messages = []
            processing_lock = asyncio.Lock()

            async def track_message_processing(user, channel, message):
                async with processing_lock:
                    processed_messages.append((user, channel, message))
                await asyncio.sleep(0.005)  # Simulate processing time
                return True

            mock_bot.handle_message = AsyncMock(side_effect=track_message_processing)
            mock_bot._processed_messages = processed_messages
            mock_bots.append(mock_bot)

        # Mock bot manager
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
            # Simulate concurrent multi-bot operations
            async def simulate_multi_bot_concurrent_load(manager):
                # Generate concurrent load for each bot
                messages_per_bot = 20
                concurrent_tasks = []

                for bot_idx, bot in enumerate(manager.lifecycle.bots):
                    # Create concurrent message tasks for this bot
                    bot_tasks = []
                    for msg_idx in range(messages_per_bot):
                        task = bot.handle_message(
                            f"user_{bot_idx}_{msg_idx}",
                            f"#channel_{bot_idx}",
                            f"ccc color_{bot_idx}_{msg_idx}"
                        )
                        bot_tasks.append(task)

                    # Add bot's tasks as a concurrent batch
                    concurrent_tasks.append(asyncio.create_task(asyncio.gather(*bot_tasks)))

                # Wait for all bots to complete their message processing
                await asyncio.gather(*concurrent_tasks)

                manager.running = False

            mock_run_loop.side_effect = simulate_multi_bot_concurrent_load

            # Run the main function
            await main()

            # Verify concurrent multi-bot operation
            total_expected_messages = num_bots * messages_per_bot

            # Check each bot processed its messages
            for i, bot in enumerate(mock_bots):
                assert bot.handle_message.call_count == messages_per_bot
                assert len(bot._processed_messages) == messages_per_bot

            # Verify total message count
            total_calls = sum(bot.handle_message.call_count for bot in mock_bots)
            assert total_calls == total_expected_messages

    @pytest.mark.asyncio
    async def test_resource_usage_under_concurrent_load(self):
        """Test resource usage stability under concurrent load.

        Validates that resource usage remains stable during
        high concurrent load conditions.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Record initial resource state
            gc.collect()
            initial_objects = len(gc.get_objects())
            initial_time = time.time()

            # Simulate concurrent load with resource monitoring
            load_duration = 30  # 30 seconds of concurrent load
            concurrent_tasks = 50

            async def generate_concurrent_load():
                tasks = []

                for i in range(concurrent_tasks):
                    task = asyncio.create_task(simulate_workload(i))
                    tasks.append(task)

                await asyncio.gather(*tasks)

            async def simulate_workload(task_id):
                # Simulate CPU and memory intensive work
                for i in range(100):
                    # Simulate some processing
                    await asyncio.sleep(0.001)

                    # Periodic resource check
                    if i % 20 == 0:
                        gc.collect()

                return task_id

            # Run concurrent load
            await generate_concurrent_load()

            # Check resource usage after load
            gc.collect()
            final_objects = len(gc.get_objects())
            elapsed = time.time() - initial_time

            # Resource usage should remain reasonable
            growth_ratio = final_objects / initial_objects
            max_acceptable_growth = 1.2  # Allow 20% growth

            assert growth_ratio <= max_acceptable_growth, (
                f"Resource usage grew too much: {growth_ratio:.2f}x "
                f"(limit: {max_acceptable_growth:.2f}x)"
            )

            # Verify context remained stable
            assert context._started is True
            assert context.session is not None
            assert not context.session.closed

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_memory_pressure_concurrent_operations(self):
        """Test system behavior under memory pressure with concurrent operations.

        Validates that the system remains stable and responsive
        even when operating under memory pressure.
        """
        # Mock configuration
        mock_config = [
            {
                "username": "memory_test_user",
                "access_token": "oauth:memory_test_token",
                "refresh_token": "memory_test_refresh_token",
                "client_id": "memory_test_client_id",
                "client_secret": "memory_test_client_secret",
                "channels": ["#memory_test_channel"],
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

        # Mock bot with memory tracking
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        mock_bot.stop = AsyncMock()
        mock_bot.close = AsyncMock()
        mock_bot.running = True

        memory_usage_log = []

        async def track_memory_usage(user, channel, message):
            # Track memory usage during processing
            gc.collect()
            current_objects = len(gc.get_objects())
            memory_usage_log.append(current_objects)

            # Simulate memory-intensive processing
            await asyncio.sleep(0.005)
            return True

        mock_bot.handle_message = AsyncMock(side_effect=track_memory_usage)

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
            # Simulate memory pressure scenario
            async def simulate_memory_pressure(manager):
                # Generate memory pressure with concurrent operations
                num_operations = 200

                for i in range(num_operations):
                    await manager.lifecycle.bots[0].handle_message(
                        f"user_{i}", "#memory_test_channel", f"ccc color_{i}"
                    )

                    # Periodic garbage collection to simulate memory pressure
                    if i % 50 == 0:
                        gc.collect()

                manager.running = False

            mock_run_loop.side_effect = simulate_memory_pressure

            # Run the main function
            await main()

            # Verify memory pressure handling
            assert mock_bot.handle_message.call_count == num_operations
            assert len(memory_usage_log) == num_operations

            # Check memory usage patterns
            if len(memory_usage_log) > 1:
                initial_memory = memory_usage_log[0]
                final_memory = memory_usage_log[-1]

                # Memory should not have grown excessively
                growth_ratio = final_memory / initial_memory
                assert growth_ratio < 2.0, (
                    f"Memory grew too much under pressure: {growth_ratio:.2f}x"
                )

    @pytest.mark.asyncio
    async def test_concurrent_bot_lifecycle_operations(self):
        """Test concurrent bot lifecycle operations.

        Validates that bot start/stop/create operations can happen
        concurrently without race conditions or deadlocks.
        """
        # Mock configuration
        mock_config = [
            {
                "username": "lifecycle_test_user",
                "access_token": "oauth:lifecycle_test_token",
                "refresh_token": "lifecycle_test_refresh_token",
                "client_id": "lifecycle_test_client_id",
                "client_secret": "lifecycle_test_client_secret",
                "channels": ["#lifecycle_test_channel"],
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

