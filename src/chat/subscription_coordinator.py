from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..utils.retry import retry_async

if TYPE_CHECKING:
    from .eventsub_backend import EventSubChatBackend


class SubscriptionCoordinator:
    """Handles subscription lifecycle including primary channel subscription, resubscription after reconnection, and channel joining/leaving."""

    def __init__(self, backend: EventSubChatBackend) -> None:
        self.backend = backend

    async def subscribe_primary_channel(self, user_ids: dict[str, str]) -> bool:
        """Subscribe to primary channel."""
        if not self.backend._sub_manager:
            return True
        if self.backend._primary_channel is None:
            return False
        channel_id = user_ids.get(self.backend._primary_channel)
        if not channel_id:
            return False
        success = await self.backend._sub_manager.subscribe_channel_chat(
            channel_id, self.backend._user_id or ""
        )
        if success:
            logging.info(f"✅ {self.backend._username} joined #{self.backend._primary_channel}")
        return success

    async def resubscribe_all_channels(self) -> bool:
        """Resubscribe to all channels after reconnection with retry logic."""
        if not self.backend._sub_manager or not self.backend._channel_resolver:
            return True
        all_success = True
        for channel in self.backend._channels:
            try:
                user_ids = await self.backend._channel_resolver.resolve_user_ids(
                    [channel], self.backend._token or "", self.backend._client_id or ""
                )
                channel_id = user_ids.get(channel)
                if channel_id:
                    # Retry subscription with exponential backoff
                    result = await self._subscribe_channel_with_retry(
                        channel_id, channel
                    )
                    if result is None:
                        logging.error(
                            f"Failed to resubscribe to {channel} after all retry attempts"
                        )
                        all_success = False
                    elif not result:
                        logging.warning(
                            f"Subscription failed for {channel} even after retries"
                        )
                        all_success = False
                else:
                    logging.warning(f"Could not resolve channel_id for {channel}")
                    all_success = False
            except Exception as e:
                logging.warning(f"Failed to resolve or resubscribe to {channel}: {e}")
                all_success = False
        return all_success

    async def _subscribe_channel_with_retry(
        self, channel_id: str, channel: str
    ) -> bool | None:
        """Subscribe to a channel with retry logic."""
        if not self.backend._sub_manager:
            return None
        sub_manager = self.backend._sub_manager

        async def subscribe_operation(attempt: int) -> tuple[bool | None, bool]:
            try:
                success = await sub_manager.subscribe_channel_chat(
                    channel_id, self.backend._user_id or ""
                )
                return success, not success  # success: don't retry, failure: retry
            except Exception as e:
                logging.warning(
                    f"Failed to resubscribe to {channel} (attempt {attempt}): {e}"
                )
                return False, True  # retry on exception

        return await retry_async(subscribe_operation, max_attempts=5)

    async def join_channel(self, channel: str) -> bool:
        """Joins a channel and subscribes to its chat messages."""
        channel_l = channel.lstrip("#").lower()
        if channel_l in self.backend._channels:
            return True

        try:
            # Resolve channel ID
            if self.backend._channel_resolver:
                user_ids = await self.backend._channel_resolver.resolve_user_ids(
                    [channel_l], self.backend._token or "", self.backend._client_id or ""
                )
                channel_id = user_ids.get(channel_l)
                if not channel_id:
                    return False

                # Subscribe
                if self.backend._sub_manager:
                    success = await self.backend._sub_manager.subscribe_channel_chat(
                        channel_id, self.backend._user_id or ""
                    )
                    if success:
                        self.backend._channels.append(channel_l)
                        logging.info(f"✅ {self.backend._username} joined #{channel_l}")
                        return True

            return False

        except Exception as e:
            logging.warning(f"Join channel failed: {str(e)}")
            return False
