"""SubscriptionManager for managing EventSub subscriptions.

This module provides the SubscriptionManager class, responsible for creating,
verifying, and cleaning up EventSub subscriptions for Twitch chat messages.
It implements rate limiting, error handling, and tracks active subscriptions.
"""

import asyncio
import logging
from typing import Any

from ..api.twitch import TwitchAPI
from ..errors.eventsub import AuthenticationError, SubscriptionError
from .protocols import SubscriptionManagerProtocol

EVENTSUB_SUBSCRIPTIONS = "eventsub/subscriptions"
EVENTSUB_CHAT_MESSAGE = "channel.chat.message"


class SubscriptionManager(SubscriptionManagerProtocol):
    """Manages EventSub subscription creation, verification, and cleanup.

    This class handles the lifecycle of EventSub subscriptions for channel chat messages,
    including rate limiting to prevent API abuse, error handling with custom exceptions,
    and tracking of active subscriptions for verification and cleanup.

    Attributes:
        _api (TwitchAPI): The Twitch API client instance.
        _session_id (str): The current EventSub session ID.
        _token (str): OAuth access token for API requests.
        _client_id (str): Twitch application client ID.
        _active_subscriptions (dict[str, str]): Mapping of subscription ID to channel ID.
        _rate_limiter (asyncio.Semaphore): Semaphore for rate limiting concurrent subscriptions.
    """

    def __init__(self, api: TwitchAPI, session_id: str, token: str, client_id: str):
        """Initialize the SubscriptionManager.

        Args:
            api (TwitchAPI): The Twitch API client instance.
            session_id (str): The current EventSub session ID.
            token (str): OAuth access token for API requests.
            client_id (str): Twitch application client ID.

        Raises:
            ValueError: If any required parameter is None or empty.
        """
        if not api:
            raise ValueError("TwitchAPI instance required")
        if not session_id or not isinstance(session_id, str):
            raise ValueError("Valid session_id required")
        if not token or not isinstance(token, str):
            raise ValueError("Valid token required")
        if not client_id or not isinstance(client_id, str):
            raise ValueError("Valid client_id required")

        self._api = api
        self._session_id = session_id
        self._token = token
        self._client_id = client_id
        self._active_subscriptions: dict[str, str] = {}  # sub_id -> channel_id
        self._rate_limiter = asyncio.Semaphore(
            10
        )  # Limit to 10 concurrent subscriptions

    async def subscribe_channel_chat(self, channel_id: str, user_id: str) -> bool:
        """Subscribe to chat messages for a specific channel.

        Creates an EventSub subscription for channel.chat.message events filtered
        for the specified user ID. Implements rate limiting and error handling.

        Args:
            channel_id (str): The broadcaster user ID of the channel.
            user_id (str): The user ID to filter messages for (typically the bot's ID).

        Returns:
            bool: True if subscription was successful, False otherwise.

        Raises:
            SubscriptionError: If subscription creation fails.
            AuthenticationError: If authentication fails (401).
            EventSubError: For other EventSub-related errors.
        """
        async with self._rate_limiter:
            try:
                body = self._build_subscription_body(channel_id, user_id)
                data, status, _ = await self._api.request(
                    "POST",
                    EVENTSUB_SUBSCRIPTIONS,
                    access_token=self._token,
                    client_id=self._client_id,
                    json_body=body,
                )

                if status == 202:
                    # Extract subscription ID from response
                    sub_id = self._extract_subscription_id(data)
                    if sub_id:
                        self._active_subscriptions[sub_id] = channel_id
                        return True
                    else:
                        logging.warning(
                            f"⚠️ EventSub subscription created but no ID returned for channel {channel_id}"
                        )
                        return False

                elif status == 401:
                    raise AuthenticationError(
                        f"Subscription failed: unauthorized for channel {channel_id}",
                        operation_type="subscribe",
                    )
                elif status == 403:
                    raise SubscriptionError(
                        f"Subscription failed: forbidden for channel {channel_id}",
                        operation_type="subscribe",
                    )
                else:
                    raise SubscriptionError(
                        f"Subscription failed: HTTP {status} for channel {channel_id}",
                        operation_type="subscribe",
                    )

            except (AuthenticationError, SubscriptionError):
                raise
            except Exception as e:
                raise SubscriptionError(
                    f"Subscription error for channel {channel_id}: {str(e)}",
                    operation_type="subscribe",
                ) from e

    async def verify_subscriptions(self) -> list[str]:
        """Verify active subscriptions and return list of active channel IDs.

        Fetches current active subscriptions from Twitch and returns a list
        of channel IDs that have active subscriptions matching this session.

        Returns:
            list[str]: List of active channel IDs.

        Raises:
            SubscriptionError: If verification fails.
            AuthenticationError: If authentication fails.
        """
        try:
            active_channel_ids = await self._fetch_active_channel_ids()
            # Update active subscriptions based on verification
            self._active_subscriptions = {
                sub_id: channel_id
                for sub_id, channel_id in self._active_subscriptions.items()
                if channel_id in active_channel_ids
            }
            return active_channel_ids
        except Exception as e:
            if isinstance(e, AuthenticationError | SubscriptionError):
                raise
            raise SubscriptionError(
                f"Verification error: {str(e)}", operation_type="verify"
            ) from e

    async def unsubscribe_all(self) -> None:
        """Unsubscribe from all active subscriptions.

        Sends DELETE requests for all tracked active subscriptions and clears
        the internal tracking.

        Raises:
            SubscriptionError: If unsubscription fails.
        """
        if not self._active_subscriptions:
            return

        errors = []
        for sub_id in self._active_subscriptions:
            try:
                await self._unsubscribe_single(sub_id)
            except Exception as e:
                errors.append(f"Failed to unsubscribe {sub_id}: {str(e)}")
                logging.warning(f"⚠️ EventSub unsubscribe failed for {sub_id}: {str(e)}")

        self._active_subscriptions.clear()

        if errors:
            raise SubscriptionError(
                f"Unsubscribe errors: {'; '.join(errors)}", operation_type="unsubscribe"
            )

        logging.info("✅ EventSub unsubscribed from all subscriptions")

    def get_active_channel_ids(self) -> list[str]:
        """Get list of channel IDs with active subscriptions.

        Returns:
            list[str]: List of channel IDs currently tracked as active.
        """
        return list(set(self._active_subscriptions.values()))

    def update_session_id(self, new_session_id: str) -> None:
        """Update the session ID for new subscriptions.

        Args:
            new_session_id (str): The new EventSub session ID.

        Raises:
            ValueError: If session_id is invalid.
        """
        if not new_session_id or not isinstance(new_session_id, str):
            raise ValueError("Valid session_id required")
        self._session_id = new_session_id
        logging.info(f"🔄 EventSub session ID updated to {new_session_id}")

    async def __aenter__(self) -> "SubscriptionManager":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        await self.unsubscribe_all()

    def _build_subscription_body(self, channel_id: str, user_id: str) -> dict[str, Any]:
        """Build the JSON body for subscription request.

        Args:
            channel_id (str): The broadcaster user ID.
            user_id (str): The user ID to filter for.

        Returns:
            dict[str, Any]: The subscription request body.
        """
        return {
            "type": EVENTSUB_CHAT_MESSAGE,
            "version": "1",
            "condition": {
                "broadcaster_user_id": channel_id,
                "user_id": user_id,
            },
            "transport": {"method": "websocket", "session_id": self._session_id},
        }

    def _extract_subscription_id(self, data: Any) -> str | None:
        """Extract subscription ID from API response.

        Args:
            data (Any): The API response data.

        Returns:
            str | None: The subscription ID if found, None otherwise.
        """
        if isinstance(data, dict):
            data_list = data.get("data")
            if isinstance(data_list, list) and data_list:
                sub_data = data_list[0]
                if isinstance(sub_data, dict):
                    sub_id = sub_data.get("id")
                    if isinstance(sub_id, str):
                        return sub_id
        return None

    async def _fetch_active_channel_ids(self) -> list[str]:
        """Fetch active channel IDs from Twitch API.

        Returns:
            list[str]: List of active channel IDs for this session.

        Raises:
            AuthenticationError: If authentication fails.
            SubscriptionError: If fetch fails.
        """
        try:
            data, status, _ = await self._api.request(
                "GET",
                EVENTSUB_SUBSCRIPTIONS,
                access_token=self._token,
                client_id=self._client_id,
            )

            if status == 401:
                raise AuthenticationError(
                    "Subscription verification failed: unauthorized",
                    operation_type="verify",
                )
            elif status != 200:
                raise SubscriptionError(
                    f"Subscription verification failed: HTTP {status}",
                    operation_type="verify",
                )

            if not isinstance(data, dict):
                return []

            rows = data.get("data")
            if not isinstance(rows, list):
                return []

            active_channel_ids = []
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") != EVENTSUB_CHAT_MESSAGE:
                    continue
                transport = entry.get("transport", {})
                if transport.get("session_id") != self._session_id:
                    continue
                cond = entry.get("condition", {})
                channel_id = cond.get("broadcaster_user_id")
                if isinstance(channel_id, str):
                    active_channel_ids.append(channel_id)

            return active_channel_ids

        except (AuthenticationError, SubscriptionError):
            raise
        except Exception as e:
            raise SubscriptionError(
                f"Fetch active subscriptions error: {str(e)}", operation_type="verify"
            ) from e

    async def _unsubscribe_single(self, sub_id: str) -> None:
        """Unsubscribe from a single subscription.

        Args:
            sub_id (str): The subscription ID to unsubscribe.

        Raises:
            SubscriptionError: If unsubscription fails.
        """
        try:
            _, status, _ = await self._api.request(
                "DELETE",
                f"{EVENTSUB_SUBSCRIPTIONS}?id={sub_id}",
                access_token=self._token,
                client_id=self._client_id,
            )

            if status == 204:
                logging.debug(f"✅ EventSub unsubscribed from {sub_id}")
            elif status == 401:
                raise AuthenticationError(
                    f"Unsubscribe failed: unauthorized for {sub_id}",
                    operation_type="unsubscribe",
                )
            elif status == 404:
                logging.warning(
                    f"⚠️ EventSub subscription {sub_id} not found (already unsubscribed)"
                )
            else:
                raise SubscriptionError(
                    f"Unsubscribe failed: HTTP {status} for {sub_id}",
                    operation_type="unsubscribe",
                )

        except (AuthenticationError, SubscriptionError):
            raise
        except Exception as e:
            raise SubscriptionError(
                f"Unsubscribe error for {sub_id}: {str(e)}",
                operation_type="unsubscribe",
            ) from e
