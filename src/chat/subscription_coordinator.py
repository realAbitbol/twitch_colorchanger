from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..utils.retry import RetryExhaustedError, retry_async

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
        logging.info(f"🔄 Starting resubscription for {len(self.backend._channels)} channels: {self.backend._channels}")
        if not self.backend._sub_manager or not self.backend._channel_resolver:
            logging.warning("🔄 Resubscription skipped: sub_manager or channel_resolver not available")
            return True
        all_success = True
        for channel in self.backend._channels:
            try:
                logging.info(f"🔄 Resolving user ID for channel {channel}")
                user_ids = await self._resolve_channel_with_token_refresh([channel])
                channel_id = user_ids.get(channel)
                if channel_id:
                    logging.info(f"🔄 Attempting to resubscribe to {channel} (ID: {channel_id})")
                    # Retry subscription with exponential backoff
                    result = await self._subscribe_channel_with_retry(
                        channel_id, channel
                    )
                    if result is None:
                        raise Exception(
                            f"Failed to resubscribe to {channel} after all retry attempts"
                        )
                    elif not result:
                        raise Exception(
                            f"Subscription failed for {channel} even after retries"
                        )
                    else:
                        logging.info(f"✅ Successfully resubscribed to {channel}")
                        # Validate subscriptions are active after resubscription
                        if self.backend._sub_manager:
                            active_channels = await self.backend._sub_manager.verify_subscriptions()
                            if channel_id not in active_channels:
                                raise Exception(f"Subscription validation failed for {channel}")
                else:
                    raise Exception(f"Could not resolve channel_id for {channel}")
            except Exception as e:
                logging.error(f"Failed to resolve or resubscribe to {channel}: {e}")
                all_success = False
        logging.info(f"🔄 Resubscription completed: {'success' if all_success else 'partial failure'}")
        return all_success

    async def _resolve_channel_with_token_refresh(self, channels: list[str]) -> dict[str, str]:
        """Resolve channels with token refresh on 401 errors."""
        if not self.backend._channel_resolver:
            return {}

        try:
            user_ids = await self.backend._channel_resolver.resolve_user_ids(
                channels, self.backend._token or "", self.backend._client_id or ""
            )
            # Check if all channels were resolved
            if all(ch in user_ids for ch in channels):
                return user_ids
            # If not all resolved, might be 401, try refresh
            if self.backend._token_manager:
                logging.info("🔄 Attempting token refresh due to channel resolution failure")
                refreshed = await self.backend._token_manager.refresh_token()
                if refreshed:
                    # Retry with new token
                    user_ids = await self.backend._channel_resolver.resolve_user_ids(
                        channels, self.backend._token or "", self.backend._client_id or ""
                    )
                    return user_ids
        except Exception as e:
            logging.warning(f"Channel resolution failed: {e}")

        return user_ids

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

        try:
            return await retry_async(subscribe_operation, max_attempts=5)
        except RetryExhaustedError:
            return None

    async def join_channel(self, channel: str) -> bool:
        """Joins a channel and subscribes to its chat messages."""
        channel_l = channel.lstrip("#").lower()
        if channel_l in self.backend._channels:
            return True

        try:
            # Resolve channel ID with token refresh
            user_ids = await self._resolve_channel_with_token_refresh([channel_l])
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

    async def leave_channel(self, channel: str) -> bool:
        """Leaves a channel and unsubscribes from its chat messages."""
        channel_l = channel.lstrip("#").lower()
        if channel_l not in self.backend._channels:
            return True

        try:
            # Resolve channel ID to find subscription
            channel_id = None
            user_ids = await self._resolve_channel_with_token_refresh([channel_l])
            channel_id = user_ids.get(channel_l)

            # Find and unsubscribe from subscription
            if self.backend._sub_manager and channel_id:
                # Find subscription ID for this channel
                sub_id_to_remove = None
                for sub_id, active_channel_id in self.backend._sub_manager._active_subscriptions.items():
                    if active_channel_id == channel_id:
                        sub_id_to_remove = sub_id
                        break

                if sub_id_to_remove:
                    try:
                        await self.backend._sub_manager._unsubscribe_single(sub_id_to_remove)
                        # Remove from active subscriptions
                        del self.backend._sub_manager._active_subscriptions[sub_id_to_remove]
                    except Exception as e:
                        logging.warning(f"Failed to unsubscribe from {channel_l}: {str(e)}")
                        # Continue with channel removal even if unsubscription fails

            # Remove from channels list
            self.backend._channels.remove(channel_l)
            logging.info(f"✅ {self.backend._username} left #{channel_l}")
            return True

        except Exception as e:
            logging.warning(f"Leave channel failed: {str(e)}")
            # Still try to remove from channels if possible
            try:
                if channel_l in self.backend._channels:
                    self.backend._channels.remove(channel_l)
            except ValueError:
                pass
            return False
