from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .eventsub_backend import EventSubChatBackend
    from .message_transceiver import WSMessage


class MessageCoordinator:
    """Manages message processing flow including handling WebSocket messages, session reconnects, and idle optimization."""

    def __init__(self, backend: EventSubChatBackend) -> None:
        self.backend = backend

    async def handle_message(self, msg: WSMessage) -> bool:
        """Handle a single WebSocket message.

        Returns True if processing should continue, False to break the loop.
        """
        if msg.type == "text":
            self.backend._last_activity = time.monotonic()
            try:
                data = json.loads(msg.data)
                msg_type = data.get("type")
                if msg_type == "session_reconnect":
                    if self.backend._reconnection_coordinator is None:
                        raise AssertionError("ReconnectionCoordinator not initialized") from None
                    await self.backend._reconnection_coordinator.handle_session_reconnect(data)
                    return True
                elif msg_type == "session_keepalive":
                    logging.info("🏓 Received session_keepalive from Twitch")
                    return True
            except json.JSONDecodeError:
                logging.warning(f"Failed to parse WebSocket message: {msg.data}")
            if self.backend._msg_processor:
                await self.backend._msg_processor.process_message(msg.data)
            return True
        return True

    async def listen(self) -> None:
        """Listen for WebSocket messages and handle them with idle optimization."""
        if not self.backend._ws_manager or not self.backend._ws_manager.is_connected:
            return

        # Idle optimization: longer sleep when no recent activity
        idle_sleep_time = 0.1  # 100ms base sleep
        max_idle_sleep = 1.0   # 1s max sleep during idle
        idle_threshold = 30.0  # 30s of no activity = idle

        consecutive_idles = 0
        max_consecutive_idles = 10

        while not self.backend._stop_event.is_set():
            now = time.monotonic()

            # Check if we should enter idle mode
            time_since_activity = now - self.backend._last_activity
            is_idle = time_since_activity > idle_threshold

            if is_idle and consecutive_idles < max_consecutive_idles:
                # Gradually increase sleep time during idle periods
                sleep_time = min(idle_sleep_time * (2 ** consecutive_idles), max_idle_sleep)
                await asyncio.sleep(sleep_time)
                consecutive_idles += 1
                continue
            elif consecutive_idles >= max_consecutive_idles:
                # Reset idle counter periodically to stay responsive
                consecutive_idles = 0

            # Normal operation - check subscriptions
            await self.backend._maybe_verify_subs(now)


            try:
                msg = await self.backend._ws_manager.receive_message()
                if not await self.handle_message(msg):
                    break
                # Reset idle counter on activity
                consecutive_idles = 0
            except Exception as e:
                # Handle timeout exceptions specifically
                if isinstance(e, TimeoutError) or "timeout" in str(e).lower():
                    # Timeout is expected during idle - just continue
                    if not is_idle:
                        logging.debug("WebSocket receive timeout during active period")
                    consecutive_idles += 1

                    # If connection is stale, trigger reconnect
                    if time_since_activity > self.backend._stale_threshold:
                        logging.warning(f"🔄 Connection stale ({time_since_activity:.1f}s > {self.backend._stale_threshold}s), last_activity={self.backend._last_activity}, current_time={now}, triggering reconnect")
                        if self.backend._reconnection_coordinator is None:
                            raise AssertionError("ReconnectionCoordinator not initialized") from None
                        if not await self.backend._reconnection_coordinator.handle_reconnect():
                            break
                    continue
                else:
                    logging.warning(f"Listen loop error: {str(e)}")
                    consecutive_idles += 1
                    if self.backend._reconnection_coordinator is None:
                        raise AssertionError("ReconnectionCoordinator not initialized") from None
                    if not await self.backend._reconnection_coordinator.handle_reconnect():
                        break
