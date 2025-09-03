"""Token manager (moved from token_manager.py)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from secrets import SystemRandom

import aiohttp

from constants import (
    TOKEN_MANAGER_BACKGROUND_BASE_SLEEP,
    TOKEN_MANAGER_VALIDATION_MIN_INTERVAL,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from logs.logger import logger

from .client import TokenClient, TokenOutcome

_jitter_rng = SystemRandom()


class TokenState(Enum):
    FRESH = "fresh"
    STALE = "stale"
    REFRESHING = "refreshing"
    EXPIRED = "expired"


@dataclass
class TokenInfo:
    username: str
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    expiry: datetime | None = None
    state: TokenState = TokenState.FRESH
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_validation: float = 0


class TokenManager:
    _instance = None
    _initialized = False

    def __new__(cls, http_session: aiohttp.ClientSession):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, http_session: aiohttp.ClientSession):
        if TokenManager._initialized:
            return
        self.http_session = http_session
        self.tokens: dict[str, TokenInfo] = {}
        self.background_task: asyncio.Task | None = None
        self.running = False
        self.logger = logger
        self._client_cache: dict[tuple[str, str], TokenClient] = {}
        TokenManager._initialized = True

    async def start(self):
        if self.running:
            return
        # Defensive: if a previous background task is still lingering (e.g. rapid
        # stop/start where stop hasn't fully awaited cancellation yet), ensure it
        # is cancelled and awaited to avoid multiple loops.
        if self.background_task and not self.background_task.done():
            self.logger.log_event(
                "token_manager",
                "stale_background_detected",
                level=logging.DEBUG,
                human="Cancelling stale background task before restart",
            )
            try:
                self.background_task.cancel()
                await self.background_task
            except asyncio.CancelledError:
                # Propagate cancellation upwards; restart logic should honor this.
                raise
            except Exception as e:  # noqa: BLE001
                self.logger.log_event(
                    "token_manager",
                    "stale_background_error",
                    level=logging.DEBUG,
                    error=str(e),
                )
            finally:
                self.background_task = None
        self.running = True
        self.background_task = asyncio.create_task(self._background_refresh_loop())
        self.logger.log_event("token_manager", "start")
        await asyncio.sleep(0)

    async def stop(self):
        if not self.running:
            return
        self.running = False
        if self.background_task:
            self.background_task.cancel()
            try:
                await self.background_task
            except Exception as e:  # noqa: BLE001
                if isinstance(e, asyncio.CancelledError):
                    self.logger.log_event(
                        "token_manager",
                        "background_cancelled",
                        level=logging.DEBUG,
                        human="Background loop cancelled",
                    )
                else:
                    raise
            finally:
                self.background_task = None

    def register(
        self,
        username: str,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        expiry: datetime | None,
    ):
        info = self.tokens.get(username)
        if info:
            info.access_token = access_token
            info.refresh_token = refresh_token
            info.client_id = client_id
            info.client_secret = client_secret
            info.expiry = expiry
            info.state = TokenState.FRESH
        else:
            self.tokens[username] = TokenInfo(
                username=username,
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                expiry=expiry,
            )
        self.logger.log_event("token_manager", "registered", user=username)

    def remove(self, username: str) -> bool:
        """Remove a user from token tracking (e.g., config removal)."""
        if username in self.tokens:
            del self.tokens[username]
            self.logger.log_event(
                "token_manager", "removed", level=logging.DEBUG, user=username
            )
            return True
        return False

    def prune(self, active_usernames: set[str]) -> int:
        """Prune tokens not in active set; return count removed."""
        to_remove = [u for u in self.tokens if u not in active_usernames]
        for u in to_remove:
            del self.tokens[u]
        if to_remove:
            self.logger.log_event(
                "token_manager",
                "pruned",
                removed=len(to_remove),
                remaining=len(self.tokens),
            )
        return len(to_remove)

    def get_info(self, username: str) -> TokenInfo | None:
        return self.tokens.get(username)

    def _get_client(self, client_id: str, client_secret: str) -> TokenClient:
        key = (client_id, client_secret)
        cli = self._client_cache.get(key)
        if cli:
            return cli
        cli = TokenClient(client_id, client_secret, self.http_session)
        self._client_cache[key] = cli
        return cli

    async def ensure_fresh(
        self, username: str, force_refresh: bool = False
    ) -> TokenOutcome:
        info = self.tokens.get(username)
        if not info:
            return TokenOutcome.FAILED
        remaining = self._remaining_seconds(info)
        if (
            not force_refresh
            and info.expiry
            and remaining is not None
            and remaining > TOKEN_REFRESH_THRESHOLD_SECONDS
        ):
            return TokenOutcome.VALID
        client = self._get_client(info.client_id, info.client_secret)
        async with info.refresh_lock:
            result = await client.ensure_fresh(
                username,
                info.access_token,
                info.refresh_token,
                info.expiry,
                force_refresh,
            )

            if result.outcome != TokenOutcome.FAILED and result.access_token:
                info.access_token = result.access_token
                if result.refresh_token:
                    info.refresh_token = result.refresh_token
                info.expiry = result.expiry
                info.state = (
                    TokenState.FRESH
                    if result.outcome in (TokenOutcome.VALID, TokenOutcome.SKIPPED)
                    else TokenState.STALE
                )
            elif result.outcome == TokenOutcome.FAILED:
                info.state = TokenState.EXPIRED
            return result.outcome

    async def validate(self, username: str) -> TokenOutcome:
        info = self.tokens.get(username)
        if not info:
            return TokenOutcome.FAILED
        now = time.time()
        if now - info.last_validation < TOKEN_MANAGER_VALIDATION_MIN_INTERVAL:
            return TokenOutcome.VALID
        if not info.expiry:
            return TokenOutcome.FAILED
        client = self._get_client(info.client_id, info.client_secret)
        valid, expiry = await client._validate_remote(  # noqa: SLF001
            username, info.access_token
        )
        info.last_validation = now
        if valid:
            info.expiry = expiry
            return TokenOutcome.VALID
        return TokenOutcome.FAILED

    def _remaining_seconds(self, info: TokenInfo) -> float | None:
        if not info.expiry:
            return None
        return (info.expiry - datetime.now()).total_seconds()

    async def _background_refresh_loop(self):
        base = TOKEN_MANAGER_BACKGROUND_BASE_SLEEP
        while self.running:
            try:
                for username, info in self.tokens.items():
                    remaining = self._remaining_seconds(info)
                    if remaining is None or remaining < 0:
                        info.state = TokenState.EXPIRED
                        continue
                    if remaining < TOKEN_REFRESH_THRESHOLD_SECONDS:
                        await self.ensure_fresh(username)
                await asyncio.sleep(base * _jitter_rng.uniform(0.5, 1.5))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.logger.log_event(
                    "token_manager",
                    "background_error",
                    level=logging.ERROR,
                    error=str(e),
                )
                await asyncio.sleep(base * 2)
