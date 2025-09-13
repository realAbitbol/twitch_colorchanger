from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

from ..api.twitch import TwitchAPI

MessageHandler = Callable[[str, str, str], Any]

"""EventSub WebSocket chat backend.

Lightweight implementation focusing on channel.chat.message events filtered
for the bot user acting as chatter. This avoids re-implementing full TwitchIO.

Scopes required: chat:read (already typical for the bot token).
"""

# ...existing code...

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"
EVENTSUB_SUBSCRIPTIONS = "eventsub/subscriptions"
EVENTSUB_CHAT_MESSAGE = "channel.chat.message"


class EventSubChatBackend:  # pylint: disable=too-many-instance-attributes
    """EventSub WebSocket chat backend for Twitch.

    Lightweight implementation focusing on channel.chat.message events filtered
    for the bot user acting as chatter. This avoids re-implementing full TwitchIO.

    Attributes:
        _session (aiohttp.ClientSession): HTTP session for API calls.
        _api (TwitchAPI): Twitch API client instance.
        _ws_url (str): Current WebSocket URL, may change via reconnect.
        _ws (aiohttp.ClientWebSocketResponse | None): Active WebSocket connection.
        _message_handler (MessageHandler | None): Callback for chat messages.
        _color_handler (MessageHandler | None): Callback for color commands.
        _token (str | None): OAuth access token.
        _client_id (str | None): Twitch client ID.
        _username (str | None): Bot username.
        _user_id (str | None): Bot user ID.
        _primary_channel (str | None): Primary channel login.
        _session_id (str | None): Current EventSub session ID.
        _pending_reconnect_session_id (str | None): Session ID for reconnect.
        _pending_challenge (str | None): Pending challenge for handshake.
        _channels (list[str]): List of joined channels.
        _channel_ids (dict[str, str]): Mapping of login to user ID.
        _stop_event (asyncio.Event): Event to signal shutdown.
        _reconnect_requested (bool): Flag for reconnect request.
        _cache_path (Path): Path to broadcaster ID cache file.
        _scopes (set[str]): Validated OAuth scopes.
        _backoff (float): Current reconnect backoff time.
        _last_activity (float): Timestamp of last WebSocket activity.
        _next_sub_check (float): Next subscription verification time.
        _stale_threshold (float): Threshold for stale connection.
        _max_backoff (float): Maximum backoff time.
        _audit_interval (float): Interval for subscription audits.
        _fast_audit_min (float): Minimum fast audit delay.
        _fast_audit_max (float): Maximum fast audit delay.
        _fast_audit_pending (bool): Flag for pending fast audit.
        _consecutive_subscribe_401 (int): Count of consecutive 401 errors.
        _token_invalid_flag (bool): Flag indicating token invalidity.
        _force_full_resubscribe (bool): Flag to force full resubscribe.
        _token_invalid_callback (Callable | None): Callback for token invalidation.
    """

    def set_token_invalid_callback(self, callback):
        """Sets the callback for token invalidation events.

        Args:
            callback (Callable): Function to call when the token becomes invalid.
        """
        self._token_invalid_callback = callback

    def __init__(self, http_session: aiohttp.ClientSession | None = None) -> None:
        """Initialize the EventSub chat backend.

        Args:
            http_session (aiohttp.ClientSession | None): Optional HTTP session to use.
                If None, a new session is created.
        """
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
        self._pending_challenge: str | None = None
        # Track if we received a reconnect instruction that might have a stale session

        # Channel/subscription bookkeeping
        self._channels: list[str] = []
        self._channel_ids: dict[str, str] = {}  # login -> user_id

        # Async runtime primitives
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
        """Updates the access token after external refresh.

        Keeps the EventSub WebSocket subscription flow aligned with the latest token,
        reducing windows where a stale token might trigger invalid events.
        Lightweight operation safe to call from hooks.

        Args:
            new_token (str | None): The new access token. If None or invalid, ignored.
        """
        if not new_token or not isinstance(new_token, str):  # defensive check
            return
        # Clear token invalid flag if previously set, allowing normal verification
        previously_invalid = self._token_invalid_flag
        self._token = new_token
        if previously_invalid:
            self._token_invalid_flag = False
            self._consecutive_subscribe_401 = 0
            logging.info("🔄 EventSub token recovered")

    def _jitter(self, a: float, b: float) -> float:
        """Returns scheduling jitter using a non-crypto source.

        Uses secrets.randbelow to avoid lint warnings while meeting minimal quality needs.

        Args:
            a (float): Minimum value.
            b (float): Maximum value.

        Returns:
            float: Random value between a and b.
        """
        if b <= a:
            return a
        span = b - a
        # 1e6 discrete steps for jitter resolution
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
        """Connects to Twitch EventSub WebSocket and subscribes to chat messages.

        Performs initial setup including credential capture, client validation,
        cache loading, handshake, channel resolution, user ID setup, scope recording,
        and subscription to the primary channel.

        Args:
            token (str): OAuth access token.
            username (str): Bot username.
            primary_channel (str): Primary channel to join.
            user_id (str | None): Bot user ID, if known.
            client_id (str | None): Twitch client ID.
            client_secret (str | None): Client secret (currently unused).

        Returns:
            bool: True if connection and subscription successful, False otherwise.
        """
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
        """Captures initial credentials and sets up basic state.

        Args:
            token (str): OAuth token.
            username (str): Bot username.
            primary_channel (str): Primary channel.
            user_id (str | None): Bot user ID.
            client_id (str | None): Client ID.
            client_secret (str | None): Client secret (ignored).
        """
        self._token = token
        self._username = username.lower()
        self._user_id = user_id
        pchan = primary_channel.lower()
        self._primary_channel = pchan
        self._channels = [pchan]
        self._client_id = client_id
        _ = client_secret  # reserved

    def _validate_client_id(self) -> bool:
        """Validates that client ID is present and a string.

        Returns:
            bool: True if valid, False otherwise.
        """
        if not self._client_id or not isinstance(self._client_id, str):
            logging.error("🚫 EventSub missing client id")
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
            logging.info(f"🔌 EventSub WebSocket connected for {self._username}")
            welcome = await asyncio.wait_for(self._ws.receive(), timeout=10)
            if welcome.type != aiohttp.WSMsgType.TEXT:
                logging.error("⚠️ EventSub bad welcome frame")
                return False
            try:
                data = json.loads(welcome.data)
                self._session_id = data.get("payload", {}).get("session", {}).get("id")
            except Exception as e:  # noqa: BLE001
                logging.error(f"⚠️ EventSub welcome parse error: {str(e)}")
                return False
            if not self._session_id:
                logging.error("🚫 EventSub no session id")
                return False
            return True
        except Exception as e:  # noqa: BLE001
            logging.error(f"💥 EventSub connect error: {str(e)}")
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
                logging.debug(
                    "🧪 EventSub token scopes scopes={scopes}".format(
                        scopes=";".join(scopes_list)
                    )
                )
        except Exception:  # noqa: BLE001
            self._scopes = set()

    async def join_channel(self, channel: str) -> bool:
        """Joins a channel and subscribes to its chat messages.

        Resolves the channel ID if not cached, subscribes to chat events,
        and updates the cache.

        Args:
            channel (str): Channel name to join.

        Returns:
            bool: True if joined successfully, False otherwise.
        """
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
        """Listens for WebSocket messages and handles them.

        Runs the main event loop, processing messages, verifying subscriptions,
        and handling reconnections until stopped.
        """
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
        """Disconnects from the WebSocket and cleans up resources.

        Sets the stop event, closes the WebSocket connection gracefully,
        and clears the WebSocket reference.
        """
        self._stop_event.set()
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close(code=1000)
            except Exception as e:  # noqa: BLE001
                logging.info(f"⚠️ EventSub WebSocket close error: {str(e)}")
        self._ws = None

    def update_token(self, new_token: str) -> None:
        """Updates the access token.

        Args:
            new_token (str): The new access token.
        """
        self._token = new_token

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Sets the handler for incoming chat messages.

        Args:
            handler (MessageHandler): Function to handle messages, called with
                (username, channel, message).
        """
        self._message_handler = handler

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
            logging.info("⚠️ EventSub invalid JSON payload")
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
        """Handle session_reconnect message with reduced cognitive complexity."""
        # Extract info using helper (handles all type checks and parsing)
        new_url, maybe_id, maybe_challenge, session_info = self._extract_reconnect_info(
            data
        )

        logging.info(
            "🔄 EventSub session reconnect instruction received: old_url={old_url} new_url={new_url} session_info={session_info}".format(
                old_url=getattr(self, "_ws_url", None),
                new_url=new_url,
                session_info=str(session_info),
            )
        )

        if not (isinstance(new_url, str) and new_url.startswith("wss://")):
            logging.error("⚠️ EventSub session reconnect URL invalid")
            return

        # Update state using helper
        self._update_reconnect_state(new_url, maybe_id, maybe_challenge, session_info)

        # Trigger reconnect
        await self._safe_close()
        self._reconnect_requested = True

    def _extract_reconnect_info(
        self, data: dict[str, Any]
    ) -> tuple[str | None, str | None, str | None, dict]:
        """Extract reconnect URL, session ID, challenge, and session info with defensive parsing."""
        if not isinstance(data, dict):
            return None, None, None, {}

        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            return None, None, None, {}

        session_info = payload.get("session", {})
        if not isinstance(session_info, dict):
            return None, None, None, {}

        new_url = session_info.get("reconnect_url")
        if not isinstance(new_url, str):
            return None, None, None, session_info

        # Try to get session ID from session_info
        maybe_id = session_info.get("id")
        if not isinstance(maybe_id, str):
            maybe_id = None

        # Parse URL for ID and challenge (fallback for ID, always for challenge)
        maybe_challenge = None
        try:
            parsed_url = urlparse(new_url)
            query_params = parse_qs(parsed_url.query)
            if not isinstance(maybe_id, str):
                maybe_id = query_params.get("id", [None])[0]
            maybe_challenge = query_params.get("challenge", [None])[0]
        except Exception as e:
            logging.info(
                f"💥 EventSub URL parse error user={self._username} error={str(e)} url={new_url}"
            )

        return new_url, maybe_id, maybe_challenge, session_info

    def _update_reconnect_state(
        self,
        new_url: str,
        maybe_id: str | None,
        maybe_challenge: str | None,
        session_info: dict,
    ) -> None:
        """Update internal state for reconnect (URL, session ID, challenge, logging)."""
        self._ws_url = new_url
        logging.info(f"🔄 EventSub switching to new WebSocket URL: {new_url}")

        if isinstance(maybe_id, str):
            self._pending_reconnect_session_id = maybe_id
            source = "session_info" if session_info.get("id") else "url_parse"
            logging.info(
                f"🆔 EventSub pending session id set user={self._username} session_id={maybe_id} source={source}"
            )
        else:
            self._pending_reconnect_session_id = None

        if isinstance(maybe_challenge, str):
            self._pending_challenge = maybe_challenge
            source = "session_info" if session_info.get("id") else "url_parse"
            logging.info(
                "🔑 EventSub pending challenge set user={user} challenge={challenge} source={source}".format(
                    user=self._username,
                    challenge=maybe_challenge,
                    source=source if "session_info" in source else "url_parse",
                )
            )
        else:
            self._pending_challenge = None

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
        # Emit unified log event with human-readable text
        try:
            logging.info(f"💬 #{channel} {username}: {message}")
        except Exception as e:  # noqa: BLE001
            logging.debug(f"⚠️ EventSub log emit error: {str(e)}")
        if self._message_handler:
            try:
                maybe = self._message_handler(username, channel, message)
                if asyncio.iscoroutine(maybe):
                    await maybe  # pragma: no cover - runtime path
            except Exception:  # noqa: BLE001
                logging.warning("💥 Chat message handler error")
        if self._color_handler and message.startswith("!"):
            try:
                maybe2 = self._color_handler(username, channel, message)
                if asyncio.iscoroutine(maybe2):
                    await maybe2
            except Exception:  # noqa: BLE001
                logging.warning("💥 Color handler error")

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
                logging.warning(f"⚠️ EventSub channel lookup failed channel={miss}")
        except Exception as e:  # noqa: BLE001
            logging.warning(f"💥 EventSub batch resolve error: {str(e)}")

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
            logging.info(f"⚠️ EventSub cache load error: {str(e)}")

    def _save_id_cache(self) -> None:
        try:
            tmp_path = self._cache_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(self._channel_ids, fh, separators=(",", ":"))
            os.replace(tmp_path, self._cache_path)
        except Exception as e:  # noqa: BLE001
            logging.info(f"⚠️ EventSub cache save error: {str(e)}")

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
            logging.info(f"⚠️ EventSub fetch user error: {str(e)}")
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
        except Exception:  # noqa: BLE001
            logging.warning(f"💥 EventSub subscribe error channel={channel_login}")

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
        logging.info(f"✅ {self._username} joined #{channel_login}")
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
            logging.info(
                "⚠️ EventSub WebSocket abnormal end code={code}".format(
                    code=getattr(msg, "data", None)
                )
            )
            ok = await self._reconnect_with_backoff()
            if not ok:
                return True
        return False

    def _log_subscribe_non_202(
        self, status: int, channel_login: str, data: Any
    ) -> None:
        logging.warning(
            f"⚠️ EventSub subscribe non-202 status={status} channel={channel_login}"
        )

    def _handle_subscribe_unauthorized(self, channel_login: str, data: Any) -> None:
        self._consecutive_subscribe_401 += 1
        logging.warning(
            f"🚫 EventSub subscribe unauthorized channel={channel_login} count={self._consecutive_subscribe_401}"
        )
        if self._consecutive_subscribe_401 >= 2 and not self._token_invalid_flag:
            self._token_invalid_flag = True
            logging.error(
                "🚫 EventSub token invalid source={source} channel={channel}".format(
                    source="subscribe", channel=channel_login
                )
            )
            if self._token_invalid_callback:
                try:
                    _ = asyncio.create_task(self._token_invalid_callback())
                except Exception as e:
                    logging.warning(
                        f"⚠️ Error in EventSub token invalid callback: {str(e)}"
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
            logging.warning(
                "🚫 EventSub missing scopes missing={missing} channel={channel}".format(
                    missing=";".join(missing), channel=channel_login
                )
            )

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
        logging.warning("🚫 EventSub subscription list unauthorized.")

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
            logging.info(f"⚠️ EventSub subscription list error: {str(e)}")
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
                    _ = asyncio.create_task(self._token_invalid_callback())
                except Exception as e:
                    logging.info(
                        f"⚠️ Error in EventSub token invalid callback: {str(e)}"
                    )
        elif action == "session_stale":
            # mark that we should perform a full resubscribe cycle after
            # reconnect rather than relying on session resume
            try:
                self._force_full_resubscribe = True
            except Exception as e:
                logging.info(f"⚠️ EventSub force_full_resubscribe error: {str(e)}")
        return action

    async def _resubscribe_missing(self, missing: set[str]) -> None:
        for ch, bid in self._channel_ids.items():
            if bid in missing:
                await self._subscribe_channel_chat(ch)
        logging.info(
            f"🔄 EventSub resubscribed missing count={len(missing)} total={len(self._channels)}"
        )

    async def _maybe_verify_subs(self, now: float) -> None:
        if now < self._next_sub_check:
            return
        try:
            await self._verify_subscriptions()
        except Exception as e:  # noqa: BLE001
            logging.info(f"⚠️ EventSub subscription check error: {str(e)}")
        # If fast audit pending (post-reconnect) schedule normal interval next, else schedule normal with jitter
        if self._fast_audit_pending:
            self._fast_audit_pending = False
            self._next_sub_check = now + self._audit_interval + self._jitter(0, 120.0)
        else:
            self._next_sub_check = now + self._audit_interval + self._jitter(0, 120.0)

    async def _ensure_socket(self) -> bool:
        if self._ws and not self._ws.closed:
            return True
        logging.info("⚠️ EventSub WebSocket closed detected")
        return await self._reconnect_with_backoff()

    async def _receive_one(self) -> aiohttp.WSMessage | None:
        if not self._ws:
            return None
        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=10)
            return msg
        except TimeoutError:
            if time.monotonic() - self._last_activity > self._stale_threshold:
                logging.info(
                    f"⚠️ EventSub stale socket idle={int(time.monotonic() - self._last_activity)}s"
                )
                ok = await self._reconnect_with_backoff()
                if not ok:
                    return None
            return None
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception as e:  # noqa: BLE001
            logging.warning(f"💥 EventSub listen loop error: {str(e)}")
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
            logging.info(
                f"🔄 EventSub forcing full resubscribe channels={len(self._channels)}"
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

        attempt = 0
        while not self._stop_event.is_set():
            attempt += 1
            try:
                # --- FULL STATE CLEANUP ---
                await self._reconnect_cleanup()

                # --- RECONNECT DELAY ---
                await asyncio.sleep(1.0)  # 1 second delay before reconnect

                logging.info(
                    "🔄 EventSub reconnect attempt={attempt} ws_url={ws_url} session_id={session_id} channels={channels}".format(
                        attempt=attempt,
                        ws_url=getattr(self, "_ws_url", None),
                        session_id=getattr(self, "_session_id", None),
                        channels=str(self._channels),
                    )
                )

                # --- HANDSHAKE WITH FULL LOGGING ---
                handshake_ok, handshake_details = await self._perform_handshake()
                logging.info(
                    "🤝 EventSub handshake result: attempt={attempt} ws_url={ws_url} session_id={session_id} handshake_ok={handshake_ok}".format(
                        attempt=attempt,
                        ws_url=getattr(self, "_ws_url", None),
                        session_id=getattr(self, "_session_id", None),
                        handshake_ok=handshake_ok,
                    )
                )
                if not handshake_ok:
                    raise RuntimeError(f"handshake failed: {handshake_details}")

                # subscribe / resubscribe work
                await self._do_subscribe_cycle()

                logging.info(
                    f"✅ EventSub reconnect success attempt={attempt} channels={len(self._channels)}"
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
            except Exception:  # noqa: BLE001
                logging.error(
                    f"❌ EventSub reconnect failed attempt={attempt} backoff={round(self._backoff, 2)}"
                )
                await asyncio.sleep(
                    self._backoff + self._jitter(0, 0.25 * self._backoff)
                )
                self._backoff = min(self._backoff * 2, self._max_backoff)
        return False

    async def _open_and_handshake_detailed(self):
        """Open WebSocket and parse welcome, logging all details for diagnostics."""
        try:
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
            handshake_details = {
                "request_headers": dict(getattr(ws, "_request_headers", {})),
                "url": self._ws_url,
            }

            # Handle challenge if needed
            challenge_handled = await self._handle_challenge_if_needed(
                ws, handshake_details
            )
            if not challenge_handled:
                return False, handshake_details

            # Process welcome message
            success, details = await self._process_welcome_message(
                ws, handshake_details
            )
            if success:
                self._pending_reconnect_session_id = None  # Clear on success
            handshake_details.update(details)
            return success, handshake_details

        except Exception as e:
            return False, {"exception": str(e)}

    async def _handle_challenge_if_needed(self, ws, handshake_details):
        """Handle challenge response flow if pending challenge exists."""
        if not getattr(self, "_pending_challenge", None):
            return True

        logging.info(
            f"🔐 EventSub challenge handshake start user={self._username} challenge={self._pending_challenge} ws_url={self._ws_url}"
        )
        handshake_details["challenge_handshake"] = True

        # Wait for challenge message
        try:
            challenge_msg = await asyncio.wait_for(ws.receive(), timeout=10)
            handshake_details["challenge_type"] = str(
                getattr(challenge_msg, "type", None)
            )

            if challenge_msg.type != aiohttp.WSMsgType.TEXT:
                handshake_details["challenge_error"] = "bad_challenge_type"
                self._pending_challenge = None
                return False

            challenge_data = json.loads(challenge_msg.data)
            received_challenge = challenge_data.get("challenge")
            handshake_details["challenge_received"] = received_challenge
            handshake_details["challenge_data"] = challenge_data

            if not isinstance(received_challenge, str):
                handshake_details["challenge_error"] = "no_challenge_value"
                self._pending_challenge = None
                return False

            # Verify challenge
            if received_challenge != self._pending_challenge:
                logging.warning(
                    f"⚠️ EventSub challenge mismatch expected={self._pending_challenge} received={received_challenge} user={self._username}"
                )
                self._pending_challenge = None
                return False

            # Send response
            response = {"type": "challenge_response", "challenge": received_challenge}
            await ws.send_json(response)
            logging.info(
                f"✅ EventSub challenge response sent user={self._username} challenge={received_challenge}"
            )
            handshake_details["challenge_response_sent"] = True

            self._pending_challenge = None
            logging.info(
                f"⌛ EventSub waiting for welcome after challenge user={self._username}"
            )
            return True

        except Exception as e:
            handshake_details["challenge_error"] = f"challenge_parse_error: {e}"
            self._pending_challenge = None
            return False

    async def _process_welcome_message(self, ws, handshake_details):
        """Process the welcome message after connection or challenge."""
        try:
            welcome = await asyncio.wait_for(ws.receive(), timeout=10)
            handshake_details["welcome_type"] = str(getattr(welcome, "type", None))
            handshake_details["welcome_raw"] = getattr(welcome, "data", None)

            # Handle close frames
            if welcome.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING):
                return await self._handle_close_frame(welcome, handshake_details)

            # Handle errors
            if welcome.type == aiohttp.WSMsgType.ERROR:
                handshake_details["error"] = "ws_error"
                handshake_details["exception"] = getattr(welcome, "data", None)
                return False, handshake_details

            # Validate text message
            if welcome.type != aiohttp.WSMsgType.TEXT:
                handshake_details["error"] = "bad_welcome_type"
                return False, handshake_details

            # Parse JSON
            data = json.loads(welcome.data)
            self._session_id = data.get("payload", {}).get("session", {}).get("id")
            handshake_details["session_id"] = self._session_id
            handshake_details["welcome_json"] = data

            if not self._session_id:
                handshake_details["error"] = "no_session_id"
                return False, handshake_details

            return True, handshake_details

        except Exception as e:
            handshake_details["error"] = f"welcome_parse_error: {e}"
            return False, handshake_details

    async def _handle_close_frame(self, welcome, handshake_details):
        """Handle WebSocket close frames during handshake."""
        handshake_details["error"] = "closed_by_server"
        close_code = getattr(welcome, "data", None)
        handshake_details["close_code"] = close_code
        handshake_details["close_reason"] = getattr(welcome, "extra", None)

        action = self._handle_close_action(close_code)
        handshake_details["mapped_action"] = action
        return False, handshake_details

    async def _safe_close(self) -> None:
        try:
            if self._ws and not self._ws.closed:
                await self._ws.close()
        except Exception as e:  # noqa: BLE001
            logging.debug(f"⚠️ EventSub safe close error: {str(e)}")
