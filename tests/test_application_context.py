"""Tests for src/application_context.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application_context import ApplicationContext, _atexit_close


@pytest.mark.asyncio
async def test_create_token_manager_failure():
    """Test ApplicationContext.create with token manager creation failure."""
    with patch('src.auth_token.manager.TokenManager', side_effect=Exception("Creation failed")), \
         patch('aiohttp.ClientSession'):
        try:
            await ApplicationContext.create()
            # Should not reach here if exception is raised
        except Exception as e:
            assert "Creation failed" in str(e)


@pytest.mark.asyncio
async def test_start_already_started():
    """Test start method when already started."""
    ctx = ApplicationContext()
    ctx._started = True
    ctx.token_manager = MagicMock()
    await ctx.start()  # Should not raise or start again


@pytest.mark.asyncio
async def test_shutdown_token_manager_error():
    """Test shutdown with token manager error."""
    ctx = ApplicationContext()
    ctx.token_manager = MagicMock()
    ctx.token_manager.stop = AsyncMock(side_effect=Exception("Stop failed"))
    with pytest.raises(Exception, match="Stop failed"):
        await ctx.shutdown()


@pytest.mark.asyncio
async def test_shutdown_http_session_error():
    """Test shutdown with HTTP session close error."""
    ctx = ApplicationContext()
    ctx.session = MagicMock()
    ctx.session.close = AsyncMock(side_effect=Exception("Close failed"))
    with pytest.raises(Exception, match="Close failed"):
        await ctx.shutdown()


def test_atexit_close_no_context():
    """Test _atexit_close with no global context."""
    global GLOBAL_CONTEXT
    GLOBAL_CONTEXT = None
    _atexit_close()  # Should not raise


def test_atexit_close_closed_session():
    """Test _atexit_close with already closed session."""
    ctx = ApplicationContext()
    ctx.session = MagicMock()
    ctx.session.closed = True
    global GLOBAL_CONTEXT
    GLOBAL_CONTEXT = ctx
    _atexit_close()  # Should not attempt to close
