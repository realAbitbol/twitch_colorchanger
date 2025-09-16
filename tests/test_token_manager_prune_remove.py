import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auth_token.client import RefreshErrorType, TokenOutcome
from src.auth_token.manager import TokenInfo, TokenManager


@pytest.mark.asyncio
async def test_remove_and_prune(monkeypatch):
    from src.auth_token.manager import TokenManager as _TM
    _TM._instance = None  # type: ignore[attr-defined]
    tm = object.__new__(TokenManager)  # type: ignore[call-arg]
    tm.http_session = None
    tm.tokens = {}
    tm.background_task = None
    tm.running = False
    tm._client_cache = {}
    tm._update_hooks = {}
    tm._invalidation_hooks = {}
    tm._hook_tasks = []
    tm._tokens_lock = asyncio.Lock()
    tm._hooks_lock = asyncio.Lock()

    info1 = TokenInfo("u1", "a1", "r1", "cid", "csec", datetime.now(UTC)+timedelta(hours=1))
    info2 = TokenInfo("u2", "a2", "r2", "cid", "csec", datetime.now(UTC)+timedelta(hours=1))
    tm.tokens["u1"] = info1
    tm.tokens["u2"] = info2

    assert await tm.remove("u1") is True
    assert "u1" not in tm.tokens
    removed = await tm.prune({"u2"})
    assert removed == 0
    removed2 = await tm.prune(set())
    assert removed2 == 1 and not tm.tokens


@pytest.mark.asyncio
async def test_invalidation_hook_called_on_refresh_failure(monkeypatch):
    """Test that invalidation hook is called when refresh fails."""
    from src.auth_token.manager import TokenManager as _TM
    _TM._instance = None
    tm = object.__new__(TokenManager)
    tm.http_session = MagicMock()
    tm.tokens = {}
    tm.background_task = None
    tm.running = False
    tm._client_cache = {}
    tm._update_hooks = {}
    tm._invalidation_hooks = {}
    tm._hook_tasks = []
    tm._tokens_lock = asyncio.Lock()
    tm._hooks_lock = asyncio.Lock()
    tm._client_cache_lock = asyncio.Lock()

    # Mock client
    mock_client = MagicMock()
    from src.auth_token.client import TokenResult
    mock_result = TokenResult(TokenOutcome.FAILED, None, None, None, RefreshErrorType.NON_RECOVERABLE)
    mock_client.ensure_fresh = AsyncMock(return_value=mock_result)
    tm._get_client = AsyncMock(return_value=mock_client)

    # Add token info
    info = TokenInfo("u1", "a1", "r1", "cid", "csec", datetime.now(UTC) + timedelta(hours=1))
    tm.tokens["u1"] = info
    info.refresh_lock = asyncio.Lock()

    # Mock hook
    hook_mock = AsyncMock()
    await tm.register_invalidation_hook("u1", hook_mock)

    # Call ensure_fresh which should fail and call hook
    outcome = await tm.ensure_fresh("u1")
    assert outcome.name == "FAILED"
    hook_mock.assert_called_once()
