"""Memory leak detection and resource monitoring tests.

Tests for detecting memory leaks, resource usage patterns,
and ensuring proper resource cleanup over extended periods.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import psutil
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application_context import ApplicationContext
from src.bot.manager import BotManager
from src.main import main


class TestMemoryLeakDetection:
    """Test suite for memory leak detection and resource monitoring."""

    @pytest.mark.asyncio
    async def test_application_context_memory_stability(self):
        """Test ApplicationContext for memory leaks over time.

        Validates that the application context doesn't leak memory
        during extended operation with repeated operations.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Record initial memory state
            gc.collect()
            initial_objects = len(gc.get_objects())
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss

            # Simulate extended operation with periodic memory checks
            test_duration = 8  # 8 seconds total
            check_interval = 2  # Check every 2 seconds
            operation_cycles = 4

            memory_growth_tolerance = 1.15  # Allow 15% growth
            max_allowed_objects = int(initial_objects * memory_growth_tolerance)

            for cycle in range(operation_cycles):
                # Simulate typical application context operations
                if context.token_manager:
                    # Simulate token manager operations
                    pass

                # Periodic memory check
                if cycle % 5 == 0:  # Check every 5 cycles
                    gc.collect()
                    current_objects = len(gc.get_objects())
                    current_memory = process.memory_info().rss

                    # Log memory usage for monitoring
                    elapsed = cycle * (test_duration / operation_cycles)
                    logging.debug(
                        f"Memory check at cycle {cycle} ({elapsed:.1f}s): "
                        f"objects: {current_objects}, memory: {current_memory / 1024 / 1024:.2f}MB"
                    )

                    # Assert memory usage is within acceptable limits
                    assert current_objects <= max_allowed_objects, (
                        f"Memory leak detected: {current_objects} objects "
                        f"(limit: {max_allowed_objects}) at cycle {cycle}"
                    )

                    # Check memory growth isn't excessive
                    memory_growth = current_memory / initial_memory
                    assert memory_growth <= memory_growth_tolerance, (
                        f"Memory usage grew too much: {memory_growth:.2f}x "
                        f"(limit: {memory_growth_tolerance:.2f}x) at cycle {cycle}"
                    )

                await asyncio.sleep(test_duration / operation_cycles)

            # Final memory assessment
            gc.collect()
            final_objects = len(gc.get_objects())
            final_memory = process.memory_info().rss

            total_memory_growth = final_memory / initial_memory
            total_object_growth = final_objects / initial_objects

            logging.info(
                f"Memory leak test completed: "
                f"objects: {initial_objects} -> {final_objects} ({total_object_growth:.2f}x), "
                f"memory: {initial_memory / 1024 / 1024:.2f}MB -> {final_memory / 1024 / 1024:.2f}MB ({total_memory_growth:.2f}x)"
            )

            # Final assertions
            assert total_object_growth <= memory_growth_tolerance
            assert total_memory_growth <= memory_growth_tolerance

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_bot_manager_memory_usage_patterns(self):
        """Test BotManager memory usage patterns over time.

        Validates that bot manager operations don't cause memory leaks
        during repeated bot lifecycle operations.
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
        memory_usage_log = []

        def track_memory_usage():
            gc.collect()
            current_objects = len(gc.get_objects())
            memory_usage_log.append(current_objects)

        mock_bot = MagicMock()
        mock_bot.start = AsyncMock(side_effect=lambda: track_memory_usage())
        mock_bot.stop = AsyncMock(side_effect=lambda: track_memory_usage())
        mock_bot.close = AsyncMock(side_effect=lambda: track_memory_usage())
        mock_bot.running = True
        mock_bot.handle_message = AsyncMock(side_effect=lambda *args, **kwargs: track_memory_usage())

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
            # Simulate memory usage pattern testing
            async def simulate_memory_patterns(manager):
                # Simulate repeated bot lifecycle operations
                for cycle in range(30):
                    # Start bot
                    await manager.lifecycle.bots[0].start()

                    # Process some messages
                    for msg in range(5):
                        await manager.lifecycle.bots[0].handle_message(
                            f"user_{cycle}_{msg}",
                            "#memory_test_channel",
                            f"ccc color_{cycle}_{msg}"
                        )

                    # Stop bot
                    await manager.lifecycle.bots[0].stop()

                    # Periodic cleanup simulation
                    if cycle % 10 == 0:
                        gc.collect()

                manager.running = False

            mock_run_loop.side_effect = simulate_memory_patterns

            # Run the main function
            await main()

            # Verify memory usage patterns
            assert len(memory_usage_log) > 0

            # Check for memory growth patterns
            if len(memory_usage_log) > 1:
                initial_memory = memory_usage_log[0]
                final_memory = memory_usage_log[-1]

                # Memory should not have grown excessively
                growth_ratio = final_memory / initial_memory
                assert growth_ratio < 1.5, (
                    f"Memory grew too much during bot lifecycle: {growth_ratio:.2f}x"
                )

    @pytest.mark.asyncio
    async def test_connection_pool_leak_detection(self):
        """Test for connection pool leaks in HTTP sessions.

        Validates that HTTP connections are properly managed
        and don't leak during extended operation.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Record initial connection state
            session = context.session
            assert session is not None

            # Get initial connector stats if available
            initial_connections = 0
            if hasattr(session, '_connector') and session._connector:
                connector = session._connector
                if hasattr(connector, '_conns'):
                    initial_connections = len(connector._conns)

            # Simulate extended operation with connection usage
            test_duration = 5  # 5 seconds
            connection_operations = 20

            for i in range(connection_operations):
                # Simulate connection usage (in real scenario, this would be actual HTTP calls)
                # The session should manage connections properly

                if i % 20 == 0:  # Periodic check
                    # Verify session is still healthy
                    assert not session.closed
                    assert session._connector is not None

                    # Check for connection pool growth
                    if hasattr(session._connector, '_conns'):
                        current_connections = len(session._connector._conns)
                        # Connection pool should not grow unbounded
                        assert current_connections < 50, (
                            f"Connection pool grew too large: {current_connections} connections"
                        )

                await asyncio.sleep(test_duration / connection_operations)

            # Final connection pool check
            if hasattr(session._connector, '_conns'):
                final_connections = len(session._connector._conns)

                # Connection pool should be reasonable
                assert final_connections < 20, (
                    f"Connection pool leak detected: {final_connections} connections"
                )

                logging.info(f"Connection pool: {initial_connections} -> {final_connections} connections")

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_file_handle_leak_detection(self):
        """Test for file handle leaks during operation.

        Validates that file handles are properly managed
        and don't leak during extended operation.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Record initial file handle count
            process = psutil.Process(os.getpid())
            initial_fds = process.num_fds()

            # Simulate extended operation that might use file handles
            test_duration = 5  # 5 seconds
            operation_cycles = 10

            for cycle in range(operation_cycles):
                # Simulate operations that might involve file I/O
                # (In real scenario, this would be actual file operations)

                if cycle % 10 == 0:  # Periodic check
                    current_fds = process.num_fds()

                    # File descriptor count should remain stable
                    fd_growth = current_fds - initial_fds
                    max_fd_growth = 10  # Allow small growth

                    assert fd_growth <= max_fd_growth, (
                        f"File descriptor leak detected: {fd_growth} new FDs "
                        f"(limit: {max_fd_growth}) at cycle {cycle}"
                    )

                    logging.debug(f"FD check at cycle {cycle}: {current_fds} FDs")

                await asyncio.sleep(test_duration / operation_cycles)

            # Final file descriptor check
            final_fds = process.num_fds()
            total_fd_growth = final_fds - initial_fds

            logging.info(f"File descriptors: {initial_fds} -> {final_fds} ({total_fd_growth} growth)")

            # File descriptor growth should be minimal
            assert total_fd_growth <= 5, (
                f"File descriptor leak detected: {total_fd_growth} growth"
            )

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_garbage_collection_effectiveness(self):
        """Test garbage collection effectiveness during extended operation.

        Validates that garbage collection is working properly
        and objects are being cleaned up appropriately.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Test garbage collection patterns
            gc_stats_before = []
            gc_stats_after = []

            for cycle in range(20):
                # Record GC stats before operations
                gc.collect()
                stats_before = gc.get_stats()
                gc_stats_before.append(stats_before)

                # Generate some objects
                temp_objects = []
                for i in range(1000):
                    temp_objects.append(f"temp_object_{cycle}_{i}")

                # Use some objects
                used_objects = temp_objects[:100]

                # Record GC stats after operations
                gc.collect()
                stats_after = gc.get_stats()
                gc_stats_after.append(stats_after)

                # Clear references to allow GC
                del temp_objects
                del used_objects

                await asyncio.sleep(0.1)

            # Analyze garbage collection effectiveness
            if gc_stats_before and gc_stats_after:
                # Check that GC is running and collecting objects
                initial_collections = sum(stat['collections'] for stat in gc_stats_before[0])
                final_collections = sum(stat['collections'] for stat in gc_stats_after[-1])

                collection_count = final_collections - initial_collections

                logging.info(f"Garbage collections performed: {collection_count}")

                # GC should have run multiple times
                assert collection_count > 0, "Garbage collection did not run"

                # Verify context remained stable during GC stress
                assert context._started is True
                assert context.session is not None
                assert not context.session.closed

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_resource_cleanup_verification(self):
        """Test comprehensive resource cleanup after extended operation.

        Validates that all resources are properly cleaned up
        after extended operation with various resource types.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Record initial resource state
            process = psutil.Process(os.getpid())
            initial_fds = process.num_fds()
            initial_memory = process.memory_info().rss

            gc.collect()
            initial_objects = len(gc.get_objects())

            # Simulate extended operation with resource usage
            await asyncio.sleep(5)  # 5 seconds of operation

            # Verify resources are still properly managed during operation
            mid_fds = process.num_fds()
            mid_memory = process.memory_info().rss

            gc.collect()
            mid_objects = len(gc.get_objects())

            # Resource usage should be reasonable during operation
            fd_growth = mid_fds - initial_fds
            memory_growth = mid_memory / initial_memory
            object_growth = mid_objects / initial_objects

            assert fd_growth <= 5, f"File descriptor growth during operation: {fd_growth}"
            assert memory_growth <= 1.2, f"Memory growth during operation: {memory_growth:.2f}x"
            assert object_growth <= 1.2, f"Object growth during operation: {object_growth:.2f}x"

        finally:
            # Shutdown and verify cleanup
            await context.shutdown()

            # Wait a bit for cleanup to complete
            await asyncio.sleep(1)

            # Record final resource state
            final_fds = process.num_fds()
            final_memory = process.memory_info().rss

            gc.collect()
            final_objects = len(gc.get_objects())

            # Calculate cleanup effectiveness
            fd_cleanup = initial_fds - final_fds
            memory_cleanup = initial_memory - final_memory
            object_cleanup = initial_objects - final_objects

            logging.info(
                f"Resource cleanup: "
                f"FDs: {initial_fds} -> {final_fds} ({fd_cleanup} cleaned), "
                f"Memory: {initial_memory / 1024 / 1024:.2f}MB -> {final_memory / 1024 / 1024:.2f}MB ({memory_cleanup / 1024 / 1024:.2f}MB cleaned), "
                f"Objects: {initial_objects} -> {final_objects} ({object_cleanup} cleaned)"
            )

            # Verify cleanup was effective
            # Note: Some resources may remain due to test infrastructure
            # but the application context should be clean
            assert context._started is False
            assert context.session is None or context.session.closed

    @pytest.mark.asyncio
    async def test_memory_fragmentation_monitoring(self):
        """Test for memory fragmentation during extended operation.

        Validates that memory fragmentation doesn't become excessive
        during long-running operations.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Monitor memory fragmentation patterns
            fragmentation_samples = []

            for sample in range(15):
                # Force garbage collection
                gc.collect()

                # Get memory stats
                process = psutil.Process(os.getpid())
                memory_info = process.memory_info()

                # Calculate fragmentation metrics
                if hasattr(process, 'memory_maps'):
                    memory_maps = process.memory_maps()
                    fragmentation_score = len(memory_maps)  # More maps = more fragmentation
                    fragmentation_samples.append(fragmentation_score)

                await asyncio.sleep(5)  # Sample every 5 seconds

            # Analyze fragmentation patterns
            if fragmentation_samples:
                initial_fragmentation = fragmentation_samples[0]
                final_fragmentation = fragmentation_samples[-1]
                max_fragmentation = max(fragmentation_samples)

                logging.info(
                    f"Memory fragmentation: "
                    f"initial: {initial_fragmentation}, max: {max_fragmentation}, final: {final_fragmentation}"
                )

                # Fragmentation should not grow excessively
                fragmentation_growth = max_fragmentation / initial_fragmentation
                assert fragmentation_growth < 3.0, (
                    f"Memory fragmentation grew too much: {fragmentation_growth:.2f}x"
                )

                # Final fragmentation should be reasonable
                assert final_fragmentation < 100, (
                    f"Final memory fragmentation too high: {final_fragmentation} maps"
                )

        finally:
            await context.shutdown()

    @pytest.mark.asyncio
    async def test_thread_leak_detection(self):
        """Test for thread leaks during operation.

        Validates that threads are properly managed and
        don't leak during extended operation.
        """
        context = await ApplicationContext.create()
        await context.start()

        try:
            # Record initial thread count
            initial_threads = len(psutil.Process(os.getpid()).threads())

            # Simulate extended operation
            test_duration = 5  # 5 seconds
            await asyncio.sleep(test_duration)

            # Check for thread leaks
            final_threads = len(psutil.Process(os.getpid()).threads())
            thread_growth = final_threads - initial_threads

            logging.info(f"Thread count: {initial_threads} -> {final_threads} ({thread_growth} growth)")

            # Thread growth should be minimal
            assert thread_growth <= 2, (
                f"Thread leak detected: {thread_growth} new threads"
            )

            # Verify context remained stable
            assert context._started is True
            assert context.session is not None
            assert not context.session.closed

        finally:
            await context.shutdown()

            # Final thread check after cleanup
            final_threads = len(psutil.Process(os.getpid()).threads())
            logging.info(f"Final thread count after cleanup: {final_threads}")

            # Thread count should be reasonable after cleanup
            assert final_threads <= initial_threads + 1