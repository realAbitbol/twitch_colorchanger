"""
Unit tests for CleanupCoordinator session registry functionality.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.chat.cleanup_coordinator import CleanupCoordinator


class TestCleanupCoordinatorSessionRegistry:
    """Test class for CleanupCoordinator session registry operations."""

    def setup_method(self):
        """Setup method called before each test."""
        # Reset singleton instance for clean tests
        CleanupCoordinator._instance = None
        self.coordinator = CleanupCoordinator()

    def teardown_method(self):
        """Teardown method called after each test."""
        # Clean up singleton instance
        CleanupCoordinator._instance = None

    @pytest.mark.asyncio
    async def test_register_session_id_success(self):
        """Test register_session_id adds session ID to active sessions."""
        # Arrange
        session_id = "session123"

        # Act
        await self.coordinator.register_session_id(session_id)

        # Assert
        assert session_id in self.coordinator._active_session_ids
        assert self.coordinator.get_active_session_ids() == [session_id]

    @pytest.mark.asyncio
    async def test_register_session_id_duplicate(self):
        """Test register_session_id handles duplicate session IDs gracefully."""
        # Arrange
        session_id = "session123"

        # Act
        await self.coordinator.register_session_id(session_id)
        await self.coordinator.register_session_id(session_id)  # duplicate

        # Assert
        assert session_id in self.coordinator._active_session_ids
        assert len(self.coordinator.get_active_session_ids()) == 1
        assert self.coordinator.get_active_session_ids() == [session_id]

    @pytest.mark.asyncio
    async def test_register_session_id_empty_string(self):
        """Test register_session_id handles empty string."""
        # Arrange
        session_id = ""

        # Act
        await self.coordinator.register_session_id(session_id)

        # Assert
        assert session_id in self.coordinator._active_session_ids
        assert self.coordinator.get_active_session_ids() == [""]

    @pytest.mark.asyncio
    async def test_register_session_id_multiple_sessions(self):
        """Test register_session_id with multiple different session IDs."""
        # Arrange
        session_ids = ["session1", "session2", "session3"]

        # Act
        for session_id in session_ids:
            await self.coordinator.register_session_id(session_id)

        # Assert
        active_sessions = self.coordinator.get_active_session_ids()
        assert len(active_sessions) == 3
        for session_id in session_ids:
            assert session_id in active_sessions

    @pytest.mark.asyncio
    async def test_unregister_session_id_success(self):
        """Test unregister_session_id removes session ID from active sessions."""
        # Arrange
        session_id = "session123"
        await self.coordinator.register_session_id(session_id)

        # Act
        await self.coordinator.unregister_session_id(session_id)

        # Assert
        assert session_id not in self.coordinator._active_session_ids
        assert self.coordinator.get_active_session_ids() == []

    @pytest.mark.asyncio
    async def test_unregister_session_id_not_registered(self):
        """Test unregister_session_id handles non-registered session ID gracefully."""
        # Arrange
        session_id = "session123"

        # Act
        await self.coordinator.unregister_session_id(session_id)

        # Assert
        assert session_id not in self.coordinator._active_session_ids
        assert self.coordinator.get_active_session_ids() == []

    @pytest.mark.asyncio
    async def test_unregister_session_id_empty_string(self):
        """Test unregister_session_id handles empty string."""
        # Arrange
        session_id = ""
        await self.coordinator.register_session_id(session_id)

        # Act
        await self.coordinator.unregister_session_id(session_id)

        # Assert
        assert session_id not in self.coordinator._active_session_ids
        assert self.coordinator.get_active_session_ids() == []

    @pytest.mark.asyncio
    async def test_unregister_session_id_partial_removal(self):
        """Test unregister_session_id removes only specified session ID."""
        # Arrange
        session_ids = ["session1", "session2", "session3"]
        for session_id in session_ids:
            await self.coordinator.register_session_id(session_id)

        # Act
        await self.coordinator.unregister_session_id("session2")

        # Assert
        active_sessions = self.coordinator.get_active_session_ids()
        assert len(active_sessions) == 2
        assert "session1" in active_sessions
        assert "session2" not in active_sessions
        assert "session3" in active_sessions

    def test_get_active_session_ids_empty(self):
        """Test get_active_session_ids returns empty list when no sessions registered."""
        # Act
        result = self.coordinator.get_active_session_ids()

        # Assert
        assert result == []

    def test_get_active_session_ids_returns_copy(self):
        """Test get_active_session_ids returns a copy, not the original set."""
        # Arrange
        session_id = "session123"
        self.coordinator._active_session_ids.add(session_id)

        # Act
        result = self.coordinator.get_active_session_ids()
        result.append("modified")  # Modify the returned list

        # Assert
        assert "modified" not in self.coordinator._active_session_ids
        assert self.coordinator.get_active_session_ids() == [session_id]

    def test_get_active_session_ids_sorted(self):
        """Test get_active_session_ids returns sessions in consistent order."""
        # Arrange
        session_ids = ["session3", "session1", "session2"]
        for session_id in session_ids:
            self.coordinator._active_session_ids.add(session_id)

        # Act
        result1 = self.coordinator.get_active_session_ids()
        result2 = self.coordinator.get_active_session_ids()

        # Assert
        assert result1 == result2  # Consistent ordering
        assert set(result1) == set(session_ids)

    @pytest.mark.asyncio
    async def test_thread_safety_register_concurrent(self):
        """Test thread safety of register_session_id with concurrent access."""
        # Arrange
        session_ids = [f"session{i}" for i in range(10)]

        # Act
        await asyncio.gather(*[
            self.coordinator.register_session_id(session_id)
            for session_id in session_ids
        ])

        # Assert
        active_sessions = self.coordinator.get_active_session_ids()
        assert len(active_sessions) == 10
        for session_id in session_ids:
            assert session_id in active_sessions

    @pytest.mark.asyncio
    async def test_thread_safety_unregister_concurrent(self):
        """Test thread safety of unregister_session_id with concurrent access."""
        # Arrange
        session_ids = [f"session{i}" for i in range(10)]
        for session_id in session_ids:
            await self.coordinator.register_session_id(session_id)

        # Act
        await asyncio.gather(*[
            self.coordinator.unregister_session_id(session_id)
            for session_id in session_ids[:5]  # Remove first 5
        ])

        # Assert
        active_sessions = self.coordinator.get_active_session_ids()
        assert len(active_sessions) == 5
        for session_id in session_ids[5:]:  # Last 5 should remain
            assert session_id in active_sessions

    @pytest.mark.asyncio
    async def test_thread_safety_mixed_operations(self):
        """Test thread safety with mixed register/unregister operations."""
        # Arrange
        session_ids = [f"session{i}" for i in range(20)]

        # Act - concurrent mixed operations
        tasks = []
        for i, session_id in enumerate(session_ids):
            if i % 2 == 0:
                tasks.append(self.coordinator.register_session_id(session_id))
            else:
                # Try to unregister non-existent session (should be safe)
                tasks.append(self.coordinator.unregister_session_id(session_id))

        await asyncio.gather(*tasks)

        # Assert
        active_sessions = self.coordinator.get_active_session_ids()
        assert len(active_sessions) == 10  # Every other session registered
        for i in range(0, 20, 2):
            assert session_ids[i] in active_sessions

    def test_singleton_behavior(self):
        """Test that CleanupCoordinator maintains singleton behavior."""
        # Arrange
        coordinator1 = CleanupCoordinator()
        coordinator2 = CleanupCoordinator()

        # Assert
        assert coordinator1 is coordinator2
        assert coordinator1 is self.coordinator

    def test_singleton_shared_state(self):
        """Test that singleton instances share state."""
        # Arrange
        coordinator1 = CleanupCoordinator()
        coordinator2 = CleanupCoordinator()

        # Act
        coordinator1._active_session_ids.add("shared_session")

        # Assert
        assert "shared_session" in coordinator2._active_session_ids
        assert coordinator2.get_active_session_ids() == ["shared_session"]

    @pytest.mark.asyncio
    async def test_shutdown_clears_session_ids(self):
        """Test shutdown clears all active session IDs."""
        # Arrange
        session_ids = ["session1", "session2", "session3"]
        for session_id in session_ids:
            await self.coordinator.register_session_id(session_id)

        # Act
        await self.coordinator.shutdown()

        # Assert
        assert len(self.coordinator._active_session_ids) == 0
        assert self.coordinator.get_active_session_ids() == []

    @pytest.mark.asyncio
    async def test_register_session_id_with_logging(self):
        """Test register_session_id logs the registration."""
        # Arrange
        session_id = "session123"

        # Act
        with patch('src.chat.cleanup_coordinator.logging') as mock_logging:
            await self.coordinator.register_session_id(session_id)

        # Assert
        mock_logging.debug.assert_called_once_with(f"🧹 Registered session ID: {session_id}")

    @pytest.mark.asyncio
    async def test_unregister_session_id_with_logging(self):
        """Test unregister_session_id logs the unregistration."""
        # Arrange
        session_id = "session123"
        await self.coordinator.register_session_id(session_id)

        # Act
        with patch('src.chat.cleanup_coordinator.logging') as mock_logging:
            await self.coordinator.unregister_session_id(session_id)

        # Assert
        mock_logging.debug.assert_called_once_with(f"🧹 Unregistered session ID: {session_id}")

    @pytest.mark.asyncio
    async def test_register_session_id_special_characters(self):
        """Test register_session_id handles special characters in session IDs."""
        # Arrange
        session_ids = ["session-123", "session_456", "session@789", "session#0"]

        # Act
        for session_id in session_ids:
            await self.coordinator.register_session_id(session_id)

        # Assert
        active_sessions = self.coordinator.get_active_session_ids()
        assert len(active_sessions) == 4
        for session_id in session_ids:
            assert session_id in active_sessions

    @pytest.mark.asyncio
    async def test_register_session_id_unicode(self):
        """Test register_session_id handles unicode characters."""
        # Arrange
        session_id = "session_ñáéíóú"

        # Act
        await self.coordinator.register_session_id(session_id)

        # Assert
        assert session_id in self.coordinator._active_session_ids
        assert self.coordinator.get_active_session_ids() == [session_id]

    @pytest.mark.asyncio
    async def test_register_session_id_long_string(self):
        """Test register_session_id handles very long session IDs."""
        # Arrange
        session_id = "a" * 1000  # Very long session ID

        # Act
        await self.coordinator.register_session_id(session_id)

        # Assert
        assert session_id in self.coordinator._active_session_ids
        assert self.coordinator.get_active_session_ids() == [session_id]

    @pytest.mark.asyncio
    async def test_register_session_id_handles_various_types(self):
        """Test register_session_id handles various input types."""
        # Test with integer (should work since sets can contain any hashable)
        await self.coordinator.register_session_id(123)
        assert 123 in self.coordinator._active_session_ids

    @pytest.mark.asyncio
    async def test_unregister_session_id_handles_various_types(self):
        """Test unregister_session_id handles various input types."""
        # Test with integer
        await self.coordinator.register_session_id(123)
        await self.coordinator.unregister_session_id(123)
        assert 123 not in self.coordinator._active_session_ids

    @pytest.mark.asyncio
    async def test_register_cleanup_task_first_task_becomes_active(self):
        """Test register_cleanup_task elects first task as active."""
        # Arrange
        cleanup_func = AsyncMock()

        # Act
        result = await self.coordinator.register_cleanup_task(cleanup_func)

        # Assert
        assert result is True
        assert cleanup_func in self.coordinator._registered_tasks
        assert self.coordinator._active_cleanup_task is not None
        assert not self.coordinator._active_cleanup_task.done()

    @pytest.mark.asyncio
    async def test_register_cleanup_task_second_task_becomes_passive(self):
        """Test register_cleanup_task registers second task as passive."""
        # Arrange
        first_func = AsyncMock()
        second_func = AsyncMock()
        await self.coordinator.register_cleanup_task(first_func)

        # Act
        result = await self.coordinator.register_cleanup_task(second_func)

        # Assert
        assert result is False
        assert first_func in self.coordinator._registered_tasks
        assert second_func in self.coordinator._registered_tasks
        assert self.coordinator._active_cleanup_task is not None

    @pytest.mark.asyncio
    async def test_register_cleanup_task_reuse_completed_task(self):
        """Test register_cleanup_task reuses slot when active task is done."""
        # Arrange
        first_func = AsyncMock()
        await self.coordinator.register_cleanup_task(first_func)
        # Cancel the active task to simulate completion
        if self.coordinator._active_cleanup_task:
            self.coordinator._active_cleanup_task.cancel()
            try:
                await self.coordinator._active_cleanup_task
            except asyncio.CancelledError:
                pass
        self.coordinator._active_cleanup_task = None

        second_func = AsyncMock()

        # Act
        result = await self.coordinator.register_cleanup_task(second_func)

        # Assert
        assert result is True
        assert self.coordinator._active_cleanup_task is not None
        # Clean up
        if self.coordinator._active_cleanup_task:
            self.coordinator._active_cleanup_task.cancel()
            try:
                await self.coordinator._active_cleanup_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_unregister_cleanup_task_active_task_cancelled_and_replaced(self):
        """Test unregister_cleanup_task cancels active task and elects new one."""
        # Arrange
        first_func = AsyncMock()
        second_func = AsyncMock()
        await self.coordinator.register_cleanup_task(first_func)
        await self.coordinator.register_cleanup_task(second_func)

        # Act
        await self.coordinator.unregister_cleanup_task(first_func)

        # Assert
        assert first_func not in self.coordinator._registered_tasks
        assert second_func in self.coordinator._registered_tasks
        # Active task should be replaced
        assert self.coordinator._active_cleanup_task is not None

    @pytest.mark.asyncio
    async def test_unregister_cleanup_task_passive_task_removed(self):
        """Test unregister_cleanup_task removes passive task without affecting active."""
        # Arrange
        first_func = AsyncMock()
        second_func = AsyncMock()
        await self.coordinator.register_cleanup_task(first_func)
        await self.coordinator.register_cleanup_task(second_func)

        # Act
        await self.coordinator.unregister_cleanup_task(second_func)

        # Assert
        assert first_func in self.coordinator._registered_tasks
        assert second_func not in self.coordinator._registered_tasks
        assert self.coordinator._active_cleanup_task is not None

    @pytest.mark.asyncio
    async def test_unregister_cleanup_task_no_active_task_after_removal(self):
        """Test unregister_cleanup_task leaves no active task when none registered."""
        # Arrange
        cleanup_func = AsyncMock()
        await self.coordinator.register_cleanup_task(cleanup_func)

        # Act
        await self.coordinator.unregister_cleanup_task(cleanup_func)

        # Assert
        assert cleanup_func not in self.coordinator._registered_tasks
        # The task should be cancelled and set to None
        assert self.coordinator._active_cleanup_task is None

    @pytest.mark.asyncio
    async def test_run_cleanup_loop_executes_cleanup_and_sleeps(self):
        """Test _run_cleanup_loop executes cleanup function and sleeps."""
        # Arrange
        cleanup_func = AsyncMock()
        interval = 6 * 3600  # 6 hours

        # Act - run one iteration then cancel
        task = asyncio.create_task(self.coordinator._run_cleanup_loop(cleanup_func))
        await asyncio.sleep(0.1)  # Let it start
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Assert
        cleanup_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_cleanup_loop_handles_cleanup_exception(self):
        """Test _run_cleanup_loop handles exceptions in cleanup function."""
        # Arrange
        cleanup_func = AsyncMock(side_effect=Exception("Cleanup failed"))

        # Act - run one iteration then cancel
        task = asyncio.create_task(self.coordinator._run_cleanup_loop(cleanup_func))
        await asyncio.sleep(0.1)  # Let it start and fail
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Assert
        cleanup_func.assert_called_once()
        # Should continue running despite exception

    @pytest.mark.asyncio
    async def test_run_cleanup_loop_handles_sleep_cancellation(self):
        """Test _run_cleanup_loop handles sleep cancellation gracefully."""
        # Arrange
        cleanup_func = AsyncMock()

        # Act - start task and cancel during sleep
        task = asyncio.create_task(self.coordinator._run_cleanup_loop(cleanup_func))
        await asyncio.sleep(0.1)  # Let cleanup run
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Assert
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_active_task_and_clears_state(self):
        """Test shutdown cancels active cleanup task and clears all state."""
        # Arrange
        cleanup_func = AsyncMock()
        await self.coordinator.register_cleanup_task(cleanup_func)
        await self.coordinator.register_session_id("session1")

        # Act
        await self.coordinator.shutdown()

        # Assert
        assert self.coordinator._active_cleanup_task is None
        assert len(self.coordinator._registered_tasks) == 0
        assert len(self.coordinator._active_session_ids) == 0

    @pytest.mark.asyncio
    async def test_shutdown_handles_no_active_task(self):
        """Test shutdown works when no active cleanup task exists."""
        # Arrange
        await self.coordinator.register_session_id("session1")

        # Act
        await self.coordinator.shutdown()

        # Assert
        assert self.coordinator._active_cleanup_task is None
        assert len(self.coordinator._registered_tasks) == 0
        assert len(self.coordinator._active_session_ids) == 0

    @pytest.mark.asyncio
    async def test_shutdown_handles_already_cancelled_task(self):
        """Test shutdown handles already cancelled cleanup task."""
        # Arrange
        cleanup_func = AsyncMock()
        await self.coordinator.register_cleanup_task(cleanup_func)
        # Cancel the task to simulate it being done
        if self.coordinator._active_cleanup_task:
            self.coordinator._active_cleanup_task.cancel()
            try:
                await self.coordinator._active_cleanup_task
            except asyncio.CancelledError:
                pass

        # Act
        await self.coordinator.shutdown()

        # Assert
        assert len(self.coordinator._registered_tasks) == 0
        assert len(self.coordinator._active_session_ids) == 0