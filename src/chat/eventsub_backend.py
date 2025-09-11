from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

from ..api.twitch import TwitchAPI
from ..health import read_status, write_status
from ..logs.logger import logger
from .abstract import ChatBackend, MessageHandler

"""EventSub WebSocket chat backend.

Lightweight implementation focusing on channel.chat.message events filtered
for the bot user acting as chatter. This avoids re-implementing full TwitchIO.

Scopes required: chat:read (already typical for the bot token).
"""

# ...existing code...

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"
EVENTSUB_SUBSCRIPTIONS = "eventsub/subscriptions"
EVENTSUB_CHAT_MESSAGE = "channel.chat.message"


class EventSubChatBackend(ChatBackend):  # pylint: disable=too-many-instance-attributes
    def set_token_invalid_callback(self, callback):
        """Set a callback to be called when token is invalid and needs refresh."""
        self._token_invalid_callback = callback

    def __init__(self, http_session: aiohttp.ClientSession | None = None) -> None:
        self._session = http_session or aiohttp.ClientSession()
        self._api = TwitchAPI(self._session)

        # Current WebSocket URL (can change via session_reconnect instruction)
        self._ws_url: str = EVENTSUB_WS_URL
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._message_handler: MessageHandler | None = None
        self._color_handler: MessageHandler | None = None

        # Credentials and identity
        self._token: str | None = None
        self._client_id: str | None = None
        self._username: str | None = None
        self._user_id: str | None = None
        self._primary_channel: str | None = None

        # Current EventSub session id when connected
        self._session_id: str | None = None
        # If Twitch sends a session_reconnect instruction it includes a
        # session id. Store it temporarily so reconnect attempts can try to
        # preserve continuity when connecting to the provided reconnect_url.
        self._pending_reconnect_session_id: str | None = None
        # Track if we received a reconnect instruction that might have a stale session
        self._reconnect_instruction_received: bool = False

        # Channel/subscription bookkeeping
        self._channels: list[str] = []
        self._channel_ids: dict[str, str] = {}  # login -> user_id

        # Async runtime primitives
        self._listen_task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()
        self._reconnect_requested = False

        # cache file for broadcaster ids (login->id)
        self._cache_path: Path = Path(
            os.environ.get("TWITCH_BROADCASTER_CACHE", "broadcaster_ids.cache.json")
        )

        # last validated OAuth scopes (lowercased)
        self._scopes: set[str] = set()

        # runtime resilience state
        self._backoff = 1.0
        self._last_activity = time.monotonic()
        self._next_sub_check = self._last_activity + 600.0  # 10 min default
        self._stale_threshold = 70.0  # heartbeat*2 + grace
        self._max_backoff = 60.0

        # audit scheduling
        self._audit_interval = 600.0
        self._fast_audit_min = 60.0
        self._fast_audit_max = 120.0
        self._fast_audit_pending = False

        # token invalidation tracking
        self._consecutive_subscribe_401 = 0
        self._token_invalid_flag = False

        # If a session_stale close code is observed, force a full
        # resubscribe flow on the next successful reconnect rather than
        # relying solely on session resumption.
        self._force_full_resubscribe: bool = False

        # initial jitter for first audit to avoid thundering herd
        self._next_sub_check += self._jitter(0, 120.0)

        # end __init__

    # --- token lifecycle integration -------------------------------------------------
    def update_access_token(self, new_token: str | None) -> None:
        """Update access token in place after an external refresh.

        Keeps EventSub WebSocket subscription flow aligned with latest token,
        reducing windows where a stale token might trigger invalid events.
        Lightweight (just assignment + flag reset) so safe to call from hooks.
        """
        if not new_token or not isinstance(new_token, str):  # defensive
            return
        # If a token_invalid flag was previously set due to stale token, clear it
        # so normal subscription verification can proceed with fresh credentials.
        previously_invalid = self._token_invalid_flag
        self._token = new_token
        if previously_invalid:
            self._token_invalid_flag = False
            self._consecutive_subscribe_401 = 0
            logger.log_event(
                "chat",
                "eventsub_token_recovered",
                level=20,
                user=self._username,
            )

    def _jitter(self, a: float, b: float) -> float:
        """Return scheduling jitter using a non-crypto but system-derived source.

        Uses secrets.randbelow to avoid lint/security warnings tied to pseudo RNG
        while the quality requirements remain minimal.
        """
        if b <= a:
            return a
        span = b - a
        # 1e6 discrete steps of jitter resolution
        r = secrets.randbelow(1_000_000) / 1_000_000.0
        return a + r * span

    async def connect(
        self,
        token: str,
        username: str,
        primary_channel: str,
        user_id: str | None,
        client_id: str | None,
        client_secret: str | None = None,  # not used presently
    ) -> bool:
        self._capture_initial_credentials(
            token, username, primary_channel, user_id, client_id, client_secret
        )
        if not self._validate_client_id():
            return False
        self._load_id_cache()
        if not await self._handshake_and_session():
            return False
        if not await self._resolve_initial_channel():
            return False
        await self._ensure_self_user_id()
        await self._record_token_scopes()
        await self._subscribe_channel_chat(
            self._primary_channel or primary_channel.lower()
        )
        self._save_id_cache()
        return True

    # ---- connect helpers (complexity reduction) ----
    def _capture_initial_credentials(
        self,
        token: str,
        username: str,
        primary_channel: str,
        user_id: str | None,
        client_id: str | None,
        client_secret: str | None,
    ) -> None:
        self._token = token
        self._username = username.lower()
        self._user_id = user_id
        pchan = primary_channel.lower()
        self._primary_channel = pchan
        self._channels = [pchan]
        self._client_id = client_id
        _ = client_secret  # reserved

    def _validate_client_id(self) -> bool:
        if not self._client_id or not isinstance(self._client_id, str):
            logger.log_event(
                "chat", "eventsub_missing_client_id", level=40, user=self._username
            )
            return False
        return True

    async def _handshake_and_session(self) -> bool:
        try:
            headers = {}
            if self._client_id:
                headers["Client-Id"] = self._client_id
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._ws = await self._session.ws_connect(
                self._ws_url,
                heartbeat=30,
                headers=headers,
                protocols=("twitch-eventsub-ws",),
            )
            logger.log_event("chat", "eventsub_ws_connected", user=self._username)
            welcome = await asyncio.wait_for(self._ws.receive(), timeout=10)
            if welcome.type != aiohttp.WSMsgType.TEXT:
                logger.log_event(
                    "chat", "eventsub_bad_welcome", level=40, user=self._username
                )
                return False
            try:
                data = json.loads(welcome.data)
                self._session_id = data.get("payload", {}).get("session", {}).get("id")
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "chat", "eventsub_welcome_parse_error", level=40, error=str(e)
                )
                return False
            if not self._session_id:
                logger.log_event(
                    "chat", "eventsub_no_session_id", level=40, user=self._username
                )
                return False
            return True
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat",
                "eventsub_connect_error",
                level=40,
                user=self._username,
                error=str(e),
            )
            return False

    async def _resolve_initial_channel(self) -> bool:
        try:
            await self._batch_resolve_channels(self._channels)
            if (self._primary_channel or "") not in self._channel_ids:
                return False
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _ensure_self_user_id(self) -> None:
        if self._user_id is not None:
            return
        me = await self._fetch_user(self._username or "")
        if me:
            self._user_id = me.get("id")

    async def _record_token_scopes(self) -> None:
        try:
            if self._token is None:
                return
            validation = await self._api.validate_token(self._token)
            if validation:
                raw_scopes = (
                    validation.get("scopes") if isinstance(validation, dict) else None
                )
                scopes_list = (
                    [str(s).lower() for s in raw_scopes]
                    if isinstance(raw_scopes, list)
                    else []
                )
                self._scopes = set(scopes_list)
                logger.log_event(
                    "chat",
                    "eventsub_token_scopes",
                    user=self._username,
                    scopes=";".join(scopes_list),
                    level=10,
                )
        except Exception:  # noqa: BLE001
            self._scopes = set()

    async def join_channel(self, channel: str) -> bool:
        channel_l = channel.lower()
        if channel_l in self._channels:
            return True
        # Attempt batch resolve (single new channel) to leverage cache logic
        await self._batch_resolve_channels([channel_l])
        if channel_l not in self._channel_ids:
            return False
        await self._subscribe_channel_chat(channel_l)
        self._channels.append(channel_l)
        self._save_id_cache()
        return True

    async def listen(self) -> None:  # noqa: D401
        if not self._ws:
            return
        while not self._stop_event.is_set():
            now = time.monotonic()
            await self._maybe_verify_subs(now)
            if await self._maybe_reconnect():
                break
            if not await self._ensure_socket():
                break
            msg = await self._receive_one()
            if await self._handle_ws_message(msg):
                break
            if await self._maybe_reconnect():
                break

    async def disconnect(self) -> None:
        self._stop_event.set()
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close(code=1000)
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "chat", "eventsub_ws_close_error", level=20, error=str(e)
                )
        self._ws = None

    def update_token(self, new_token: str) -> None:
        self._token = new_token

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._message_handler = handler

    def set_color_change_handler(self, handler: MessageHandler) -> None:
        self._color_handler = handler

    async def _handle_text(self, raw: str) -> None:
        data = self._decode_json(raw)
        if data is None:
            return
        mtype = self._extract_message_type(data)
        if mtype is None or mtype == "session_keepalive":
            return
        if mtype == "session_reconnect":
            await self._handle_session_reconnect(data)
            return
        if mtype == "notification":
            await self._handle_notification(data)

    # ---- message handling helpers ----
    def _decode_json(self, raw: str) -> dict[str, Any] | None:
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            logger.log_event("chat", "eventsub_invalid_json", level=20)
            return None

    @staticmethod
    def _extract_message_type(data: dict[str, Any]) -> str | None:
        meta = data.get("metadata")
        if isinstance(meta, dict):
            mt = meta.get("message_type")
            if isinstance(mt, str):
                return mt
        # Fallback to top-level 'type' field
        mtype = data.get("type")
        if isinstance(mtype, str):
            return mtype
        return None

    async def _handle_session_reconnect(self, data: dict[str, Any]) -> None:
        payload = data.get("payload", {}) if isinstance(data, dict) else {}
        session_info = payload.get("session", {}) if isinstance(payload, dict) else {}
        new_url = (
            session_info.get("reconnect_url")
            if isinstance(session_info, dict)
            else None
        )
        logger.log_event(
            "chat",
            "eventsub_reconnect_instruction_received",
            user=self._username,
            old_url=getattr(self, "_ws_url", None),
            new_url=new_url,
            session_info=str(session_info),
        )
        if isinstance(new_url, str) and new_url.startswith("wss://"):
            self._ws_url = new_url
            logger.log_event(
                "chat",
                "eventsub_reconnect_instruction_switching_url",
                user=self._username,
                new_url=new_url,
            )
            # Remember the session id provided by Twitch so we can attempt to
            # resume the same session when connecting to the reconnect_url.
            # Try to get it from session_info first, then fall back to parsing the URL
            maybe_id = (
                session_info.get("id") if isinstance(session_info, dict) else None
            )
            if not isinstance(maybe_id, str) and isinstance(new_url, str):
                # Parse session ID from URL query parameters as fallback
                try:
                    parsed_url = urlparse(new_url)
                    query_params = parse_qs(parsed_url.query)
                    maybe_id = query_params.get("id", [None])[0]
                except Exception as e:
                    logger.log_event(
                        "chat",
                        "eventsub_url_parse_error",
                        level=20,
                        error=str(e),
                        url=new_url,
                    )

            if isinstance(maybe_id, str):
                self._pending_reconnect_session_id = maybe_id
                logger.log_event(
                    "chat",
                    "eventsub_pending_session_id_set",
                    user=self._username,
                    session_id=maybe_id,
                    source="session_info" if session_info.get("id") else "url_parse",
                )
                # Mark that we received a reconnect instruction - the session ID
                # might be stale by the time we try to reconnect
                self._reconnect_instruction_received = True
            await self._safe_close()
            self._reconnect_requested = True
        else:
            logger.log_event(
                "chat",
                "eventsub_reconnect_url_invalid",
                level=40,
                user=self._username,
                session_info=str(session_info),
                new_url=new_url,
            )

    async def _handle_notification(self, data: dict[str, Any]) -> None:
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return
        sub = payload.get("subscription")
        if not isinstance(sub, dict):
            return
        stype = sub.get("type")
        if stype != EVENTSUB_CHAT_MESSAGE:
            return
        event = payload.get("event", {})
        if not isinstance(event, dict):
            return
        chatter = event.get("chatter_user_name")
        channel_login = event.get("broadcaster_user_name")
        message = self._extract_message_text(event)
        if (
            chatter
            and channel_login
            and message is not None
            and self._username
            and isinstance(chatter, str)
            and isinstance(channel_login, str)
            and chatter.lower() == self._username
        ):
            await self._dispatch_message(chatter, channel_login.lower(), message)

    def _extract_message_text(self, event: dict[str, Any]) -> str | None:
        # event.message = { "text": str, ... }
        msg = event.get("message")
        if isinstance(msg, dict):
            text = msg.get("text")
            if isinstance(text, str):
                return text
        return None

    async def _dispatch_message(
        self, username: str, channel: str, message: str
    ) -> None:
        # Emit unified log event (reuse irc_privmsg naming) with IRC-style human text
        try:
            human = f"{username}: {message}"
            logger.log_event(
                "irc",
                "privmsg",
                user=username,
                channel=channel,
                human=human,
                backend="eventsub",
            )
        except Exception as e:  # noqa: BLE001
            logger.log_event("chat", "eventsub_log_emit_error", level=10, error=str(e))
        if self._message_handler:
            try:
                maybe = self._message_handler(username, channel, message)
                if asyncio.iscoroutine(maybe):
                    await maybe  # pragma: no cover - runtime path
            except Exception as e:  # noqa: BLE001
                logger.log_event(
                    "chat", "message_handler_error", level=30, error=str(e)
                )
        if self._color_handler and message.startswith("!"):
            try:
                maybe2 = self._color_handler(username, channel, message)
                if asyncio.iscoroutine(maybe2):
                    await maybe2
            except Exception as e:  # noqa: BLE001
                logger.log_event("chat", "color_handler_error", level=30, error=str(e))

    async def _ensure_channel_id(self, channel_login: str) -> bool:
        if channel_login in self._channel_ids:
            return True
        info = await self._fetch_user(channel_login)
        if not info:
            logger.log_event(
                "chat",
                "eventsub_channel_lookup_failed",
                level=30,
                channel=channel_login,
            )
            return False
        cid = info.get("id")
        if not isinstance(cid, str):
            return False
        self._channel_ids[channel_login] = cid
        return True

    async def _batch_resolve_channels(self, channels: list[str]) -> None:
        # Determine which are missing
        needed = [c for c in channels if c not in self._channel_ids]
        if not needed or not (self._token and self._client_id):
            return
        try:
            mapping = await self._api.get_users_by_login(
                access_token=self._token, client_id=self._client_id, logins=needed
            )
            for login, uid in mapping.items():
                self._channel_ids[login] = uid
            # Log any unresolved
            unresolved = [c for c in needed if c not in self._channel_ids]
            for miss in unresolved:
                logger.log_event(
                    "chat", "eventsub_channel_lookup_failed", level=30, channel=miss
                )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat", "eventsub_batch_resolve_error", level=30, error=str(e)
            )

    # ---- cache helpers ----
    def _load_id_cache(self) -> None:
        try:
            if self._cache_path.exists():
                with self._cache_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(k, str) and isinstance(v, str):
                            self._channel_ids.setdefault(k.lower(), v)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat", "eventsub_cache_load_error", level=20, error=str(e)
            )

    def _save_id_cache(self) -> None:
        try:
            tmp_path = self._cache_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(self._channel_ids, fh, separators=(",", ":"))
            os.replace(tmp_path, self._cache_path)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat", "eventsub_cache_save_error", level=20, error=str(e)
            )

    async def _fetch_user(self, login: str) -> dict[str, Any] | None:
        if not self._token or not self._client_id:
            return None
        try:
            params = {"login": login}
            data, status, _ = await self._api.request(
                "GET",
                "users",
                access_token=self._token,
                client_id=self._client_id,
                params=params,
            )
            if status == 200 and data and data.get("data"):
                first = data["data"][0]
                if isinstance(first, dict):
                    return first
            return None
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat", "eventsub_fetch_user_error", level=20, error=str(e)
            )
            return None

    async def _subscribe_channel_chat(self, channel_login: str) -> None:
        if not self._can_subscribe():
            return
        broadcaster_id = self._channel_ids.get(channel_login)
        if not broadcaster_id:
            return
        body = self._build_subscribe_body(broadcaster_id)
        try:
            if self._token is None or self._client_id is None:
                return
            data, status, _ = await self._api.request(
                "POST",
                EVENTSUB_SUBSCRIPTIONS,
                access_token=self._token,
                client_id=self._client_id,
                json_body=body,
            )
            self._handle_subscribe_response(channel_login, status, data)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat",
                "eventsub_subscribe_error",
                level=30,
                error=str(e),
                channel=channel_login,
            )

    def _can_subscribe(self) -> bool:
        return (
            bool(self._session_id and self._token and self._client_id and self._user_id)
            and not self._token_invalid_flag
        )

    def _build_subscribe_body(self, broadcaster_id: str) -> dict[str, Any]:
        return {
            "type": EVENTSUB_CHAT_MESSAGE,
            "version": "1",
            "condition": {
                "broadcaster_user_id": broadcaster_id,
                "user_id": self._user_id,
            },
            "transport": {"method": "websocket", "session_id": self._session_id},
        }

    def _handle_subscribe_response(
        self, channel_login: str, status: int, data: Any
    ) -> None:
        if status == 202:
            self._on_subscribed(channel_login)
            return
        self._log_subscribe_non_202(status, channel_login, data)
        if status == 401:
            self._handle_subscribe_unauthorized(channel_login, data)
            return
        self._on_subscribe_other(channel_login, status)

    def _on_subscribed(self, channel_login: str) -> None:
        logger.log_event(
            "chat",
            "eventsub_subscribed",
            channel=channel_login,
            user=self._username,
        )
        self._consecutive_subscribe_401 = 0

    async def _maybe_reconnect(self) -> bool:
        """Helper to handle reconnect if requested. Returns True if reconnect was attempted and failed (should break loop)."""
        if self._reconnect_requested:
            self._reconnect_requested = False
            ok = await self._reconnect_with_backoff()
            if not ok:
                return True
            return False
        return False

    async def _handle_ws_message(self, msg) -> bool:
        """Handle a websocket message. Returns True if a reconnect was attempted and failed (should break loop)."""
        if msg is None:
            return False  # timeout path handled internally
        if msg.type == aiohttp.WSMsgType.TEXT:
            self._last_activity = time.monotonic()
            await self._handle_text(msg.data)
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            logger.log_event(
                "chat",
                "eventsub_ws_abnormal_end",
                user=self._username,
                code=getattr(msg, "data", None),
            )
            ok = await self._reconnect_with_backoff()
            if not ok:
                return True
        return False

    def _log_subscribe_non_202(
        self, status: int, channel_login: str, data: Any
    ) -> None:
        logger.log_event(
            "chat",
            "eventsub_subscribe_non_202",
            level=30,
            status=status,
            channel=channel_login,
            detail=(data.get("message") if isinstance(data, dict) else None),
        )

    def _handle_subscribe_unauthorized(self, channel_login: str, data: Any) -> None:
        self._consecutive_subscribe_401 += 1
        logger.log_event(
            "chat",
            "eventsub_subscribe_unauthorized",
            level=30,
            channel=channel_login,
            count=self._consecutive_subscribe_401,
        )
        if self._consecutive_subscribe_401 >= 2 and not self._token_invalid_flag:
            self._token_invalid_flag = True
            logger.log_event(
                "chat",
                "eventsub_token_invalid",
                level=40,
                user=self._username,
                channel=channel_login,
                source="subscribe",
                detail=(data.get("message") if isinstance(data, dict) else None),
            )
            if self._token_invalid_callback:
                try:
                    _ = asyncio.create_task(self._token_invalid_callback())
                except Exception as e:
                    logger.log_event(
                        "chat",
                        "eventsub_token_invalid_callback_error",
                        level=30,
                        error=str(e),
                    )

    def _on_subscribe_other(self, channel_login: str, status: int) -> None:
        # reset counter on any non-401 failure
        self._consecutive_subscribe_401 = 0
        if status == 403:
            self._log_missing_scopes(channel_login)

    def _log_missing_scopes(self, channel_login: str) -> None:
        required = {"user:read:chat", "chat:read"}
        missing = sorted(s for s in required if s not in self._scopes)
        if missing:
            logger.log_event(
                "chat",
                "eventsub_missing_scopes",
                level=30,
                channel=channel_login,
                missing=";".join(missing),
            )

    async def _open_and_handshake(self) -> bool:
        """Open WebSocket and parse welcome, setting session id."""
        try:
            self._ws = await self._session.ws_connect(self._ws_url, heartbeat=30)
            welcome = await asyncio.wait_for(self._ws.receive(), timeout=10)
            if welcome.type != aiohttp.WSMsgType.TEXT:
                return False
            data = json.loads(welcome.data)
            self._session_id = data.get("payload", {}).get("session", {}).get("id")
            return bool(self._session_id)
        except Exception:
            return False

    async def _verify_subscriptions(self) -> None:
        if not (self._token and self._client_id and self._session_id):
            return
        active = await self._fetch_active_broadcaster_ids()
        if active is None:
            return
        expected = self._expected_broadcaster_ids()
        missing = expected - active
        if not missing:
            return
        await self._resubscribe_missing(missing)

    async def _fetch_active_broadcaster_ids(self) -> set[str] | None:
        if not self._can_fetch_broadcaster_ids():
            return None
        data, status = await self._try_fetch_broadcaster_ids()
        if data is None:
            return None
        if status == 401:
            self._handle_list_unauthorized(data)
            return None
        if status != 200 or not isinstance(data, dict):
            return None
        return self._extract_broadcaster_ids_from_data(data)

    def _can_fetch_broadcaster_ids(self) -> bool:
        return self._token is not None and self._client_id is not None

    def _handle_list_unauthorized(self, data: Any) -> None:
        logger.log_event(
            "chat",
            "eventsub_list_unauthorized",
            level=30,
            detail=(data.get("message") if isinstance(data, dict) else None),
        )

    async def _try_fetch_broadcaster_ids(self) -> tuple[Any, int]:
        try:
            # mypy: ensure str, not Optional[str]
            if self._token is None or self._client_id is None:
                raise RuntimeError("Token or client_id is None")
            data, status, _ = await self._api.request(
                "GET",
                EVENTSUB_SUBSCRIPTIONS,
                access_token=self._token,
                client_id=self._client_id,
            )
            return data, status
        except Exception as e:  # noqa: BLE001
            logger.log_event("chat", "eventsub_sub_list_error", level=20, error=str(e))
            return None, -1

    def _extract_broadcaster_ids_from_data(self, data: Any) -> set[str]:
        rows = data.get("data")
        if not isinstance(rows, list):
            return set()
        result: set[str] = set()
        for entry in rows:
            bid = self._extract_broadcaster_id(entry)
            if bid:
                result.add(bid)
        return result

    def _extract_broadcaster_id(self, entry: Any) -> str | None:
        if not isinstance(entry, dict):
            return None
        if entry.get("type") != EVENTSUB_CHAT_MESSAGE:
            return None
        transport = entry.get("transport", {})
        if transport.get("session_id") != self._session_id:
            return None
        cond = entry.get("condition", {})
        bid = cond.get("broadcaster_user_id")
        return bid if isinstance(bid, str) else None

    def _expected_broadcaster_ids(self) -> set[str]:
        return {
            bid for bid in (self._channel_ids.get(c) for c in self._channels) if bid
        }

    def _handle_close_action(self, close_code: int | None) -> str | None:
        """Map a close code to an action and perform minimal side-effects.

        Returns a symbolic action name or None.
        """
        if close_code is None:
            return None
        CLOSE_CODE_ACTIONS = {
            4001: "token_refresh",
            4002: "token_refresh",
            4003: "token_refresh",
            4007: "session_stale",
        }
        action = CLOSE_CODE_ACTIONS.get(int(close_code))
        if action == "token_refresh":
            # Mark token invalid and call the configured callback
            self._token_invalid_flag = True
            if self._token_invalid_callback:
                try:
                    task = asyncio.create_task(self._token_invalid_callback())
                    # keep a weak reference on the instance so GC doesn't
                    # collect immediately in some event loop implementations
                    self._last_token_refresh_task = task
                except Exception as e:
                    logger.log_event(
                        "chat",
                        "eventsub_token_invalid_callback_error",
                        level=20,
                        error=str(e),
                    )
        elif action == "session_stale":
            # mark that we should perform a full resubscribe cycle after
            # reconnect rather than relying on session resume
            try:
                self._force_full_resubscribe = True
            except Exception as e:
                logger.log_event(
                    "chat",
                    "eventsub_force_full_resubscribe_error",
                    level=20,
                    error=str(e),
                )
        return action

    async def _resubscribe_missing(self, missing: set[str]) -> None:
        for ch, bid in self._channel_ids.items():
            if bid in missing:
                await self._subscribe_channel_chat(ch)
        logger.log_event(
            "chat",
            "eventsub_resubscribe_missing",
            missing=len(missing),
            total=len(self._channels),
        )

    async def _maybe_verify_subs(self, now: float) -> None:
        if now < self._next_sub_check:
            return
        try:
            await self._verify_subscriptions()
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat", "eventsub_subscription_check_error", level=20, error=str(e)
            )
        # If fast audit pending (post-reconnect) schedule normal interval next, else schedule normal with jitter
        if self._fast_audit_pending:
            self._fast_audit_pending = False
            self._next_sub_check = now + self._audit_interval + self._jitter(0, 120.0)
        else:
            self._next_sub_check = now + self._audit_interval + self._jitter(0, 120.0)

    async def _ensure_socket(self) -> bool:
        if self._ws and not self._ws.closed:
            return True
        logger.log_event("chat", "eventsub_ws_closed_detected", user=self._username)
        return await self._reconnect_with_backoff()

    async def _receive_one(self) -> aiohttp.WSMessage | None:
        if not self._ws:
            return None
        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=10)
            return msg
        except TimeoutError:
            if time.monotonic() - self._last_activity > self._stale_threshold:
                logger.log_event(
                    "chat",
                    "eventsub_stale_detected",
                    user=self._username,
                    idle=int(time.monotonic() - self._last_activity),
                )
                ok = await self._reconnect_with_backoff()
                if not ok:
                    return None
            return None
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat",
                "eventsub_listen_error",
                level=30,
                user=self._username,
                error=str(e),
            )
            ok = await self._reconnect_with_backoff()
            if not ok:
                return None
            return None

    # ---- reconnect helpers moved to class scope to reduce function complexity ----
    async def _reconnect_cleanup(self) -> None:
        await self._safe_close()
        # If Twitch provided a pending reconnect session id keep it so the
        # new connection can attempt to resume that session.
        # However, if we're forcing a full resubscribe (e.g., due to session_stale),
        # don't use the pending session id as it may be invalid.
        if self._pending_reconnect_session_id and not self._force_full_resubscribe:
            self._session_id = self._pending_reconnect_session_id
        else:
            self._session_id = None
        # Clear the pending marker after consuming it.
        self._pending_reconnect_session_id = None
        self._consecutive_subscribe_401 = 0

    async def _perform_handshake(self) -> tuple[bool, dict]:
        return await self._open_and_handshake_detailed()

    async def _do_subscribe_cycle(self) -> None:
        # rebuild channel subs
        await self._batch_resolve_channels(self._channels)
        for ch in self._channels:
            await self._subscribe_channel_chat(ch)
        # If we detected a session_stale earlier, ensure we attempt a
        # full resubscribe cycle and then clear the flag.
        if self._force_full_resubscribe:
            logger.log_event(
                "chat",
                "eventsub_force_full_resubscribe",
                user=self._username,
                channel_count=len(self._channels),
            )
            # Re-run the subscribe flow to be explicit.
            for ch in self._channels:
                await self._subscribe_channel_chat(ch)
            self._force_full_resubscribe = False

    async def _reconnect_with_backoff(self) -> bool:
        """Reconnect loop with reduced cognitive complexity by delegating
        cleanup, handshake and subscribe cycles to small helpers.
        """

        # Use class-scoped helpers (_reconnect_cleanup, _perform_handshake,
        # _do_subscribe_cycle) to keep this function small and testable.

        import traceback

        attempt = 0
        while not self._stop_event.is_set():
            attempt += 1
            try:
                # --- FULL STATE CLEANUP ---
                await self._reconnect_cleanup()

                # --- RECONNECT DELAY ---
                await asyncio.sleep(1.0)  # 1 second delay before reconnect

                logger.log_event(
                    "chat",
                    "eventsub_reconnect_attempt",
                    user=self._username,
                    attempt=attempt,
                    ws_url=getattr(self, "_ws_url", None),
                    session_id=getattr(self, "_session_id", None),
                    channels=str(self._channels),
                )

                # --- HANDSHAKE WITH FULL LOGGING ---
                handshake_ok, handshake_details = await self._perform_handshake()
                logger.log_event(
                    "chat",
                    "eventsub_handshake_result",
                    user=self._username,
                    attempt=attempt,
                    ws_url=getattr(self, "_ws_url", None),
                    session_id=getattr(self, "_session_id", None),
                    handshake_ok=handshake_ok,
                    handshake_details=handshake_details,
                )
                if not handshake_ok:
                    raise RuntimeError(f"handshake failed: {handshake_details}")

                # subscribe / resubscribe work
                await self._do_subscribe_cycle()

                logger.log_event(
                    "chat",
                    "eventsub_reconnect_success",
                    user=self._username,
                    attempt=attempt,
                    ws_url=getattr(self, "_ws_url", None),
                    session_id=getattr(self, "_session_id", None),
                    channel_count=len(self._channels),
                    channels=str(self._channels),
                )
                # update health status on successful reconnect
                try:
                    write_status(
                        {
                            "last_reconnect_ok": time.time(),
                            "consecutive_reconnect_failures": 0,
                        }
                    )
                except Exception as e:
                    logger.log_event(
                        "chat",
                        "eventsub_health_write_error",
                        level=20,
                        error=str(e),
                    )

                self._backoff = 1.0
                now = time.monotonic()
                self._last_activity = now
                # schedule a fast audit soon with jitter
                self._fast_audit_pending = True
                self._next_sub_check = now + self._jitter(
                    self._fast_audit_min, self._fast_audit_max
                )
                return True
            except Exception as e:  # noqa: BLE001
                twitch_error = None
                if hasattr(e, "args") and e.args:
                    twitch_error = e.args[0]
                logger.log_event(
                    "chat",
                    "eventsub_reconnect_failed",
                    level=40,
                    user=self._username,
                    attempt=attempt,
                    ws_url=getattr(self, "_ws_url", None),
                    session_id=getattr(self, "_session_id", None),
                    channels=str(self._channels),
                    error=str(e),
                    twitch_error=twitch_error,
                    traceback=traceback.format_exc(),
                    backoff=round(self._backoff, 2),
                )
                await asyncio.sleep(
                    self._backoff + self._jitter(0, 0.25 * self._backoff)
                )
                self._backoff = min(self._backoff * 2, self._max_backoff)
                # record a reconnect failure in health status
                try:
                    status = read_status()
                    failures = int(status.get("consecutive_reconnect_failures", 0)) + 1
                    write_status(
                        {
                            "last_reconnect_failure": time.time(),
                            "consecutive_reconnect_failures": failures,
                        }
                    )
                except Exception as e:
                    logger.log_event(
                        "chat",
                        "eventsub_health_write_error",
                        level=20,
                        error=str(e),
                    )
        return False

    async def _open_and_handshake_detailed(self):
        """Open WebSocket and parse welcome, logging all details for diagnostics."""
        try:
            # Optionally, create a new ClientSession for each reconnect (advanced):
            # self._session = aiohttp.ClientSession()
            headers = {}
            if self._client_id:
                headers["Client-Id"] = self._client_id
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            ws = await self._session.ws_connect(
                self._ws_url,
                heartbeat=30,
                headers=headers,
                protocols=("twitch-eventsub-ws",),
            )
            self._ws = ws
            # Log handshake request headers (aiohttp hides some, but we can log what we can)
            handshake_details = {
                "request_headers": dict(getattr(ws, "_request_headers", {})),
                "url": self._ws_url,
            }
            welcome = await asyncio.wait_for(ws.receive(), timeout=10)
            handshake_details["welcome_type"] = str(getattr(welcome, "type", None))
            handshake_details["welcome_raw"] = getattr(welcome, "data", None)
            # Explicitly record CLOSE/ERROR frames to help triage server-side
            # rejections (for example Twitch sending a close code instead of the
            # expected JSON TEXT welcome). Keep existing behavior of failing the
            # handshake but provide richer details in logs.
            if (
                welcome.type == aiohttp.WSMsgType.CLOSE
                or welcome.type == aiohttp.WSMsgType.CLOSING
            ):
                handshake_details["error"] = "closed_by_server"
                # `welcome.data` is usually the close code; `welcome.extra` may
                # contain additional reason text depending on the transport.
                close_code = getattr(welcome, "data", None)
                handshake_details["close_code"] = close_code
                handshake_details["close_reason"] = getattr(welcome, "extra", None)
                # Map known close codes to actions. We make conservative
                # assumptions about codes that indicate authentication issues.
                # If an auth-related code is observed, trigger the
                # token-invalid callback (if configured) so higher layers can
                # refresh tokens.
                action = self._handle_close_action(close_code)
                handshake_details["mapped_action"] = action
                return False, handshake_details
            if welcome.type == aiohttp.WSMsgType.ERROR:
                handshake_details["error"] = "ws_error"
                handshake_details["exception"] = getattr(welcome, "data", None)
                return False, handshake_details
            if welcome.type != aiohttp.WSMsgType.TEXT:
                handshake_details["error"] = "bad_welcome_type"
                return False, handshake_details
            try:
                data = json.loads(welcome.data)
                self._session_id = data.get("payload", {}).get("session", {}).get("id")
                handshake_details["session_id"] = self._session_id
                handshake_details["welcome_json"] = data
                # On successful handshake, if we had a pending reconnect
                # session id provided by Twitch, clear it — the session has
                # now been established (either resumed or replaced).
                self._pending_reconnect_session_id = None
            except Exception as e:
                handshake_details["error"] = f"welcome_parse_error: {e}"
                return False, handshake_details
            if not self._session_id:
                handshake_details["error"] = "no_session_id"
                return False, handshake_details
            return True, handshake_details
        except Exception as e:
            return False, {"exception": str(e)}

    async def _safe_close(self) -> None:
        try:
            if self._ws and not self._ws.closed:
                await self._ws.close()
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "chat", "eventsub_safe_close_error", level=10, error=str(e)
            )
