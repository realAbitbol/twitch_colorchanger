"""Central application context for shared async resources."""

from __future__ import annotations

import asyncio
import time
from token.manager import TokenManager

import aiohttp

from logs.logger import logger
from rate.rate_limiter import TwitchRateLimiter


class ApplicationContext:
    """Holds shared async resources for the application lifecycle."""

    # Class / instance attribute type declarations (helps mypy)
    session: aiohttp.ClientSession | None
    token_manager: TokenManager | None
    _rate_limiters: dict[str, TwitchRateLimiter]
    _started: bool
    _lock: asyncio.Lock
    _maintenance_task: asyncio.Task | None
    _session_birth: float | None
    _SESSION_MAX_AGE: int
    _tasks: dict[str, asyncio.Task]
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
        logger.log_event("context", "creating")
        ctx.session = aiohttp.ClientSession()
        ctx._session_birth = time.time()
        logger.log_event("context", "session_created")
        ctx.token_manager = TokenManager(ctx.session)
        return ctx

    # --------------------------- Lifecycle -------------------------- #
    async def start(self):
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
            logger.log_event("context", "start")
            self._maintenance_task = asyncio.create_task(self._maintenance_loop())
            self._register_task("maintenance", self._maintenance_task)

    async def shutdown(self):
        async with self._lock:
            logger.log_event("context", "shutdown_begin")
            if self._maintenance_task:
                self._maintenance_task.cancel()
                try:
                    await self._maintenance_task
                except Exception as e:  # noqa: BLE001
                    logger.log_event(
                        "context",
                        "maintenance_cancel_wait_error",
                        level=10,
                        error=str(e),
                    )
                self._maintenance_task = None
            if self.session:
                try:
                    await self.session.close()
                except Exception as e:  # noqa: BLE001
                    logger.log_event(
                        "context", "session_close_error", level=40, error=str(e)
                    )
                finally:
                    self.session = None
            if self.token_manager:
                try:
                    await self.token_manager.stop()
                except Exception as e:  # noqa: BLE001
                    if isinstance(e, asyncio.CancelledError):
                        logger.log_event(
                            "context",
                            "token_manager_cancelled",
                            level=30,
                            human="Token manager cancellation during shutdown",
                        )
                    else:
                        logger.log_event(
                            "context",
                            "token_manager_stop_error",
                            level=40,
                            error=str(e),
                        )
                finally:
                    self.token_manager = None
            self._rate_limiters.clear()
            self._started = False
            self._tasks.clear()
            logger.log_event("context", "shutdown")

    # ------------------------- Rate Limiting ------------------------ #
    def get_rate_limiter(
        self, client_id: str, username: str | None = None
    ) -> TwitchRateLimiter:
        key = f"{client_id}:{username or 'app'}"
        limiter = self._rate_limiters.get(key)
        if limiter is None:
            limiter = TwitchRateLimiter(client_id, username)
            self._rate_limiters[key] = limiter
            logger.log_event(
                "context", "rate_limiter_created", client_id=client_id, user=username
            )
        return limiter

    # --------------------- Task & Metrics Registry ------------------ #
    def _register_task(self, name: str, task: asyncio.Task | None):
        if not task:
            return
        self._tasks[name] = task
        logger.log_event("context", "task_registered", task=name)

    def task_snapshot(self) -> list[dict[str, str]]:
        out = []
        for name, t in self._tasks.items():
            out.append({"name": name, "state": "done" if t.done() else "running"})
        return out

    def incr(self, key: str, delta: int = 1):
        self._counters[key] = self._counters.get(key, 0) + delta

    def metrics_snapshot(self) -> dict[str, int]:  # shallow copy
        return dict(self._counters)

    def _emit_metrics(self):
        snap = self.metrics_snapshot()
        logger.log_event("metrics", "snapshot", **snap)

    # ----------------------- Maintenance Loop ----------------------- #
    async def _maintenance_loop(self):  # pragma: no cover - timing oriented
        while self._started:
            try:
                await asyncio.sleep(3600)  # hourly tick
                # Session recycling for long-lived DNS / connection hygiene
                if (
                    self.session
                    and self._session_birth
                    and time.time() - self._session_birth > self._SESSION_MAX_AGE
                ):
                    logger.log_event("context", "session_recycle")
                    try:
                        await self.session.close()
                    except Exception as e:  # noqa: BLE001
                        logger.log_event(
                            "context",
                            "session_close_recycle_error",
                            level=10,
                            error=str(e),
                        )
                    self.session = aiohttp.ClientSession()
                    self._session_birth = time.time()
                # Stale probe + metrics
                self._probe_rate_limiters()
                self._maintenance_ticks += 1
                if self._maintenance_ticks % 6 == 0:  # ~ every 6h
                    self._emit_metrics()
                logger.log_event("context", "maintenance_tick", level=10)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.log_event("context", "maintenance_error", level=30, error=str(e))
                await asyncio.sleep(300)

    def _probe_rate_limiters(self):
        stale = 0
        for key, limiter in self._rate_limiters.items():
            snap = limiter.snapshot()
            for bucket_name in ("app_bucket", "user_bucket"):
                bucket = snap.get(bucket_name)
                if not bucket:
                    continue
                age = bucket.get("age", 0)
                if age > 3600:  # 1h threshold
                    stale += 1
                    logger.log_event(
                        "rate_limit",
                        "bucket_stale_probe",
                        level=10,
                        key=key,
                        bucket=bucket_name,
                        age=int(age),
                    )
        if stale:
            self.incr("stale_rate_buckets", stale)
