"""
Unit tests for HookManager.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, call, patch

from src.auth_token.hook_manager import HookManager


class TestHookManager:
    """Test class for HookManager functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_manager = Mock()
        self.hook_manager = HookManager(self.mock_manager)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_register_update_hook_adds_hook(self):
        """Test register_update_hook adds hook to update hooks dict."""
        # Arrange
        async def test_hook():
            pass

        # Act
        await self.hook_manager.register_update_hook("testuser", test_hook)

        # Assert
        assert "testuser" in self.hook_manager._update_hooks
        assert test_hook in self.hook_manager._update_hooks["testuser"]

    @pytest.mark.asyncio
    async def test_register_update_hook_multiple_hooks_same_user(self):
        """Test register_update_hook allows multiple hooks for same user."""
        # Arrange
        async def hook1():
            pass

        async def hook2():
            pass

        # Act
        await self.hook_manager.register_update_hook("testuser", hook1)
        await self.hook_manager.register_update_hook("testuser", hook2)

        # Assert
        assert len(self.hook_manager._update_hooks["testuser"]) == 2
        assert hook1 in self.hook_manager._update_hooks["testuser"]
        assert hook2 in self.hook_manager._update_hooks["testuser"]

    @pytest.mark.asyncio
    async def test_register_invalidation_hook_adds_hook(self):
        """Test register_invalidation_hook adds hook to invalidation hooks dict."""
        # Arrange
        async def test_hook():
            pass

        # Act
        await self.hook_manager.register_invalidation_hook("testuser", test_hook)

        # Assert
        assert "testuser" in self.hook_manager._invalidation_hooks
        assert test_hook in self.hook_manager._invalidation_hooks["testuser"]

    @pytest.mark.asyncio
    async def test_register_invalidation_hook_multiple_hooks_same_user(self):
        """Test register_invalidation_hook allows multiple hooks for same user."""
        # Arrange
        async def hook1():
            pass

        async def hook2():
            pass

        # Act
        await self.hook_manager.register_invalidation_hook("testuser", hook1)
        await self.hook_manager.register_invalidation_hook("testuser", hook2)

        # Assert
        assert len(self.hook_manager._invalidation_hooks["testuser"]) == 2

    @pytest.mark.asyncio
    async def test_maybe_fire_update_hook_no_change_does_nothing(self):
        """Test maybe_fire_update_hook does nothing when token didn't change."""
        # Arrange
        async def test_hook():
            pass

        await self.hook_manager.register_update_hook("testuser", test_hook)

        # Act
        await self.hook_manager.maybe_fire_update_hook("testuser", token_changed=False)

        # Assert - No tasks should be created
        assert len(self.hook_manager._hook_tasks) == 0

    @pytest.mark.asyncio
    async def test_maybe_fire_update_hook_creates_task_when_changed(self):
        """Test maybe_fire_update_hook creates task when token changed."""
        # Arrange
        hook_mock = AsyncMock()
        await self.hook_manager.register_update_hook("testuser", hook_mock)

        # Act
        await self.hook_manager.maybe_fire_update_hook("testuser", token_changed=True)

        # Assert
        assert len(self.hook_manager._hook_tasks) == 1
        hook_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_maybe_fire_update_hook_handles_exceptions(self):
        """Test maybe_fire_update_hook handles hook execution exceptions."""
        # Arrange
        async def failing_hook():
            raise ValueError("Hook failed")

        await self.hook_manager.register_update_hook("testuser", failing_hook)

        # Act
        await self.hook_manager.maybe_fire_update_hook("testuser", token_changed=True)

        # Assert
        assert len(self.hook_manager._hook_tasks) == 1
        task = self.hook_manager._hook_tasks[0]
        # Wait for task to complete
        await asyncio.sleep(0)
        assert task.done()
        assert task.exception() is not None
        assert isinstance(task.exception(), ValueError)
        assert str(task.exception()) == "Hook failed"

    @pytest.mark.asyncio
    async def test_maybe_fire_invalidation_hook_creates_task(self):
        """Test maybe_fire_invalidation_hook creates task for invalidation."""
        # Arrange
        hook_mock = AsyncMock()
        await self.hook_manager.register_invalidation_hook("testuser", hook_mock)

        # Act
        await self.hook_manager.maybe_fire_invalidation_hook("testuser")

        # Assert
        assert len(self.hook_manager._hook_tasks) == 1
        hook_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_maybe_fire_invalidation_hook_no_hooks_registered(self):
        """Test maybe_fire_invalidation_hook does nothing when no hooks registered."""
        # Act
        await self.hook_manager.maybe_fire_invalidation_hook("testuser")

        # Assert
        assert len(self.hook_manager._hook_tasks) == 0

    @pytest.mark.asyncio
    async def test_create_retained_task_adds_to_hook_tasks(self):
        """Test _create_retained_task adds task to hook_tasks list."""
        # Arrange
        async def test_coro():
            return "done"

        # Act
        task = await self.hook_manager._create_retained_task(test_coro(), category="test")

        # Assert
        assert task in self.hook_manager._hook_tasks
        assert len(self.hook_manager._hook_tasks) == 1

    @pytest.mark.asyncio
    async def test_remove_hook_task_removes_completed_task(self):
        """Test _remove_hook_task removes completed task from hook_tasks."""
        # Arrange
        async def test_coro():
            return "done"

        task = await self.hook_manager._create_retained_task(test_coro(), category="test")

        # Wait for task to complete
        await task

        # Act - This should be called by the done callback
        # We simulate it
        await self.hook_manager._remove_hook_task(task, "test")

        # Assert
        assert task not in self.hook_manager._hook_tasks
        assert len(self.hook_manager._hook_tasks) == 0

    @pytest.mark.asyncio
    async def test_remove_hook_task_logs_exceptions(self):
        """Test _remove_hook_task logs exceptions from failed tasks."""
        # Arrange
        async def failing_coro():
            raise ValueError("Task failed")

        task = await self.hook_manager._create_retained_task(failing_coro(), category="test")

        # Wait for task to complete with exception
        try:
            await task
        except ValueError:
            pass  # Expected

        # Act
        with patch('src.auth_token.hook_manager.logging') as mock_logging:
            await self.hook_manager._remove_hook_task(task, "test")

        # Assert
        mock_logging.debug.assert_called()
        assert "Task failed" in str(mock_logging.debug.call_args)

    @pytest.mark.asyncio
    async def test_remove_hook_task_handles_cancelled_task(self):
        """Test _remove_hook_task handles cancelled tasks."""
        # Arrange
        async def test_coro():
            await asyncio.sleep(10)  # Long running

        task = await self.hook_manager._create_retained_task(test_coro(), category="test")
        task.cancel()

        # Wait for cancellation
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Act
        await self.hook_manager._remove_hook_task(task, "test")

        # Assert
        assert task not in self.hook_manager._hook_tasks