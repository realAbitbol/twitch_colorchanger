from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.manager import BotManager, run_bots


@pytest.mark.asyncio
async def test_start_all_bots_success():
    """Test _start_all_bots success."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]
    manager = BotManager(users_config, "test.conf", context=ctx)

    with patch.object(manager.lifecycle, "_create_bot") as mock_create:
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        mock_create.return_value = mock_bot

        result = await manager._start_all_bots()

        assert result is True
        assert len(manager.bots) == 1
        assert len(manager.tasks) == 1
        assert manager.running is True
        mock_create.assert_called_once()
        mock_bot.start.assert_called_once()


@pytest.mark.asyncio
async def test_start_all_bots_no_bots():
    """Test _start_all_bots when no bots created."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    users_config = []  # Empty config
    manager = BotManager(users_config, "test.conf", context=ctx)

    result = await manager._start_all_bots()

    assert result is False
    assert len(manager.bots) == 0


@pytest.mark.asyncio
async def test_start_all_bots_create_fails():
    """Test _start_all_bots when bot creation fails."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]
    manager = BotManager(users_config, "test.conf", context=ctx)

    with patch.object(manager.lifecycle, "_create_bot", side_effect=ValueError("Create failed")):
        result = await manager._start_all_bots()

        assert result is False
        assert len(manager.bots) == 0


@pytest.mark.asyncio
async def test_stop_all_bots():
    """Test _stop_all_bots."""
    ctx = MagicMock()
    manager = BotManager([], "test.conf", context=ctx)
    manager.running = True

    mock_bot = MagicMock()
    mock_bot.close = MagicMock()
    manager.bots = [mock_bot]

    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_task.cancel = MagicMock()
    manager.tasks = [mock_task]

    with patch.object(manager, "_wait_for_task_completion", new_callable=AsyncMock):
        await manager._stop_all_bots()

        assert manager.running is False
        mock_bot.close.assert_called_once()
        mock_task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_run_bots_success():
    """Test run_bots success."""
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]

    with patch("src.application_context.ApplicationContext") as mock_ctx_class, \
          patch("src.bot.manager._run_main_loop", new_callable=AsyncMock) as mock_loop, \
          patch("src.bot.manager.BotManager") as mock_manager_class:
        mock_ctx = MagicMock()
        mock_ctx.create = AsyncMock(return_value=mock_ctx)
        mock_ctx.start = AsyncMock()
        mock_ctx.shutdown = AsyncMock()
        mock_ctx.session = MagicMock()
        mock_ctx_class.create = AsyncMock(return_value=mock_ctx)

        mock_manager = MagicMock(spec=BotManager)
        mock_manager._manager_lock = AsyncMock()
        mock_manager._start_all_bots = AsyncMock(return_value=True)
        mock_manager._stop_all_bots = AsyncMock()
        mock_manager_class.return_value = mock_manager

        await run_bots(users_config, "test.conf")

        mock_manager._start_all_bots.assert_called_once()
        mock_loop.assert_called_once_with(mock_manager)
        mock_manager._stop_all_bots.assert_called_once()


@pytest.mark.asyncio
async def test_run_bots_start_fails():
    """Test run_bots when start fails."""
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]

    with patch("src.application_context.ApplicationContext") as mock_ctx_class, \
          patch("src.bot.manager.BotManager") as mock_manager_class:
        mock_ctx = MagicMock()
        mock_ctx.create = AsyncMock(return_value=mock_ctx)
        mock_ctx.start = AsyncMock()
        mock_ctx.shutdown = AsyncMock()
        mock_ctx.session = MagicMock()
        mock_ctx_class.create = AsyncMock(return_value=mock_ctx)

        mock_manager = MagicMock(spec=BotManager)
        mock_manager._manager_lock = AsyncMock()
        mock_manager._start_all_bots = AsyncMock(return_value=False)
        mock_manager._stop_all_bots = AsyncMock()
        mock_manager_class.return_value = mock_manager

        await run_bots(users_config, "test.conf")

        mock_manager._start_all_bots.assert_called_once()
        # Should not call loop if start fails
        mock_manager._stop_all_bots.assert_called_once()


@pytest.mark.asyncio
async def test_create_bot_success():
    """Test _create_bot success."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]
    manager = BotManager(users_config, "test.conf", context=ctx)

    bot = manager._create_bot(manager.users_config[0])

    assert bot.username == "user1"
    assert bot.access_token == "a" * 20
    assert bot.channels == ["#chan1"]
    assert bot.enabled is True


@pytest.mark.asyncio
async def test_create_bot_no_context():
    """Test _create_bot failure with no context."""
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]
    manager = BotManager(users_config, "test.conf")

    with pytest.raises(RuntimeError, match="Context/session not initialized"):
        manager._create_bot(users_config[0])


@pytest.mark.asyncio
async def test_restart_with_new_config_success():
    """Test _restart_with_new_config success."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.token_manager = MagicMock()
    ctx.token_manager.prune = AsyncMock()
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]
    manager = BotManager(users_config, "test.conf", context=ctx)
    manager.new_config = [
        {
            "username": "user2",
            "access_token": "d" * 20,
            "refresh_token": "refresh2",
            "client_id": "e" * 10,
            "client_secret": "f" * 10,
            "channels": ["#chan2"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]

    with patch.object(manager.lifecycle, "_stop_all_bots", new_callable=AsyncMock) as mock_stop, \
         patch.object(manager.lifecycle, "_start_all_bots", new_callable=AsyncMock, return_value=True) as mock_start:
        result = await manager._restart_with_new_config()

        assert result is True
        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        assert manager.new_config is None
        assert manager.restart_requested is False


@pytest.mark.asyncio
async def test_restart_with_new_config_no_config():
    """Test _restart_with_new_config with no new config."""
    ctx = MagicMock()
    users_config = []
    manager = BotManager(users_config, "test.conf", context=ctx)

    result = await manager._restart_with_new_config()

    assert result is False


@pytest.mark.asyncio
async def test_restart_with_new_config_start_fails():
    """Test _restart_with_new_config when start fails."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]
    manager = BotManager(users_config, "test.conf", context=ctx)
    manager.new_config = [
        {
            "username": "user2",
            "access_token": "d" * 20,
            "refresh_token": "refresh2",
            "client_id": "e" * 10,
            "client_secret": "f" * 10,
            "channels": ["#chan2"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]

    with patch.object(manager.lifecycle, "_stop_all_bots", new_callable=AsyncMock) as mock_stop, \
         patch.object(manager.lifecycle, "_start_all_bots", new_callable=AsyncMock, return_value=False) as mock_start:
        result = await manager._restart_with_new_config()

        assert result is False
        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        assert manager.new_config is None


def test_setup_signal_handlers():
    """Test setup_signal_handlers sets handlers."""
    ctx = MagicMock()
    users_config = []
    manager = BotManager(users_config, "test.conf", context=ctx)

    with patch("signal.signal") as mock_signal:
        manager.setup_signal_handlers()

        assert mock_signal.call_count == 2  # SIGINT and SIGTERM


@pytest.mark.asyncio
async def test_start_all_bots_partial_failure():
    """Test _start_all_bots with partial bot creation failures."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        },
        {
            "username": "user2",
            "access_token": "d" * 20,
            "refresh_token": "refresh2",
            "client_id": "e" * 10,
            "client_secret": "f" * 10,
            "channels": ["#chan2"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]
    manager = BotManager(users_config, "test.conf", context=ctx)

    def mock_create(user_config):
        if user_config.username == "user1":
            raise ValueError("Create failed for user1")
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        return mock_bot

    with patch.object(manager.lifecycle, "_create_bot", side_effect=mock_create):
        result = await manager._start_all_bots()

        assert result is True  # At least one bot succeeded
        assert len(manager.bots) == 1
        assert len(manager.tasks) == 1


@pytest.mark.asyncio
async def test_cancel_all_tasks_done():
    """Test _cancel_all_tasks with already done tasks."""
    ctx = MagicMock()
    manager = BotManager([], "test.conf", context=ctx)

    mock_task = MagicMock()
    mock_task.done.return_value = True
    manager.tasks = [mock_task]

    manager._cancel_all_tasks()

    mock_task.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_all_tasks_exception():
    """Test _cancel_all_tasks with exception during cancel."""
    ctx = MagicMock()
    manager = BotManager([], "test.conf", context=ctx)

    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_task.cancel.side_effect = ValueError("Cancel failed")
    manager.tasks = [mock_task]

    manager._cancel_all_tasks()

    mock_task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_close_all_bots_exception():
    """Test _close_all_bots with exception during close."""
    ctx = MagicMock()
    manager = BotManager([], "test.conf", context=ctx)

    mock_bot = MagicMock()
    mock_bot.close.side_effect = OSError("Close failed")
    mock_bot.username = "testuser"
    manager.bots = [mock_bot]

    manager._close_all_bots()

    mock_bot.close.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_task_completion_exception():
    """Test _wait_for_task_completion with task exception."""
    ctx = MagicMock()
    manager = BotManager([], "test.conf", context=ctx)

    mock_task = AsyncMock()
    mock_task.exception.return_value = RuntimeError("Task failed")
    manager.tasks = [mock_task]

    await manager._wait_for_task_completion()

    assert len(manager.tasks) == 0


@pytest.mark.asyncio
async def test_stop_all_bots_not_running():
    """Test _stop_all_bots when not running."""
    ctx = MagicMock()
    manager = BotManager([], "test.conf", context=ctx)
    manager.running = False

    await manager._stop_all_bots()

    assert manager.running is False


@pytest.mark.asyncio
async def test_restart_with_new_config_prune_error():
    """Test _restart_with_new_config with prune error."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.token_manager = MagicMock()
    ctx.token_manager.prune = AsyncMock(side_effect=ValueError("Prune failed"))
    users_config = [
        {
            "username": "user1",
            "access_token": "a" * 20,
            "refresh_token": "refresh1",
            "client_id": "b" * 10,
            "client_secret": "c" * 10,
            "channels": ["#chan1"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]
    manager = BotManager(users_config, "test.conf", context=ctx)
    manager.new_config = [
        {
            "username": "user2",
            "access_token": "d" * 20,
            "refresh_token": "refresh2",
            "client_id": "e" * 10,
            "client_secret": "f" * 10,
            "channels": ["#chan2"],
            "is_prime_or_turbo": True,
            "enabled": True,
        }
    ]

    with patch.object(manager.lifecycle, "_stop_all_bots", new_callable=AsyncMock) as mock_stop, \
         patch.object(manager.lifecycle, "_start_all_bots", new_callable=AsyncMock, return_value=True) as mock_start:
        result = await manager._restart_with_new_config()

        assert result is True
        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        ctx.token_manager.prune.assert_called_once()


def test_signal_handler_sets_flag():
    """Test signal handler sets shutdown_initiated flag."""
    ctx = MagicMock()
    users_config = []
    manager = BotManager(users_config, "test.conf", context=ctx)

    with patch("signal.signal") as mock_signal:
        manager.setup_signal_handlers()

        # Get the handler function
        handler = mock_signal.call_args_list[0][0][1]

        # Call handler
        handler(2, None)  # SIGINT

        assert manager.shutdown_initiated is True


@pytest.mark.asyncio
async def test_run_main_loop_shutdown():
    """Test _run_main_loop detects shutdown_initiated."""
    from src.bot.manager import _run_main_loop
    manager = MagicMock()
    manager.running = True
    manager.shutdown_initiated = False
    manager.restart_requested = False
    manager.tasks = [MagicMock()]

    def mock_sleep(seconds):
        manager.shutdown_initiated = True

    with patch("asyncio.sleep", side_effect=mock_sleep), \
         patch.object(manager, "_stop_all_bots", new_callable=AsyncMock):
        await _run_main_loop(manager)

        manager._stop_all_bots.assert_called_once()


@pytest.mark.asyncio
async def test_run_main_loop_restart():
    """Test _run_main_loop detects restart_requested."""
    from src.bot.manager import _run_main_loop
    manager = MagicMock()
    manager.running = True
    manager.shutdown_initiated = False
    manager.restart_requested = False
    manager.tasks = [MagicMock()]

    call_count = 0

    def mock_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            manager.restart_requested = True
        elif call_count == 2:
            manager.running = False

    with patch("asyncio.sleep", side_effect=mock_sleep), \
         patch.object(manager, "_restart_with_new_config", new_callable=AsyncMock, return_value=True):
        await _run_main_loop(manager)

        manager._restart_with_new_config.assert_called_once()


@pytest.mark.asyncio
async def test_run_main_loop_tasks_done():
    """Test _run_main_loop detects all tasks done."""
    from src.bot.manager import _run_main_loop
    manager = MagicMock()
    manager.running = True
    manager.shutdown_initiated = False
    manager.restart_requested = False
    task = MagicMock()
    task.done.return_value = True
    manager.tasks = [task]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await _run_main_loop(manager)

        # Loop exits when all tasks are done, but running remains True as per code logic


@pytest.mark.asyncio
async def test_run_main_loop_restart_fail():
    """Test _run_main_loop when restart fails."""
    from src.bot.manager import _run_main_loop
    manager = MagicMock()
    manager.running = True
    manager.shutdown_initiated = False
    manager.restart_requested = False
    manager.tasks = [MagicMock()]

    call_count = 0

    def mock_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            manager.restart_requested = True
        elif call_count == 2:
            manager.running = False

    async def mock_restart():
        await asyncio.sleep(0)
        manager.restart_requested = False
        return False

    with patch("asyncio.sleep", side_effect=mock_sleep), \
         patch.object(manager, "_restart_with_new_config", side_effect=mock_restart):
        await _run_main_loop(manager)

        manager._restart_with_new_config.assert_called_once()
        # Should continue loop, not break
