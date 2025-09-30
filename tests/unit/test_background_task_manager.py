"""
Unit tests for BackgroundTaskManager.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.auth_token.background_task_manager import BackgroundTaskManager
from src.auth_token.client import TokenOutcome


class TestBackgroundTaskManager:
    """Test class for BackgroundTaskManager functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_manager = Mock()
        self.task_manager = BackgroundTaskManager(self.mock_manager)

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_start_creates_task_when_not_running(self):
        """Test start creates background task when not already running."""
        # Act
        await self.task_manager.start()

        # Assert
        assert self.task_manager.running is True
        assert self.task_manager.task is not None

    @pytest.mark.asyncio
    async def test_start_does_nothing_when_already_running(self):
        """Test start does nothing when already running."""
        # Arrange
        await self.task_manager.start()
        original_task = self.task_manager.task

        # Act
        await self.task_manager.start()

        # Assert
        assert self.task_manager.running is True
        assert self.task_manager.task is original_task

    @pytest.mark.asyncio
    async def test_start_cancels_stale_task(self):
        """Test start cancels stale background task before creating new one."""
        # Arrange
        mock_task = AsyncMock()
        mock_task.done = False
        mock_task.cancel = Mock()  # cancel is synchronous
        self.task_manager.task = mock_task

        # Act
        await self.task_manager.start()

        # Assert
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_task_when_running(self):
        """Test stop cancels background task when running."""
        # Arrange
        await self.task_manager.start()
        mock_task = Mock()
        self.task_manager.task = mock_task

        # Act
        with patch('asyncio.wait_for', new_callable=AsyncMock):
            await self.task_manager.stop()

        # Assert
        assert self.task_manager.running is False
        assert self.task_manager.task is None
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_does_nothing_when_not_running(self):
        """Test stop does nothing when not running."""
        # Act
        await self.task_manager.stop()

        # Assert
        assert self.task_manager.running is False
        assert self.task_manager.task is None

    @pytest.mark.asyncio
    async def test_background_refresh_loop_processes_users(self):
        """Test _background_refresh_loop processes all users."""
        # Arrange
        self.mock_manager._tokens_lock = AsyncMock()
        self.mock_manager.tokens = {"user1": Mock(), "user2": Mock()}
        self.mock_manager._paused_users = []

        mock_info1 = Mock()
        mock_info2 = Mock()
        self.mock_manager.tokens = {"user1": mock_info1, "user2": mock_info2}

        with patch.object(self.task_manager, '_process_single_background', new_callable=AsyncMock) as mock_process:
            async def mock_wait_for(coro, timeout=None):  # noqa: ASYNC109
                self.task_manager.running = False
                return None

            with patch('asyncio.wait_for', mock_wait_for), patch('asyncio.sleep', new_callable=AsyncMock):
                # Stop after one iteration
                self.task_manager.running = True

                # Act
                await self.task_manager._background_refresh_loop()

        # Assert
        assert mock_process.call_count == 2
        mock_process.assert_any_call("user1", mock_info1, force_proactive=False, drift_compensation=pytest.approx(0.0, abs=1e-5))
        mock_process.assert_any_call("user2", mock_info2, force_proactive=False, drift_compensation=pytest.approx(0.0, abs=1e-5))

    @pytest.mark.asyncio
    async def test_background_refresh_loop_handles_drift_correction(self):
        """Test _background_refresh_loop applies drift correction."""
        # Arrange
        self.mock_manager._tokens_lock = AsyncMock()
        self.mock_manager.tokens = {}
        self.mock_manager._paused_users = []

        with (
            patch('time.time', side_effect=[100, 103.5]),  # 3.5s drift
            patch.object(self.task_manager, '_process_single_background', new_callable=AsyncMock),
            patch('asyncio.wait_for', side_effect=lambda *args, **kwargs: None)
        ):
            # Stop after one iteration
            self.task_manager.running = False

            # Act
            await self.task_manager._background_refresh_loop()

        # Drift of 3.5s should trigger consecutive_drift increment


    @pytest.mark.asyncio
    async def test_process_single_background_critical_health_forces_refresh(self):
        """Test _process_single_background forces refresh for critical health."""
        # Arrange
        mock_info = Mock()
        self.mock_manager.validator.assess_token_health.return_value = "critical"
        self.mock_manager.validator.remaining_seconds.return_value = 3600
        self.mock_manager.refresher.ensure_fresh = AsyncMock(side_effect=lambda *args, **kwargs: TokenOutcome.REFRESHED)

        # Act
        await self.task_manager._process_single_background("testuser", mock_info)

        # Assert
        self.mock_manager.refresher.ensure_fresh.assert_called_once_with("testuser", force_refresh=True)

    @pytest.mark.asyncio
    async def test_process_single_background_handles_unknown_expiry(self):
        """Test _process_single_background handles unknown expiry."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = None
        self.mock_manager.validator.assess_token_health.return_value = "healthy"
        self.mock_manager.validator.remaining_seconds.return_value = None

        async def mock_handle_unknown_expiry(username):
            pass

        with patch.object(self.task_manager, '_handle_unknown_expiry', mock_handle_unknown_expiry):
            # Act
            await self.task_manager._process_single_background("testuser", mock_info)

    @pytest.mark.asyncio
    async def test_process_single_background_handles_expired_tokens(self):
        """Test _process_single_background handles expired tokens."""
        # Arrange
        mock_info = Mock()
        mock_info.refresh_lock = AsyncMock()
        mock_info.expiry = datetime.now() - timedelta(hours=1)
        self.mock_manager.validator.assess_token_health.return_value = "healthy"
        self.mock_manager.validator.remaining_seconds.return_value = -3600

        with patch.object(self.task_manager, '_maybe_periodic_or_unknown_resolution', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = -3600

            with patch.object(self.task_manager, '_calculate_refresh_threshold') as mock_calc:
                mock_calc.return_value = 1800

                self.mock_manager.refresher.ensure_fresh = AsyncMock()

                # Act
                await self.task_manager._process_single_background("testuser", mock_info)

        # Assert
        self.mock_manager.refresher.ensure_fresh.assert_called_once_with("testuser", force_refresh=True)

    @pytest.mark.asyncio
    async def test_process_single_background_triggers_refresh_when_needed(self):
        """Test _process_single_background triggers refresh when threshold reached."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = datetime.now() + timedelta(minutes=30)
        self.mock_manager.validator.assess_token_health.return_value = "healthy"
        self.mock_manager.validator.remaining_seconds.return_value = 1800

        with patch.object(self.task_manager, '_maybe_periodic_or_unknown_resolution', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = 1800

            with patch.object(self.task_manager, '_calculate_refresh_threshold') as mock_calc:
                mock_calc.return_value = 1900  # Higher than remaining

                self.mock_manager.refresher.ensure_fresh = AsyncMock()

                # Act
                await self.task_manager._process_single_background("testuser", mock_info)

        # Assert
        self.mock_manager.refresher.ensure_fresh.assert_called_once_with("testuser")

    @pytest.mark.asyncio
    async def test_maybe_periodic_or_unknown_resolution_handles_unknown_expiry(self):
        """Test _maybe_periodic_or_unknown_resolution handles unknown expiry."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = None

        async def mock_handle_unknown_expiry(username):
            pass

        with patch.object(self.task_manager, '_handle_unknown_expiry', mock_handle_unknown_expiry):
            # Act
            result = await self.task_manager._maybe_periodic_or_unknown_resolution("testuser", mock_info, None)

        # Assert
        assert result is not None

    @pytest.mark.asyncio
    async def test_maybe_periodic_or_unknown_resolution_skips_recent_validation(self):
        """Test _maybe_periodic_or_unknown_resolution skips recent validation."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = datetime.now() + timedelta(hours=1)
        mock_info.last_validation = 1000.0

        with patch('time.time', return_value=1001.0):  # Recent validation
            # Act
            result = await self.task_manager._maybe_periodic_or_unknown_resolution("testuser", mock_info, 3600)

        # Assert
        assert result == 3600

    @pytest.mark.asyncio
    async def test_maybe_periodic_or_unknown_resolution_performs_validation(self):
        """Test _maybe_periodic_or_unknown_resolution performs periodic validation."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = datetime.now() + timedelta(hours=1)
        mock_info.last_validation = 0

        self.mock_manager.validator.validate = AsyncMock(return_value=TokenOutcome.VALID)
        self.mock_manager.validator.remaining_seconds.return_value = 3500

        with (
            patch('time.time', return_value=2000.0),
            patch('src.auth_token.background_task_manager.format_duration', return_value="58m")
        ):
                # Act
                result = await self.task_manager._maybe_periodic_or_unknown_resolution("testuser", mock_info, 3600)

        # Assert
        assert result == 3500

    @pytest.mark.asyncio
    async def test_handle_unknown_expiry_attempts_refresh(self):
        """Test _handle_unknown_expiry attempts refresh and tracks attempts."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = None
        mock_info.forced_unknown_attempts = 0

        self.mock_manager._tokens_lock = AsyncMock()
        self.mock_manager.tokens = {"testuser": mock_info}
        self.mock_manager.refresher.ensure_fresh = AsyncMock(return_value=TokenOutcome.VALID)

        # Act
        with patch('asyncio.sleep'):
            await self.task_manager._handle_unknown_expiry("testuser")

        # Assert
        assert self.mock_manager.refresher.ensure_fresh.call_count == 2
        self.mock_manager.refresher.ensure_fresh.assert_any_call("testuser", force_refresh=False)
        self.mock_manager.refresher.ensure_fresh.assert_any_call("testuser", force_refresh=True)

    @pytest.mark.asyncio
    async def test_handle_unknown_expiry_forced_refresh_on_failure(self):
        """Test _handle_unknown_expiry performs forced refresh after initial failure."""
        # Arrange
        mock_info = Mock()
        mock_info.expiry = None
        mock_info.forced_unknown_attempts = 2

        self.mock_manager._tokens_lock = AsyncMock()
        self.mock_manager.tokens = {"testuser": mock_info}
        self.mock_manager.refresher.ensure_fresh = AsyncMock(side_effect=[TokenOutcome.FAILED, TokenOutcome.REFRESHED])

        # Act
        with patch('asyncio.sleep'):
            await self.task_manager._handle_unknown_expiry("testuser")

        # Assert
        assert self.mock_manager.refresher.ensure_fresh.call_count == 2

    def test_calculate_refresh_threshold_normal_case(self):
        """Test _calculate_refresh_threshold normal case."""
        # Act
        result = self.task_manager._calculate_refresh_threshold(force_proactive=False, drift_compensation=0)

        # Assert
        # Should return TOKEN_REFRESH_THRESHOLD_SECONDS
        from src.constants import TOKEN_REFRESH_THRESHOLD_SECONDS
        assert result == TOKEN_REFRESH_THRESHOLD_SECONDS

    def test_calculate_refresh_threshold_with_drift(self):
        """Test _calculate_refresh_threshold with drift compensation."""
        # Act
        result = self.task_manager._calculate_refresh_threshold(force_proactive=False, drift_compensation=100)

        # Assert
        from src.constants import TOKEN_REFRESH_THRESHOLD_SECONDS
        expected = TOKEN_REFRESH_THRESHOLD_SECONDS - min(100 * 0.5, TOKEN_REFRESH_THRESHOLD_SECONDS * 0.3)
        assert result == expected

    def test_calculate_refresh_threshold_force_proactive(self):
        """Test _calculate_refresh_threshold with force_proactive."""
        # Act
        result = self.task_manager._calculate_refresh_threshold(force_proactive=True, drift_compensation=0)

        # Assert
        from src.constants import TOKEN_REFRESH_THRESHOLD_SECONDS
        assert result == TOKEN_REFRESH_THRESHOLD_SECONDS * 1.5

    def test_should_force_refresh_due_to_drift_true(self):
        """Test _should_force_refresh_due_to_drift returns True when conditions met."""
        # Act
        result = self.task_manager._should_force_refresh_due_to_drift(
            force_proactive=True, drift_compensation=70, remaining=3601
        )

        # Assert
        assert result is True

    def test_should_force_refresh_due_to_drift_false(self):
        """Test _should_force_refresh_due_to_drift returns False when conditions not met."""
        # Act
        result = self.task_manager._should_force_refresh_due_to_drift(
            force_proactive=False, drift_compensation=30, remaining=7200
        )

        # Assert
        assert result is False

    def test_log_remaining_detail_logs_debug_info(self):
        """Test _log_remaining_detail logs appropriate debug information."""
        # Arrange
        with (
            patch('src.auth_token.background_task_manager.format_duration', return_value="1h 30m"),
            patch('src.auth_token.background_task_manager.logging') as mock_logging
        ):
                # Act
                self.task_manager._log_remaining_detail("testuser", 5400)

        # Assert
        mock_logging.debug.assert_called_once()
        log_call = str(mock_logging.debug.call_args)
        assert "testuser" in log_call
        assert "1h 30m" in log_call

    def test_task_health_status_initialization(self):
        """Test TaskHealthStatus initializes with correct default values."""
        from src.auth_token.background_task_manager import TaskHealthStatus

        # Act
        health = TaskHealthStatus()

        # Assert
        assert health.last_success_time is None
        assert health.last_failure_time is None
        assert health.consecutive_failures == 0
        assert health.total_failures == 0
        assert health.is_healthy is True
        assert health.last_error_message is None

    @pytest.mark.asyncio
    async def test_record_success_updates_health_status(self):
        """Test _record_success updates health status correctly."""
        # Arrange
        import time
        start_time = time.time()

        # Act
        await self.task_manager._record_success()

        # Assert
        health = self.task_manager.health
        assert health.last_success_time is not None
        assert health.last_success_time >= start_time
        assert health.consecutive_failures == 0
        assert health.is_healthy is True
        assert health.last_error_message is None

    @pytest.mark.asyncio
    async def test_record_failure_updates_health_status_first_failure(self):
        """Test _record_failure updates health status for first failure."""
        # Arrange
        import time
        start_time = time.time()
        test_error = RuntimeError("Test error")

        # Act
        await self.task_manager._record_failure(test_error)

        # Assert
        health = self.task_manager.health
        assert health.last_failure_time is not None
        assert health.last_failure_time >= start_time
        assert health.consecutive_failures == 1
        assert health.total_failures == 1
        assert health.is_healthy is True  # Still healthy after 1 failure
        assert health.last_error_message == "Test error"

    @pytest.mark.asyncio
    async def test_record_failure_updates_health_status_multiple_failures(self):
        """Test _record_failure marks unhealthy after 3 consecutive failures."""
        # Arrange
        test_error = RuntimeError("Test error")

        # Act - Record 3 failures
        await self.task_manager._record_failure(test_error)
        await self.task_manager._record_failure(test_error)
        await self.task_manager._record_failure(test_error)

        # Assert
        health = self.task_manager.health
        assert health.consecutive_failures == 3
        assert health.total_failures == 3
        assert health.is_healthy is False
        assert health.last_error_message == "Test error"

    @pytest.mark.asyncio
    async def test_record_failure_resets_on_success(self):
        """Test _record_failure counter resets after success."""
        # Arrange
        test_error = RuntimeError("Test error")

        # Act - Record 2 failures, then success, then 1 more failure
        await self.task_manager._record_failure(test_error)
        await self.task_manager._record_failure(test_error)
        await self.task_manager._record_success()
        await self.task_manager._record_failure(test_error)

        # Assert
        health = self.task_manager.health
        assert health.consecutive_failures == 1  # Reset after success
        assert health.total_failures == 3  # But total still accumulates
        assert health.is_healthy is True  # Back to healthy

    def test_get_health_status_returns_health_object(self):
        """Test get_health_status returns the health status object."""
        # Act
        health = self.task_manager.get_health_status()

        # Assert
        assert health is self.task_manager.health
        assert hasattr(health, 'last_success_time')
        assert hasattr(health, 'consecutive_failures')
        assert hasattr(health, 'is_healthy')

    @pytest.mark.asyncio
    async def test_background_refresh_loop_records_success_on_successful_iteration(self):
        """Test _background_refresh_loop records success for successful iterations."""
        # Arrange
        self.mock_manager._tokens_lock = AsyncMock()
        self.mock_manager.tokens = {}
        self.mock_manager._paused_users = []

        with patch.object(self.task_manager, '_process_single_background', new_callable=AsyncMock):
            async def mock_wait_for(coro, timeout=None):  # noqa: ASYNC109
                self.task_manager.running = False
                return None

            with patch('asyncio.wait_for', mock_wait_for), patch('asyncio.sleep', new_callable=AsyncMock):
                # Stop after one iteration
                self.task_manager.running = True

                # Act
                await self.task_manager._background_refresh_loop()

        # Assert - Health should record success
        health = self.task_manager.health
        assert health.last_success_time is not None
        assert health.consecutive_failures == 0
        assert health.is_healthy is True

    @pytest.mark.asyncio
    async def test_background_refresh_loop_records_failure_on_failed_iteration(self):
        """Test _background_refresh_loop records failure when user processing fails."""
        # Arrange
        self.mock_manager._tokens_lock = AsyncMock()
        self.mock_manager.tokens = {"user1": Mock()}
        self.mock_manager._paused_users = []

        with patch.object(self.task_manager, '_process_single_background', new_callable=AsyncMock) as mock_process:
            mock_process.side_effect = Exception("Processing failed")

            async def mock_wait_for(coro, timeout=None):  # noqa: ASYNC109
                self.task_manager.running = False
                if hasattr(coro, '__await__'):
                    task = asyncio.create_task(coro)
                    task.cancel()
                return None

            with patch('asyncio.wait_for', mock_wait_for):
                # Stop after one iteration
                self.task_manager.running = True

                # Act
                await self.task_manager._background_refresh_loop()

        # Assert - Health should record failure
        health = self.task_manager.health
        assert health.last_failure_time is not None
        assert health.consecutive_failures == 1
        assert health.last_error_message == "One or more user background refreshes failed"
