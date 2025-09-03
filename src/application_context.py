"""Central application context for shared async resources.

Manages:
 - aiohttp.ClientSession
 - TokenManager instance
 - Rate limiter instances (previously global registry)

Provides unified startup/shutdown semantics.
"""

from __future__ import annotations

import asyncio

import aiohttp

from .logger import logger
from .rate_limiter import TwitchRateLimiter
from .token_manager import TokenManager


class ApplicationContext:
    """Holds shared async resources for the application lifecycle."""

    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None
        self.token_manager: TokenManager | None = None
        self._rate_limiters: dict[str, TwitchRateLimiter] = {}
        self._started = False
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls) -> ApplicationContext:
        self = cls()
        logger.log_event("context", "creating")
        self.session = aiohttp.ClientSession()
        logger.log_event("context", "session_created")
        self.token_manager = TokenManager(self.session)
        return self

    async def start(self):
        async with self._lock:
            if self._started:
                return
            if self.token_manager:
                await self.token_manager.start()
            self._started = True
            logger.log_event("context", "start")

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

    async def shutdown(self):
        async with self._lock:
            logger.log_event("context", "shutdown_begin")
            if self.token_manager:
                try:
                    await self.token_manager.stop()
                except Exception as e:  # noqa: BLE001
                    logger.log_event(
                        "context", "token_manager_stop_error", level=40, error=str(e)
                    )
                finally:
                    self.token_manager = None
            if self.session:
                try:
                    await self.session.close()
                except Exception as e:  # noqa: BLE001
                    logger.log_event(
                        "context", "session_close_error", level=40, error=str(e)
                    )
                finally:
                    self.session = None
            self._rate_limiters.clear()
            self._started = False
            logger.log_event("context", "shutdown")
