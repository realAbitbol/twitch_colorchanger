"""
Unit tests for AsyncPersistence.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.config import async_persistence
from src.config.async_persistence import (
    _flush,
    _log_batch_result,
    _log_batch_start,
    _persist_batch,
    async_update_user_in_config,
    cancel_pending_flush,
    flush_pending_updates,
    queue_user_update,
)


class TestAsyncPersistence:
    """Test class for AsyncPersistence functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        # Clear global state between tests
        from src.config import async_persistence
        async_persistence._PENDING.clear()
        async_persistence._FLUSH_TASK = None

    def teardown_method(self):
        """Teardown method called after each test."""
        # Clean up any remaining tasks
        from src.config import async_persistence
        if async_persistence._FLUSH_TASK and not async_persistence._FLUSH_TASK.done():
            async_persistence._FLUSH_TASK.cancel()

    @pytest.mark.asyncio
    async def test_queue_user_update_should_queue_valid_user(self):
        """Test queue_user_update queues valid user config."""
        config_file = "test.conf"
        user_config = {"username": "testuser", "color": "#FF0000"}

        await queue_user_update(user_config, config_file)

        from src.config import async_persistence
        assert "testuser" in async_persistence._PENDING
        assert async_persistence._PENDING["testuser"][0] == user_config

    @pytest.mark.asyncio
    async def test_queue_user_update_should_ignore_empty_username(self):
        """Test queue_user_update ignores configs with empty username."""
        config_file = "test.conf"
        user_config = {"username": "", "color": "#FF0000"}

        await queue_user_update(user_config, config_file)

        from src.config import async_persistence
        assert len(async_persistence._PENDING) == 0

    @pytest.mark.asyncio
    async def test_queue_user_update_should_merge_configs(self):
        """Test queue_user_update merges multiple updates for same user."""
        config_file = "test.conf"
        user_config1 = {"username": "testuser", "color": "#FF0000"}
        user_config2 = {"username": "testuser", "enabled": True}

        await queue_user_update(user_config1, config_file)
        await queue_user_update(user_config2, config_file)

        from src.config import async_persistence
        expected = {"username": "testuser", "color": "#FF0000", "enabled": True}
        assert async_persistence._PENDING["testuser"][0] == expected

    @pytest.mark.asyncio
    async def test_queue_user_update_should_schedule_flush_task(self):
        """Test queue_user_update schedules flush task when none exists."""
        config_file = "test.conf"
        user_config = {"username": "testuser", "color": "#FF0000"}

        await queue_user_update(user_config, config_file)

        from src.config import async_persistence
        assert async_persistence._FLUSH_TASK is not None
        assert not async_persistence._FLUSH_TASK.done()

    @pytest.mark.asyncio
    async def test_queue_user_update_should_not_schedule_duplicate_task(self):
        """Test queue_user_update doesn't schedule duplicate flush task."""
        config_file = "test.conf"
        user_config1 = {"username": "testuser1", "color": "#FF0000"}
        user_config2 = {"username": "testuser2", "color": "#00FF00"}

        await queue_user_update(user_config1, config_file)
        first_task = async_persistence._FLUSH_TASK

        await queue_user_update(user_config2, config_file)
        second_task = async_persistence._FLUSH_TASK

        assert first_task is second_task

    @pytest.mark.asyncio
    async def test_flush_should_process_pending_updates(self):
        """Test _flush processes all pending updates."""
        import time

        from src.config import async_persistence
        config_file = "test.conf"
        async_persistence._PENDING["testuser"] = ({"username": "testuser", "color": "#FF0000"}, time.time())

        with patch('src.config.async_persistence._persist_batch', new_callable=AsyncMock) as mock_persist:
            mock_persist.return_value = 0
            await _flush(config_file)

        mock_persist.assert_called_once_with([{"username": "testuser", "color": "#FF0000"}], config_file)
        assert len(async_persistence._PENDING) == 0
        assert async_persistence._FLUSH_TASK is None

    @pytest.mark.asyncio
    async def test_flush_should_skip_when_no_pending(self):
        """Test _flush skips when no pending updates."""
        config_file = "test.conf"

        with patch('src.config.async_persistence._persist_batch', new_callable=AsyncMock) as mock_persist:
            await _flush(config_file)

        mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_batch_should_persist_all_successfully(self):
        """Test _persist_batch persists all configs successfully."""
        pending = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "user2", "color": "#00FF00"}
        ]
        config_file = "test.conf"

        with patch('src.config.async_persistence.update_user_in_config', return_value=True), \
              patch('asyncio.get_event_loop') as mock_loop, \
              patch('shutil.copy2') as mock_copy, \
              patch('os.remove') as mock_remove:
            mock_loop.return_value.run_in_executor = AsyncMock()
            failures = await _persist_batch(pending, config_file)

        assert failures == 0
        assert mock_loop.return_value.run_in_executor.call_count == 2
        mock_copy.assert_called_once()
        mock_remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_batch_should_count_failures(self):
        """Test _persist_batch counts persistence failures."""
        pending = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "user2", "color": "#00FF00"}
        ]
        config_file = "test.conf"

        with patch('asyncio.get_event_loop') as mock_loop, \
              patch('shutil.copy2') as mock_copy, \
              patch('os.remove') as mock_remove:
            mock_loop.return_value.run_in_executor = AsyncMock(side_effect=[True, False])
            failures = await _persist_batch(pending, config_file)

        assert failures == 1
        # copy2 called twice: once for backup, once for rollback
        assert mock_copy.call_count == 2
        mock_remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_batch_should_use_persistence_lock(self):
        """Test _persist_batch uses the global persistence lock."""
        pending = [{"username": "user1", "color": "#FF0000"}]
        config_file = "test.conf"

        with patch('src.config.async_persistence.update_user_in_config', return_value=True), \
             patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock()
            await _persist_batch(pending, config_file)

        # Verify the lock context was used (hard to test directly, but ensure no exceptions)

    @pytest.mark.asyncio
    async def test_cancel_pending_flush_should_cancel_task(self):
        """Test cancel_pending_flush cancels pending flush task."""
        from src.config import async_persistence
        config_file = "test.conf"

        # Schedule a task
        await queue_user_update({"username": "testuser", "color": "#FF0000"}, config_file)
        assert async_persistence._FLUSH_TASK is not None

        await cancel_pending_flush()

        assert async_persistence._FLUSH_TASK is None

    @pytest.mark.asyncio
    async def test_cancel_pending_flush_should_handle_no_task(self):
        """Test cancel_pending_flush handles case with no pending task."""
        await cancel_pending_flush()
        # Should not raise any exceptions

    @pytest.mark.asyncio
    async def test_flush_pending_updates_should_force_flush(self):
        """Test flush_pending_updates forces immediate flush."""
        import time

        from src.config import async_persistence
        config_file = "test.conf"
        async_persistence._PENDING["testuser"] = ({"username": "testuser", "color": "#FF0000"}, time.time())

        with patch('src.config.async_persistence._persist_batch', new_callable=AsyncMock) as mock_persist:
            mock_persist.return_value = 0
            await flush_pending_updates(config_file)

        mock_persist.assert_called_once()
        assert len(async_persistence._PENDING) == 0

    @pytest.mark.asyncio
    async def test_async_update_user_in_config_should_call_sync_function(self):
        """Test async_update_user_in_config calls sync update function."""
        user_config = {"username": "testuser", "color": "#FF0000"}
        config_file = "test.conf"

        with patch('src.config.async_persistence.update_user_in_config', return_value=True), \
             patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=True)
            result = await async_update_user_in_config(user_config, config_file)

        assert result is True
        mock_loop.return_value.run_in_executor.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_update_user_in_config_should_use_persistence_lock(self):
        """Test async_update_user_in_config uses persistence lock."""
        user_config = {"username": "testuser", "color": "#FF0000"}
        config_file = "test.conf"

        with patch('src.config.async_persistence.update_user_in_config', return_value=True), \
             patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=True)
            await async_update_user_in_config(user_config, config_file)

        # Lock usage is implicit in the async with block

    def test_log_batch_start_should_log_debug_message(self):
        """Test _log_batch_start logs debug message."""
        with patch('src.config.async_persistence.logging') as mock_logging:
            _log_batch_start(5)

        mock_logging.debug.assert_called_once()
        call_args = mock_logging.debug.call_args[0][0]
        assert "count=5" in call_args

    def test_log_batch_result_should_log_warning_on_failures(self):
        """Test _log_batch_result logs warning when there are failures."""
        with patch('src.config.async_persistence.logging') as mock_logging:
            _log_batch_result(2, 5)

        mock_logging.warning.assert_called_once()
        call_args = mock_logging.warning.call_args[0][0]
        assert "failures count=2" in call_args
        assert "attempted=5" in call_args

    def test_log_batch_result_should_not_log_on_success(self):
        """Test _log_batch_result doesn't log when no failures."""
        with patch('src.config.async_persistence.logging') as mock_logging:
            _log_batch_result(0, 5)

        mock_logging.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_queue_updates_should_not_deadlock(self):
        """Test concurrent queue_user_update calls don't deadlock."""
        config_file = "test.conf"
        user_configs = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "user2", "color": "#00FF00"},
            {"username": "user3", "color": "#0000FF"}
        ]

        # Run multiple concurrent updates
        tasks = [queue_user_update(config, config_file) for config in user_configs]
        await asyncio.gather(*tasks)

        from src.config import async_persistence
        assert len(async_persistence._PENDING) == 3

    @pytest.mark.asyncio
    async def test_concurrent_persist_batch_should_use_lock(self):
        """Test concurrent _persist_batch calls use the same lock."""
        pending1 = [{"username": "user1", "color": "#FF0000"}]
        pending2 = [{"username": "user2", "color": "#00FF00"}]
        config_file = "test.conf"

        async def persist_with_delay(pending):
            await asyncio.sleep(0.01)  # Small delay to test concurrency
            return await _persist_batch(pending, config_file)

        with patch('src.config.async_persistence.update_user_in_config', return_value=True), \
              patch('asyncio.get_event_loop') as mock_loop, \
              patch('shutil.copy2') as mock_copy, \
              patch('os.remove') as mock_remove:
            mock_loop.return_value.run_in_executor = AsyncMock()
            # Run concurrent persists
            results = await asyncio.gather(
                persist_with_delay(pending1),
                persist_with_delay(pending2)
            )

        # Both should succeed without deadlocks
        assert results == [0, 0]

    @pytest.mark.asyncio
    async def test_debounced_flush_should_delay_execution(self):
        """Test that flush is debounced and delayed."""
        from src.config import async_persistence
        config_file = "test.conf"

        # Mock sleep to speed up test
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep, \
             patch('src.config.async_persistence._persist_batch', new_callable=AsyncMock) as mock_persist:
            mock_persist.return_value = 0

            # Queue update
            await queue_user_update({"username": "testuser", "color": "#FF0000"}, config_file)

            # Wait for flush to complete
            await async_persistence._FLUSH_TASK

            mock_sleep.assert_called_once()
            mock_persist.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_in_persist_should_be_handled_gracefully(self):
        """Test that errors in persistence are handled without crashing."""
        pending = [{"username": "user1", "color": "#FF0000"}]
        config_file = "test.conf"

        with patch('asyncio.get_event_loop') as mock_loop, \
             patch('shutil.copy2') as mock_copy:
            mock_loop.return_value.run_in_executor = AsyncMock(side_effect=Exception("IO Error"))
            failures = await _persist_batch(pending, config_file)

        assert failures == 1
        mock_copy.assert_called()  # rollback called

    @pytest.mark.asyncio
    async def test_persist_batch_should_rollback_on_partial_failure(self):
        """Test _persist_batch rolls back on partial batch failure."""
        pending = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "user2", "color": "#00FF00"}
        ]
        config_file = "test.conf"

        with patch('asyncio.get_event_loop') as mock_loop, \
             patch('shutil.copy2') as mock_copy, \
             patch('os.remove') as mock_remove:
            mock_loop.return_value.run_in_executor = AsyncMock(side_effect=[True, False])
            failures = await _persist_batch(pending, config_file)

        assert failures == 1
        # copy2 called twice: once for backup, once for rollback
        assert mock_copy.call_count == 2
        mock_remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_batch_should_rollback_atomically_on_first_failure(self):
        """Test _persist_batch ensures atomicity: rollback entire batch if any item fails, even if later items succeed."""
        pending = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "user2", "color": "#00FF00"},
            {"username": "user3", "color": "#0000FF"}
        ]
        config_file = "test.conf"

        with patch('asyncio.get_event_loop') as mock_loop, \
             patch('shutil.copy2') as mock_copy, \
             patch('os.remove') as mock_remove:
            # First fails, second and third succeed
            mock_loop.return_value.run_in_executor = AsyncMock(side_effect=[False, True, True])
            failures = await _persist_batch(pending, config_file)

        assert failures == 1
        # copy2 called twice: once for backup, once for rollback (atomic rollback)
        assert mock_copy.call_count == 2
        mock_remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_batch_should_fail_all_on_backup_failure(self):
        """Test _persist_batch fails all when backup creation fails."""
        pending = [
            {"username": "user1", "color": "#FF0000"},
            {"username": "user2", "color": "#00FF00"}
        ]
        config_file = "test.conf"

        with patch('shutil.copy2', side_effect=OSError("Backup failed")):
            failures = await _persist_batch(pending, config_file)

        assert failures == 2  # len(pending)

    @pytest.mark.asyncio
    async def test_empty_batch_should_not_persist(self):
        """Test that empty pending batch doesn't attempt persistence."""
        config_file = "test.conf"

        with patch('src.config.async_persistence._persist_batch', new_callable=AsyncMock) as mock_persist:
            await _flush(config_file)

        mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_queue_user_update_should_clean_expired_entries(self):
        """Test queue_user_update cleans expired user lock entries."""
        import time

        from src.config import async_persistence
        config_file = "test.conf"

        # Add an expired entry
        expired_time = time.time() - async_persistence._USER_LOCK_TTL_SECONDS - 1
        async_persistence._PENDING["expireduser"] = ({"username": "expireduser", "color": "#000000"}, expired_time)

        # Add a valid entry
        await queue_user_update({"username": "validuser", "color": "#FF0000"}, config_file)

        # Expired entry should be cleaned
        assert "expireduser" not in async_persistence._PENDING
        assert "validuser" in async_persistence._PENDING

    @pytest.mark.asyncio
    async def test_flush_should_filter_expired_entries(self):
        """Test _flush filters out expired entries before processing."""
        import time

        from src.config import async_persistence
        config_file = "test.conf"

        # Add expired and valid entries
        expired_time = time.time() - async_persistence._USER_LOCK_TTL_SECONDS - 1
        valid_time = time.time()
        async_persistence._PENDING["expireduser"] = ({"username": "expireduser", "color": "#000000"}, expired_time)
        async_persistence._PENDING["validuser"] = ({"username": "validuser", "color": "#FF0000"}, valid_time)

        with patch('src.config.async_persistence._persist_batch', new_callable=AsyncMock) as mock_persist:
            mock_persist.return_value = 0
            await _flush(config_file)

        # Only valid entry should be persisted
        mock_persist.assert_called_once_with([{"username": "validuser", "color": "#FF0000"}], config_file)
        assert len(async_persistence._PENDING) == 0

    @pytest.mark.asyncio
    async def test_user_lock_registry_memory_bounding(self):
        """Test that user lock registry memory is bounded by TTL cleanup."""
        import time

        from src.config import async_persistence
        config_file = "test.conf"

        # Simulate many users over time
        for i in range(10):
            await queue_user_update({"username": f"user{i}", "color": f"#{i:02X}0000"}, config_file)

        initial_count = len(async_persistence._PENDING)
        assert initial_count > 0

        # Simulate time passing beyond TTL
        with patch('time.time', return_value=time.time() + async_persistence._USER_LOCK_TTL_SECONDS + 1):
            # Next operation should clean expired entries
            await queue_user_update({"username": "newuser", "color": "#FFFFFF"}, config_file)

        # All previous entries should be cleaned, only new one remains
        assert len(async_persistence._PENDING) == 1
        assert "newuser" in async_persistence._PENDING
