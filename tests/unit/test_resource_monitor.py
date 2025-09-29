"""
Unit tests for ResourceMonitor.
"""

import asyncio
import gc
import os
import time
from unittest.mock import AsyncMock, Mock, mock_open, patch

import pytest

from src.utils.resource_monitor import ResourceMonitor, ResourceSnapshot


class TestResourceMonitor:
    """Test class for ResourceMonitor functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        self.monitor = ResourceMonitor()

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_start_monitoring_creates_task_when_not_running(self):
        """Test start_monitoring creates monitoring task when not already running."""
        # Act
        await self.monitor.start_monitoring()

        # Assert
        assert self.monitor._monitoring is True
        assert self.monitor._monitor_task is not None

    @pytest.mark.asyncio
    async def test_start_monitoring_does_nothing_when_already_running(self):
        """Test start_monitoring does nothing when already running."""
        # Arrange
        await self.monitor.start_monitoring()
        original_task = self.monitor._monitor_task

        # Act
        await self.monitor.start_monitoring()

        # Assert
        assert self.monitor._monitoring is True
        assert self.monitor._monitor_task is original_task

    @pytest.mark.asyncio
    async def test_stop_monitoring_cancels_task_when_running(self):
        """Test stop_monitoring cancels monitoring task when running."""
        # Arrange
        await self.monitor.start_monitoring()

        # Act
        await self.monitor.stop_monitoring()

        # Assert
        assert self.monitor._monitoring is False
        assert self.monitor._monitor_task is not None  # Task exists but is cancelled
        assert self.monitor._monitor_task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_monitoring_does_nothing_when_not_running(self):
        """Test stop_monitoring does nothing when not running."""
        # Act
        await self.monitor.stop_monitoring()

        # Assert
        assert self.monitor._monitoring is False
        assert self.monitor._monitor_task is None

    def test_take_snapshot_success(self):
        """Test _take_snapshot with successful file operations."""
        # Arrange
        statm_content = "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52"
        tcp_content = "  0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1 ffff88003d8b6c00 100 0 0 10 0\n"
        tcp6_content = "  0: 00000000000000000000000000000000:0016 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12346 1 ffff88003d8b6c00 100 0 0 10 0\n"

        def mock_open_side_effect(file, mode='r', **kwargs):
            if '/proc/self/statm' in str(file):
                return mock_open(read_data=statm_content).return_value
            elif '/proc/net/tcp' in str(file):
                return mock_open(read_data=tcp_content).return_value
            elif '/proc/net/tcp6' in str(file):
                return mock_open(read_data=tcp6_content).return_value
            else:
                return mock_open().return_value

        with (
            patch('builtins.open', side_effect=mock_open_side_effect) as mock_file,
            patch('os.listdir', return_value=['0', '1', '2', '3', '4']) as mock_listdir,
            patch('os.sysconf', return_value=4096) as mock_sysconf,
            patch('asyncio.all_tasks', return_value=[Mock()]) as mock_all_tasks,
            patch('gc.get_objects', return_value=[1, 2, 3]) as mock_gc,
            patch('time.monotonic', return_value=123456.789) as mock_time
        ):
            # Act
            snapshot = self.monitor._take_snapshot()

        # Assert
        assert isinstance(snapshot, ResourceSnapshot)
        assert snapshot.timestamp == 123456.789
        # Memory calculation: resident_pages (2) * page_size (4096) / 1024 / 1024 = 8192 / 1024 / 1024 = 0.0078125 MB
        assert snapshot.memory_mb == 2 * 4096 / 1024 / 1024
        assert snapshot.open_files == 5  # len(['0', '1', '2', '3', '4'])
        assert snapshot.connections == 0  # No headers in mock data, so 1 + 1 - 2 = 0
        assert snapshot.gc_objects == 3
        assert snapshot.asyncio_tasks == 1

        # Verify file operations
        assert mock_file.call_count == 3  # statm, tcp, tcp6
        mock_listdir.assert_called_once_with('/proc/self/fd')
        mock_sysconf.assert_called_once_with('SC_PAGE_SIZE')

    def test_take_snapshot_handles_file_errors(self):
        """Test _take_snapshot handles file operation errors gracefully."""
        # Arrange
        with (
            patch('builtins.open', side_effect=OSError("File not found")) as mock_file,
            patch('os.listdir', side_effect=OSError("Permission denied")) as mock_listdir,
            patch('os.sysconf', return_value=4096) as mock_sysconf,
            patch('asyncio.all_tasks', return_value=[]) as mock_all_tasks,
            patch('gc.get_objects', return_value=[]) as mock_gc,
            patch('time.monotonic', return_value=123456.789) as mock_time
        ):
            # Act
            snapshot = self.monitor._take_snapshot()

        # Assert
        assert isinstance(snapshot, ResourceSnapshot)
        assert snapshot.timestamp == 123456.789
        assert snapshot.memory_mb == 0.0
        assert snapshot.open_files == 0
        assert snapshot.connections == 0
        assert snapshot.gc_objects == 0
        assert snapshot.asyncio_tasks == 0

    def test_take_snapshot_handles_value_errors(self):
        """Test _take_snapshot handles value parsing errors gracefully."""
        # Arrange
        invalid_statm_content = "invalid data"

        with (
            patch('builtins.open', mock_open(read_data=invalid_statm_content)) as mock_file,
            patch('os.listdir', return_value=['0', '1']) as mock_listdir,
            patch('os.sysconf', return_value=4096) as mock_sysconf,
            patch('asyncio.all_tasks', return_value=[Mock()]) as mock_all_tasks,
            patch('gc.get_objects', return_value=[1]) as mock_gc,
            patch('time.monotonic', return_value=123456.789) as mock_time
        ):
            # Act
            snapshot = self.monitor._take_snapshot()

        # Assert
        assert isinstance(snapshot, ResourceSnapshot)
        assert snapshot.memory_mb == 0.0  # Should default to 0.0 on ValueError
        assert snapshot.open_files == 2
        assert snapshot.connections == 0
        assert snapshot.gc_objects == 1
        assert snapshot.asyncio_tasks == 1

    def test_take_snapshot_handles_runtime_error_in_asyncio(self):
        """Test _take_snapshot handles RuntimeError from asyncio.all_tasks gracefully."""
        # Arrange
        statm_content = "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52"

        with (
            patch('builtins.open', mock_open(read_data=statm_content)) as mock_file,
            patch('os.listdir', return_value=['0']) as mock_listdir,
            patch('os.sysconf', return_value=4096) as mock_sysconf,
            patch('asyncio.all_tasks', side_effect=RuntimeError("No event loop")) as mock_all_tasks,
            patch('gc.get_objects', return_value=[1, 2]) as mock_gc,
            patch('time.monotonic', return_value=123456.789) as mock_time
        ):
            # Act
            snapshot = self.monitor._take_snapshot()

        # Assert
        assert isinstance(snapshot, ResourceSnapshot)
        assert snapshot.asyncio_tasks == 0  # Should default to 0 on RuntimeError

    def test_get_latest_snapshot_returns_none_when_empty(self):
        """Test get_latest_snapshot returns None when no snapshots exist."""
        # Act
        result = self.monitor.get_latest_snapshot()

        # Assert
        assert result is None

    def test_get_latest_snapshot_returns_latest(self):
        """Test get_latest_snapshot returns the most recent snapshot."""
        # Arrange
        snapshot1 = ResourceSnapshot(timestamp=100.0, memory_mb=10.0, open_files=5, connections=2, gc_objects=100, asyncio_tasks=3)
        snapshot2 = ResourceSnapshot(timestamp=200.0, memory_mb=15.0, open_files=6, connections=3, gc_objects=110, asyncio_tasks=4)

        self.monitor.metrics.snapshots = [snapshot1, snapshot2]

        # Act
        result = self.monitor.get_latest_snapshot()

        # Assert
        assert result is snapshot2

    def test_force_garbage_collection_calls_gc_collect(self):
        """Test force_garbage_collection calls gc.collect."""
        # Arrange
        with patch('gc.collect') as mock_gc_collect:
            # Act
            self.monitor.force_garbage_collection()

        # Assert
        mock_gc_collect.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_memory_cleanup_calls_force_gc(self):
        """Test _trigger_memory_cleanup calls force_garbage_collection."""
        # Arrange
        snapshot = ResourceSnapshot(timestamp=100.0, memory_mb=50.0, open_files=5, connections=2, gc_objects=100, asyncio_tasks=3)
        self.monitor.metrics.snapshots = [snapshot]

        with patch.object(self.monitor, 'force_garbage_collection') as mock_force_gc:
            # Act
            await self.monitor._trigger_memory_cleanup()

        # Assert
        mock_force_gc.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_connection_cleanup_calls_force_gc(self):
        """Test _trigger_connection_cleanup calls force_garbage_collection."""
        # Arrange
        with patch.object(self.monitor, 'force_garbage_collection') as mock_force_gc:
            # Act
            await self.monitor._trigger_connection_cleanup()

        # Assert
        mock_force_gc.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_task_cleanup_handles_high_task_count(self):
        """Test _trigger_task_cleanup handles high task count appropriately."""
        # Arrange
        with patch('asyncio.all_tasks', return_value=[Mock() for _ in range(60)]) as mock_all_tasks:
            # Act
            await self.monitor._trigger_task_cleanup()

        # Assert
        mock_all_tasks.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_task_cleanup_handles_normal_task_count(self):
        """Test _trigger_task_cleanup does nothing for normal task count."""
        # Arrange
        with patch('asyncio.all_tasks', return_value=[Mock() for _ in range(40)]) as mock_all_tasks:
            # Act
            await self.monitor._trigger_task_cleanup()

        # Assert
        mock_all_tasks.assert_called_once()


class TestResourceMetrics:
    """Test class for ResourceMetrics functionality."""

    def setup_method(self):
        """Setup method called before each test."""
        from src.utils.resource_monitor import ResourceMetrics
        self.metrics = ResourceMetrics()

    def test_add_snapshot_maintains_max_snapshots(self):
        """Test add_snapshot maintains maximum snapshot count."""
        # Arrange
        self.metrics.max_snapshots = 3
        snapshots = [
            ResourceSnapshot(timestamp=float(i), memory_mb=10.0, open_files=5, connections=2, gc_objects=100, asyncio_tasks=3)
            for i in range(5)
        ]

        # Act
        for snapshot in snapshots:
            self.metrics.add_snapshot(snapshot)

        # Assert
        assert len(self.metrics.snapshots) == 3
        assert self.metrics.snapshots[0].timestamp == 2.0  # Oldest remaining
        assert self.metrics.snapshots[-1].timestamp == 4.0  # Newest

    def test_detect_memory_leak_no_snapshots(self):
        """Test detect_memory_leak returns False with insufficient snapshots."""
        # Act
        result = self.metrics.detect_memory_leak()

        # Assert
        assert result is False

    def test_detect_memory_leak_with_leak(self):
        """Test detect_memory_leak detects memory leak."""
        # Arrange
        snapshots = [
            ResourceSnapshot(timestamp=float(i), memory_mb=10.0 + i * 30.0, open_files=5, connections=2, gc_objects=100, asyncio_tasks=3)
            for i in range(6)
        ]
        self.metrics.snapshots = snapshots

        # Act
        result = self.metrics.detect_memory_leak()

        # Assert
        assert result is True  # 150MB increase over baseline

    def test_detect_memory_leak_no_leak(self):
        """Test detect_memory_leak returns False when no leak detected."""
        # Arrange
        snapshots = [
            ResourceSnapshot(timestamp=float(i), memory_mb=10.0, open_files=5, connections=2, gc_objects=100, asyncio_tasks=3)
            for i in range(6)
        ]
        self.metrics.snapshots = snapshots

        # Act
        result = self.metrics.detect_memory_leak()

        # Assert
        assert result is False

    def test_detect_connection_leak_with_leak(self):
        """Test detect_connection_leak detects connection leak."""
        # Arrange
        snapshots = [
            ResourceSnapshot(timestamp=float(i), memory_mb=10.0, open_files=5, connections=2 + i * 10, gc_objects=100, asyncio_tasks=3)
            for i in range(4)
        ]
        self.metrics.snapshots = snapshots

        # Act
        result = self.metrics.detect_connection_leak()

        # Assert
        assert result is True  # 30 connection increase

    def test_detect_connection_leak_no_leak(self):
        """Test detect_connection_leak returns False when no leak detected."""
        # Arrange
        snapshots = [
            ResourceSnapshot(timestamp=float(i), memory_mb=10.0, open_files=5, connections=2, gc_objects=100, asyncio_tasks=3)
            for i in range(4)
        ]
        self.metrics.snapshots = snapshots

        # Act
        result = self.metrics.detect_connection_leak()

        # Assert
        assert result is False

    def test_detect_task_leak_with_leak(self):
        """Test detect_task_leak detects task leak."""
        # Arrange
        snapshots = [
            ResourceSnapshot(timestamp=float(i), memory_mb=10.0, open_files=5, connections=2, gc_objects=100, asyncio_tasks=3 + i * 15)
            for i in range(4)
        ]
        self.metrics.snapshots = snapshots

        # Act
        result = self.metrics.detect_task_leak()

        # Assert
        assert result is True  # 45 task increase

    def test_detect_task_leak_no_leak(self):
        """Test detect_task_leak returns False when no leak detected."""
        # Arrange
        snapshots = [
            ResourceSnapshot(timestamp=float(i), memory_mb=10.0, open_files=5, connections=2, gc_objects=100, asyncio_tasks=3)
            for i in range(4)
        ]
        self.metrics.snapshots = snapshots

        # Act
        result = self.metrics.detect_task_leak()

        # Assert
        assert result is False


class TestGlobalFunctions:
    """Test class for global functions."""

    @patch('src.utils.resource_monitor.ResourceMonitor')
    def test_get_resource_monitor_creates_instance(self, mock_monitor_class):
        """Test get_resource_monitor creates new instance when none exists."""
        # Arrange
        from src.utils.resource_monitor import get_resource_monitor, _resource_monitor
        _resource_monitor = None  # Reset global state
        mock_instance = Mock()
        mock_monitor_class.return_value = mock_instance

        # Act
        result = get_resource_monitor()

        # Assert
        assert result is mock_instance
        mock_monitor_class.assert_called_once()

    @patch('src.utils.resource_monitor.get_resource_monitor')
    @pytest.mark.asyncio
    async def test_start_resource_monitoring_calls_start(self, mock_get_monitor):
        """Test start_resource_monitoring calls start_monitoring on global instance."""
        # Arrange
        mock_monitor = AsyncMock()
        mock_get_monitor.return_value = mock_monitor

        # Act
        from src.utils.resource_monitor import start_resource_monitoring
        await start_resource_monitoring()

        # Assert
        mock_monitor.start_monitoring.assert_called_once()

    @patch('src.utils.resource_monitor.get_resource_monitor')
    @pytest.mark.asyncio
    async def test_stop_resource_monitoring_calls_stop(self, mock_get_monitor):
        """Test stop_resource_monitoring calls stop_monitoring on global instance."""
        # Arrange
        mock_monitor = AsyncMock()
        mock_get_monitor.return_value = mock_monitor

        # Act
        from src.utils.resource_monitor import stop_resource_monitoring
        await stop_resource_monitoring()

        # Assert
        mock_monitor.stop_monitoring.assert_called_once()

    @patch('src.utils.resource_monitor.get_resource_monitor')
    def test_log_resource_usage_with_snapshot(self, mock_get_monitor):
        """Test log_resource_usage logs snapshot data when available."""
        # Arrange
        mock_monitor = Mock()
        snapshot = ResourceSnapshot(timestamp=123456.789, memory_mb=25.5, open_files=10, connections=5, gc_objects=200, asyncio_tasks=8)
        mock_monitor.get_latest_snapshot.return_value = snapshot
        mock_get_monitor.return_value = mock_monitor

        with patch('src.utils.resource_monitor.logging') as mock_logging:
            # Act
            from src.utils.resource_monitor import log_resource_usage
            log_resource_usage()

        # Assert
        mock_logging.info.assert_called_once()
        log_message = str(mock_logging.info.call_args)
        assert "25.5MB" in log_message
        assert "10" in log_message  # open_files
        assert "5" in log_message   # connections
        assert "8" in log_message   # asyncio_tasks

    @patch('src.utils.resource_monitor.get_resource_monitor')
    def test_log_resource_usage_without_snapshot(self, mock_get_monitor):
        """Test log_resource_usage logs debug message when no snapshot available."""
        # Arrange
        mock_monitor = Mock()
        mock_monitor.get_latest_snapshot.return_value = None
        mock_get_monitor.return_value = mock_monitor

        with patch('src.utils.resource_monitor.logging') as mock_logging:
            # Act
            from src.utils.resource_monitor import log_resource_usage
            log_resource_usage()

        # Assert
        mock_logging.debug.assert_called_once_with("No resource snapshot available")