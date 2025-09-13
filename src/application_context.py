"""Central application context for shared async resources."""

from __future__ import annotations

import asyncio
import atexit
import logging
import time
from typing import Any

import aiohttp

from .auth_token.manager import TokenManager
from .health import write_status
from .rate.rate_limiter import TwitchRateLimiter

# Global reference for emergency cleanup if normal shutdown is interrupted
GLOBAL_CONTEXT: ApplicationContext | None = None


class ApplicationContext:
    """Holds shared async resources for the application lifecycle."""

    # Class / instance attribute type declarations (helps mypy)
    session: aiohttp.ClientSession | None
    token_manager: TokenManager | None
    _rate_limiters: dict[str, TwitchRateLimiter]
    _started: bool
    _lock: asyncio.Lock
    _maintenance_task: asyncio.Task[Any] | None
    _session_birth: float | None
    _SESSION_MAX_AGE: int
    _tasks: dict[str, asyncio.Task[Any]]
    _counters: dict[str, int]
    _maintenance_ticks: int

    def __init__(self) -> None:
        # Core resources
        self.session = None
        self.token_manager = None
        self._rate_limiters = {}
        # Lifecycle flags
        self._started = False
        self._lock = asyncio.Lock()
        # Maintenance / aging
        self._maintenance_task = None
        self._session_birth = None
        self._SESSION_MAX_AGE = 24 * 3600  # 24h recycle
        # Task registry & metrics
        self._tasks = {}
        self._counters = {}
        self._maintenance_ticks = 0

    # ------------------------- Construction ------------------------- #
    @classmethod
    async def create(cls) -> ApplicationContext:
        ctx = cls()
        logging.debug("🧪 Creating application context")
        ctx.session = aiohttp.ClientSession()
        ctx._session_birth = time.time()
        logging.debug("🔗 HTTP session created")
        ctx.token_manager = TokenManager(ctx.session)
        # Register globally for atexit fallback
        global GLOBAL_CONTEXT  # noqa: PLW0603
        GLOBAL_CONTEXT = ctx
        return ctx

    # --------------------------- Lifecycle -------------------------- #
    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            if self.token_manager:
                await self.token_manager.start()
                if getattr(self.token_manager, "background_task", None):
                    self._register_task(
                        "token_refresh", self.token_manager.background_task
                    )
            self._started = True
            logging.debug("🚀 Application context started")
            self._maintenance_task = asyncio.create_task(self._maintenance_loop())
            self._register_task("maintenance", self._maintenance_task)

    async def shutdown(self) -> None:
        async with self._lock:
            logging.info("🔻 Application context shutdown initiated")
            await self._cancel_maintenance_task()
            await self._stop_token_manager()
            await self._close_http_session()
            self._rate_limiters.clear()
            self._started = False
            self._tasks.clear()
            logging.info("✅ Application context shutdown complete")
            # After clean shutdown remove global reference so atexit won't re-run
            global GLOBAL_CONTEXT  # noqa: PLW0603
            if GLOBAL_CONTEXT is self:
                GLOBAL_CONTEXT = None

    async def _cancel_maintenance_task(self) -> None:
        if not self._maintenance_task:
            return
        self._maintenance_task.cancel()
        try:
            await self._maintenance_task
        except Exception as e:  # noqa: BLE001
            logging.debug(f"⚠️ Error waiting maintenance task cancel: {str(e)}")
        finally:
            self._maintenance_task = None

    async def _stop_token_manager(self) -> None:
        if not self.token_manager:
            return
        try:
            await self.token_manager.stop()
        except Exception as e:  # noqa: BLE001
            if isinstance(e, asyncio.CancelledError):
                logging.warning("🛑 Token manager cancellation during shutdown")
            else:
                logging.error(f"💥 Error stopping token manager: {str(e)}")
        finally:
            self.token_manager = None

    async def _close_http_session(self) -> None:
        if not self.session:
            return
        try:
            await self.session.close()
        except Exception as e:  # noqa: BLE001
            logging.error(f"💥 Error closing HTTP session: {str(e)}")
        finally:
            self.session = None

    # ------------------------- Rate Limiting ------------------------ #
    def get_rate_limiter(
        self, client_id: str, username: str | None = None
    ) -> TwitchRateLimiter:
        key = f"{client_id}:{username or 'app'}"
        limiter = self._rate_limiters.get(key)
        if limiter is None:
            limiter = TwitchRateLimiter(client_id, username)
            self._rate_limiters[key] = limiter
            logging.debug("🧱 Rate limiter created")
        return limiter

    # --------------------- Task & Metrics Registry ------------------ #
    def _register_task(self, name: str, task: asyncio.Task[Any] | None) -> None:
        if not task:
            return
        self._tasks[name] = task
        logging.debug("📝 Context: task registered")

    def task_snapshot(self) -> list[dict[str, str]]:
        # Currently unused (kept for potential future diagnostics). If still unused,
        # consider removing after verification cycles.  # pragma: no cover
        out: list[dict[str, str]] = []
        for name, t in self._tasks.items():
            out.append({"name": name, "state": "done" if t.done() else "running"})
        return out

    def incr(self, key: str, delta: int = 1) -> None:
        self._counters[key] = self._counters.get(key, 0) + delta

    def metrics_snapshot(self) -> dict[str, int]:  # shallow copy
        return dict(self._counters)

    def _emit_metrics(self) -> None:
        logging.debug("📊 Metrics snapshot")

    # ----------------------- Maintenance Loop ----------------------- #
    async def _maintenance_loop(self) -> None:  # pragma: no cover - timing oriented
        while self._started:
            try:
                await asyncio.sleep(3600)  # hourly tick
                await self._maybe_recycle_session()
                self._probe_rate_limiters()
                self._maintenance_ticks += 1
                self._maybe_emit_metrics()
                # heartbeat for external health checks
                try:
                    write_status({"last_maintenance": time.time()})
                except Exception as e:  # noqa: BLE001
                    # Log the health write failure but keep the maintenance loop alive
                    try:
                        logging.debug(f"⚠️ Error in maintenance loop: {str(e)}")
                    except Exception:
                        # Fallback: avoid raising from the maintenance loop
                        try:
                            import sys as _sys

                            _sys.stderr.write(f"health write error: {e}\n")
                        except Exception:
                            ...
                logging.debug("🕰️ Maintenance tick")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logging.warning(f"💥 Maintenance loop error: {str(e)}")
                await asyncio.sleep(300)

    async def _maybe_recycle_session(self) -> None:
        if (
            self.session
            and self._session_birth
            and time.time() - self._session_birth > self._SESSION_MAX_AGE
        ):
            logging.info("♻️ HTTP session recycled")
            try:
                await self.session.close()
            except Exception as e:  # noqa: BLE001
                logging.debug(f"⚠️ Error closing HTTP session during recycle: {str(e)}")
            self.session = aiohttp.ClientSession()
            self._session_birth = time.time()

    def _maybe_emit_metrics(self) -> None:
        if self._maintenance_ticks % 6 == 0:  # ~ every 6h
            self._emit_metrics()

    def _probe_rate_limiters(self) -> None:
        stale = sum(
            self._probe_single_limiter(key, limiter)
            for key, limiter in self._rate_limiters.items()
        )
        if stale:
            self.incr("stale_rate_buckets", stale)

    def _probe_single_limiter(self, key: str, limiter: TwitchRateLimiter) -> int:
        stale_found = 0
        snap = limiter.snapshot()
        for bucket_name in ("app_bucket", "user_bucket"):
            bucket_obj = snap.get(bucket_name)
            if not isinstance(bucket_obj, dict) or not bucket_obj:
                continue
            age_obj = bucket_obj.get("age", 0)
            age = float(age_obj) if isinstance(age_obj, int | float) else 0.0
            if age > 3600:
                stale_found += 1
                logging.debug(
                    f"🧪 Probed stale rate limit bucket key={key} bucket={bucket_name} age={int(age)}s"
                )
        return stale_found


# -------------------- Atexit Fallback (best-effort) -------------------- #
def _atexit_close() -> None:  # pragma: no cover - process teardown path
    ctx = GLOBAL_CONTEXT
    if not ctx:
        return
    session = ctx.session
    if session and not session.closed:
        try:
            # Create a temporary loop just to close the session cleanly
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(session.close())
            finally:
                loop.close()
            logging.info("🧹 HTTP session closed at exit")
        except Exception as e:  # noqa: BLE001
            # Best effort logging; avoid nested silent pass
            msg = str(e)
            try:
                logging.warning(f"⚠️ HTTP session close error at exit: {msg}")
            except Exception:
                # Fallback minimal stderr write (no pass-only block)
                try:
                    import sys as _sys

                    _sys.stderr.write(f"[atexit] session close error: {msg}\n")
                except Exception:
                    ...  # pragma: no cover


atexit.register(_atexit_close)
