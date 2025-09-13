import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

import pytest

from src.auth_token.manager import TokenInfo, TokenManager, TokenOutcome


def _fresh_manager(monkeypatch):
    from src.auth_token.manager import TokenManager as _TM
    _TM._instance = None  # type: ignore[attr-defined]
    tm = object.__new__(TokenManager)  # type: ignore[call-arg]
    tm.http_session = None
    tm.tokens = {}
    tm.background_task = None
    tm.running = False
    tm._client_cache = {}
    tm._update_hooks = {}
    tm._hook_tasks = []
    return tm


# 1. Unknown-expiry resolution: exhaustion path
@pytest.mark.asyncio
async def test_unknown_expiry_exhaustion(monkeypatch, caplog):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo(
        username="u", access_token="A", refresh_token="R", client_id="cid", client_secret="csec", expiry=None
    )
    tm.tokens["u"] = info

    calls = {"count": 0}

    async def fake_ensure(username, force_refresh=False):  # noqa: ARG001
        await asyncio.sleep(0)
        calls["count"] += 1
        # Always fail so expiry stays None
        return TokenOutcome.FAILED

    monkeypatch.setattr(tm, "ensure_fresh", fake_ensure)  # type: ignore[arg-type]

    caplog.set_level(logging.DEBUG)
    # Invoke handler multiple times to exhaust attempts
    for _ in range(4):  # 0..3 (4th triggers exhausted log)
        await tm._handle_unknown_expiry("u")  # noqa: SLF001

    assert info.forced_unknown_attempts == 3
    exhausted_logs = [r for r in caplog.records if r.levelno >= logging.WARNING and "exhausted" in r.message]
    assert exhausted_logs, "Expected exhaustion log entry containing 'exhausted'"


# 1b. Unknown-expiry success and reset path
@pytest.mark.asyncio
async def test_unknown_expiry_success_resets_attempts(monkeypatch):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo(
        username="u", access_token="A", refresh_token="R", client_id="cid", client_secret="csec", expiry=None
    )
    info.forced_unknown_attempts = 2
    tm.tokens["u"] = info

    async def fake_ensure(username, force_refresh=False):  # noqa: ARG001
        await asyncio.sleep(0)
        # Simulate success by setting expiry during first call
        if tm.tokens[username].expiry is None:
            tm.tokens[username].expiry = datetime.now(UTC) + timedelta(seconds=30)
        return TokenOutcome.REFRESHED

    monkeypatch.setattr(tm, "ensure_fresh", fake_ensure)  # type: ignore[arg-type]
    await tm._handle_unknown_expiry("u")  # noqa: SLF001
    assert info.expiry is not None
    assert info.forced_unknown_attempts == 0


# 2. Periodic validation success vs failure triggering forced refresh
@pytest.mark.asyncio
async def test_periodic_validation_success(monkeypatch):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo(
        "u", "A", "R", "cid", "csec", datetime.now(UTC) + timedelta(seconds=50)
    )
    info.last_validation = 0  # ensure interval elapsed
    tm.tokens["u"] = info

    async def fake_validate(username):  # noqa: ARG001
        await asyncio.sleep(0)
        info.expiry = datetime.now(UTC) + timedelta(seconds=60)
        return TokenOutcome.VALID

    monkeypatch.setattr(tm, "validate", fake_validate)  # type: ignore[arg-type]
    remaining = await tm._maybe_periodic_or_unknown_resolution("u", info, 40)  # noqa: SLF001
    assert remaining is not None and remaining > 0
    assert info.expiry is not None


@pytest.mark.asyncio
async def test_periodic_validation_failure_forced_refresh(monkeypatch):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo(
        "u", "A", "R", "cid", "csec", datetime.now(UTC) + timedelta(seconds=50)
    )
    info.last_validation = 0
    tm.tokens["u"] = info

    validate_calls = {"c": 0}
    refresh_calls = {"c": 0}

    async def fake_validate(username):  # noqa: ARG001
        await asyncio.sleep(0)
        validate_calls["c"] += 1
        return TokenOutcome.FAILED

    async def fake_ensure(username, force_refresh=False):  # noqa: ARG001
        await asyncio.sleep(0)
        refresh_calls["c"] += 1
        return TokenOutcome.REFRESHED

    monkeypatch.setattr(tm, "validate", fake_validate)  # type: ignore[arg-type]
    monkeypatch.setattr(tm, "ensure_fresh", fake_ensure)  # type: ignore[arg-type]
    _ = await tm._maybe_periodic_or_unknown_resolution("u", info, 40)  # noqa: SLF001
    assert validate_calls["c"] == 1
    assert refresh_calls["c"] == 1


# 2b. Periodic validation error path logging
@pytest.mark.asyncio
async def test_periodic_validation_error_logged(monkeypatch, caplog):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo(
        "u", "A", "R", "cid", "csec", datetime.now(UTC) + timedelta(seconds=50)
    )
    info.last_validation = 0
    tm.tokens["u"] = info

    async def fake_validate(username):  # noqa: ARG001
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    monkeypatch.setattr(tm, "validate", fake_validate)  # type: ignore[arg-type]
    caplog.set_level(logging.WARNING)
    await tm._maybe_periodic_or_unknown_resolution("u", info, 40)  # noqa: SLF001
    msgs = [r.message for r in caplog.records]
    assert any("⚠️ Periodic remote token validation error for user u" in m for m in msgs)


# 3. Force proactive (drift) refresh branch
@pytest.mark.asyncio
async def test_force_proactive_refresh(monkeypatch):
    tm = _fresh_manager(monkeypatch)
    import src.auth_token.manager as mgr_mod
    # Patch threshold to small value for test
    monkeypatch.setattr(mgr_mod, "TOKEN_REFRESH_THRESHOLD_SECONDS", 10, raising=False)
    info = TokenInfo(
        "u", "A", "R", "cid", "csec", datetime.now(UTC) + timedelta(seconds=12)
    )
    tm.tokens["u"] = info
    calls = {"forced": False}

    async def fake_ensure(username, force_refresh=False):  # noqa: ARG001
        await asyncio.sleep(0)
        if force_refresh:
            calls["forced"] = True
        return TokenOutcome.REFRESHED if force_refresh else TokenOutcome.VALID

    monkeypatch.setattr(tm, "ensure_fresh", fake_ensure)  # type: ignore[arg-type]
    await tm._process_single_background("u", info, force_proactive=True)  # noqa: SLF001
    assert calls["forced"], "Expected forced refresh due to proactive drift handling"


# 4. Update hook error handling (exception inside hook -> retained_task_error)
@pytest.mark.asyncio
async def test_update_hook_error_logged(monkeypatch, caplog):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo(
        "u", "A", "R", "cid", "csec", datetime.now(UTC) + timedelta(seconds=5)
    )
    tm.tokens["u"] = info

    class DummyClient:
        async def ensure_fresh(self, *a, **k):  # noqa: D401
            await asyncio.sleep(0)
            class R:
                pass
            r = R()
            r.outcome = TokenOutcome.REFRESHED
            r.access_token = "A2"  # noqa: S105  # noqa: S105
            r.refresh_token = "R2"  # noqa: S105  # noqa: S105
            r.expiry = datetime.now(UTC) + timedelta(seconds=30)
            return r

    monkeypatch.setattr(tm, "_get_client", lambda cid, cs: DummyClient())

    async def bad_hook():  # raises after a tick
        await asyncio.sleep(0)
        raise RuntimeError("hook boom")

    tm.register_update_hook("u", bad_hook)
    caplog.set_level(logging.DEBUG)
    # Patch _create_retained_task to run hook and invoke callback immediately
    def _immediate(coro, category: str):  # type: ignore[override]
        async def runner():
            try:
                await coro
            except Exception as e:  # log similar to callback path
                logging.debug(f"⚠️ Retained background task error category={category} error={str(e)} type={type(e).__name__}")
        return asyncio.create_task(runner())
    monkeypatch.setattr(tm, "_create_retained_task", _immediate)  # type: ignore[arg-type]
    await tm.ensure_fresh("u", force_refresh=True)
    # Allow task scheduling and callback execution over a couple of loop turns
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    msgs = [r.message for r in caplog.records]
    assert any("⚠️ Retained background task error" in m for m in msgs)


# 5. EventSub propagation hook
@pytest.mark.asyncio
async def test_eventsub_propagation_hook(monkeypatch):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo(
        "u", "A", "R", "cid", "csec", datetime.now(UTC) + timedelta(seconds=5)
    )
    tm.tokens["u"] = info

    class DummyClient:
        async def ensure_fresh(self, *a, **k):
            await asyncio.sleep(0)
            class R:  # simple result
                pass
            r = R()
            r.outcome = TokenOutcome.REFRESHED
            r.access_token = "NEW"  # noqa: S105  # noqa: S105
            r.refresh_token = "RR"  # noqa: S105  # noqa: S105
            r.expiry = datetime.now(UTC) + timedelta(seconds=30)
            return r

    monkeypatch.setattr(tm, "_get_client", lambda cid, cs: DummyClient())

    class Backend:
        def __init__(self):
            self.tokens = []
        def update_access_token(self, tok):  # noqa: D401
            self.tokens.append(tok)

    backend = Backend()
    tm.register_eventsub_backend("u", backend)
    await tm.ensure_fresh("u", force_refresh=True)
    await asyncio.sleep(0)
    assert backend.tokens == ["NEW"]


# 6. TokenManager start creates background task
@pytest.mark.asyncio
async def test_start_creates_background_task(monkeypatch):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo("u", "A", "R", "cid", "csec", datetime.now(UTC) + timedelta(seconds=120))
    tm.tokens["u"] = info
    async def fake_initial():
        await asyncio.sleep(0)
    monkeypatch.setattr(tm, "_initial_validation_pass", fake_initial)
    async def fake_loop():
        await asyncio.sleep(0.01)
    monkeypatch.setattr(tm, "_background_refresh_loop", fake_loop)
    await tm.start()
    assert tm.running and tm.background_task is not None
    # Cancel and ignore cancellation
    if tm.background_task:
        tm.background_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tm.background_task
    tm.running = False


# 7. validate() success & failure update logic
@pytest.mark.asyncio
async def test_validate_success_and_failure(monkeypatch):
    tm = _fresh_manager(monkeypatch)
    info = TokenInfo(
        "u", "A", "R", "cid", "csec", datetime.now(UTC) + timedelta(seconds=120)
    )
    tm.tokens["u"] = info
    # Simulate client returning valid then invalid
    seq = {"step": 0}

    class DummyClient:
        async def _validate_remote(self, username, access):  # noqa: D401, SLF001
            await asyncio.sleep(0)
            if seq["step"] == 0:
                seq["step"] = 1
                return True, datetime.now(UTC) + timedelta(seconds=180)
            return False, None

    monkeypatch.setattr(tm, "_get_client", lambda cid, cs: DummyClient())
    out1 = await tm.validate("u")
    assert out1 == TokenOutcome.VALID and tm.tokens["u"].expiry is not None
    # Force min interval bypass so validation executed again
    tm.tokens["u"].last_validation = 0
    out2 = await tm.validate("u")
    assert out2 == TokenOutcome.FAILED


# 8. retained_task_error path already covered by test_update_hook_error_logged
