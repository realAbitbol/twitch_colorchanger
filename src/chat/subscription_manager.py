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
from .cleanup_coordinator import CleanupCoordinator
from .protocols import SubscriptionManagerProtocol

EVENTSUB_SUBSCRIPTIONS = "eventsub/subscriptions"
EVENTSUB_CHAT_MESSAGE = "channel.chat.message"
SUBSCRIPTION_VERIFICATION_FAILED_UNAUTHORIZED = (
    "Subscription verification failed: unauthorized"
)


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

    def __init__(
        self,
        api: TwitchAPI,
        session_id: str,
        token: str,
        client_id: str,
        token_manager: Any = None,
        cleanup_coordinator: CleanupCoordinator | None = None,
    ):
        """Initialize the SubscriptionManager.

        Args:
            api (TwitchAPI): The Twitch API client instance.
            session_id (str): The current EventSub session ID.
            token (str): OAuth access token for API requests.
            client_id (str): Twitch application client ID.
            token_manager: Optional token manager for refresh on 401.
            cleanup_coordinator: Optional cleanup coordinator for coordinated cleanup.

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
        self._token_manager = token_manager
        self._cleanup_coordinator = cleanup_coordinator
        self._active_subscriptions: dict[str, str] = {}  # sub_id -> channel_id
        self._rate_limiter = asyncio.Semaphore(
            10
        )  # Limit to 10 concurrent subscriptions
        self._token_lock = asyncio.Lock()  # Lock for atomic token updates
        self._cleanup_registered = False

    async def subscribe_channel_chat(self, channel_id: str, user_id: str) -> bool:
        """Subscribe to chat messages for a specific user in a channel.

        Creates an EventSub subscription for channel.chat.message events for a specific user
        in the channel. Implements rate limiting and error handling.

        Args:
            channel_id (str): The broadcaster user ID of the channel.
            user_id (str): The user ID to filter messages for.

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
                logging.debug(
                    f"📡 Subscribing to channel {channel_id} with session_id {self._session_id}, payload: {body}"
                )
                return await self._handle_subscription_request(body, channel_id)
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

    async def cleanup_stale_subscriptions(self) -> None:
        """Clean up stale EventSub subscriptions from previous sessions.

        Queries all existing EventSub subscriptions from Twitch API, filters for
        'channel.chat.message' type subscriptions with session IDs not in the
        active sessions list, and deletes them. This prevents accumulation of
        stale subscriptions.

        Handles API errors gracefully without failing startup. Logs the number
        of subscriptions found, deleted, and any errors encountered.

        Raises:
            None: Errors are logged but do not propagate to prevent startup failure.
        """
        try:
            # Get active session IDs from coordinator
            active_session_ids = []
            if self._cleanup_coordinator:
                active_session_ids = self._cleanup_coordinator.get_active_session_ids()

            logging.debug(f"🧹 Starting cleanup for active sessions: {active_session_ids}")
            data, status, _ = await self._api.request(
                "GET",
                EVENTSUB_SUBSCRIPTIONS,
                access_token=self._token,
                client_id=self._client_id,
            )

            if status == 401:
                data, status = await self._refresh_token_and_retry_get()
                if status == 401:
                    logging.warning("⚠️ Cannot cleanup stale subscriptions: authentication failed")
                    return

            if status != 200:
                logging.warning(f"⚠️ Cannot cleanup stale subscriptions: HTTP {status}")
                return

            stale_sub_ids = self._extract_stale_subscription_ids(data, active_session_ids)
            logging.info(f"🧹 Found {len(stale_sub_ids)} stale subscriptions to cleanup for active sessions {active_session_ids}")

            deleted_count = 0
            error_count = 0
            for sub_id in stale_sub_ids:
                try:
                    await self._unsubscribe_single(sub_id)
                    deleted_count += 1
                    logging.debug(f"✅ Cleaned up stale subscription {sub_id}")
                except Exception as e:
                    error_count += 1
                    logging.warning(f"⚠️ Failed to cleanup stale subscription {sub_id}: {str(e)}")

            if stale_sub_ids:
                logging.info(f"🧹 Cleanup completed: {deleted_count} deleted, {error_count} errors for active sessions {active_session_ids}")

        except Exception as e:
            logging.warning(f"⚠️ Error during stale subscription cleanup: {str(e)}")

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

    async def _cleanup_old_session_subscriptions(self, old_session_id: str) -> None:
        """Clean up subscriptions from an old session.

        Args:
            old_session_id (str): The old session ID to clean up subscriptions for.
        """
        try:
            data, status, _ = await self._api.request(
                "GET",
                EVENTSUB_SUBSCRIPTIONS,
                access_token=self._token,
                client_id=self._client_id,
            )

            if status == 401:
                data, status = await self._refresh_token_and_retry_get()
                if status == 401:
                    logging.warning(f"⚠️ Cannot cleanup old session {old_session_id}: authentication failed")
                    return

            if status != 200:
                logging.warning(f"⚠️ Cannot cleanup old session {old_session_id}: HTTP {status}")
                return

            # Extract subscription IDs for the old session
            old_sub_ids = self._extract_subscription_ids_for_session(data, old_session_id)

            # Unsubscribe from old subscriptions
            for sub_id in old_sub_ids:
                try:
                    await self._unsubscribe_single(sub_id)
                    logging.debug(f"✅ Cleaned up old subscription {sub_id} from session {old_session_id}")
                except Exception as e:
                    logging.warning(f"⚠️ Failed to cleanup old subscription {sub_id}: {str(e)}")

            if old_sub_ids:
                logging.info(f"🧹 Cleaned up {len(old_sub_ids)} subscriptions from old session {old_session_id}")

        except Exception as e:
            logging.warning(f"⚠️ Error during cleanup of old session {old_session_id}: {str(e)}")

    def _extract_subscription_ids_for_session(self, data: Any, session_id: str) -> list[str]:
        """Extract subscription IDs for a specific session from API response data.

        Args:
            data (Any): The API response data.
            session_id (str): The session ID to filter by.

        Returns:
            list[str]: List of subscription IDs for the session.
        """
        if not isinstance(data, dict):
            return []

        rows = data.get("data")
        if not isinstance(rows, list):
            return []

        sub_ids = []
        for entry in rows:
            if not isinstance(entry, dict):
                continue

            transport = entry.get("transport", {})
            if (
                not isinstance(transport, dict)
                or transport.get("session_id") != session_id
            ):
                continue

            sub_id = entry.get("id")
            if isinstance(sub_id, str):
                sub_ids.append(sub_id)

        return sub_ids

    def _extract_stale_subscription_ids(self, data: Any, active_session_ids: list[str]) -> list[str]:
        """Extract subscription IDs for stale subscriptions from API response data.

        Filters for 'channel.chat.message' type subscriptions where the transport
        session_id is not in the active session IDs list. Also identifies any
        session IDs that appear in API but aren't tracked in coordinator.

        Args:
            data (Any): The API response data.
            active_session_ids (list[str]): List of active session IDs.

        Returns:
            list[str]: List of subscription IDs for stale subscriptions.
        """
        if not isinstance(data, dict):
            return []

        rows = data.get("data")
        if not isinstance(rows, list):
            return []

        stale_sub_ids = []
        session_ids_found = set()
        unregistered_sessions = set()

        for entry in rows:
            if not isinstance(entry, dict):
                continue

            # Only process channel.chat.message subscriptions
            if entry.get("type") != EVENTSUB_CHAT_MESSAGE:
                continue

            transport = entry.get("transport", {})
            if not isinstance(transport, dict):
                continue

            # Check if session_id is not in active sessions
            session_id = transport.get("session_id")
            if isinstance(session_id, str):
                session_ids_found.add(session_id)
                if (session_id not in active_session_ids and
                    session_id != self._session_id):
                    # Check if this is a session from previous run (not current session)
                    sub_id = entry.get("id")
                    if isinstance(sub_id, str):
                        stale_sub_ids.append(sub_id)
                        unregistered_sessions.add(session_id)

        # Log unregistered sessions found in API but not in coordinator
        if unregistered_sessions:
            logging.warning(f"🧹 Found unregistered session IDs in API: {sorted(unregistered_sessions)}")

        logging.debug(f"🧹 Session IDs found in subscriptions: {sorted(session_ids_found)} for active sessions {active_session_ids}")
        return stale_sub_ids

    async def update_session_id(self, new_session_id: str) -> None:
        """Update the session ID for new subscriptions.

        Performs atomic cleanup of subscriptions from the old session
        before updating to the new session ID. Uses proper locking to
        prevent race conditions.

        Args:
            new_session_id (str): The new EventSub session ID.

        Raises:
            ValueError: If session_id is invalid.
        """
        if not new_session_id or not isinstance(new_session_id, str):
            raise ValueError("Valid session_id required")

        # Clean up subscriptions from the old session before updating
        old_session_id = self._session_id
        if old_session_id != new_session_id:
            logging.info(f"🧹 Starting atomic cleanup of subscriptions from old session {old_session_id}")

            # Use atomic operation: cleanup old session and register new session together
            if self._cleanup_coordinator:
                async with self._token_lock:  # Use existing token lock for atomicity
                    await self._cleanup_old_session_subscriptions(old_session_id)
                    await self._cleanup_coordinator.unregister_session_id(old_session_id)
                    await self._cleanup_coordinator.register_session_id(new_session_id)

            logging.info(f"✅ Completed atomic cleanup of old session {old_session_id}")

        self._session_id = new_session_id
        logging.info(f"🔄 EventSub session ID updated to {new_session_id}")

    def update_access_token(self, new_access_token: str) -> None:
        """Update the access token for API requests.

        Args:
            new_access_token (str): The new access token.

        Raises:
            ValueError: If access_token is invalid.
        """
        if not new_access_token or not isinstance(new_access_token, str):
            raise ValueError("Valid access_token required")
        self._token = new_access_token
        logging.info("🔄 EventSub access token updated")

    async def register_cleanup_task(self) -> bool:
        """Register the cleanup task with the coordinator.

        Returns:
            bool: True if elected as active cleanup manager, False otherwise.
        """
        if not self._cleanup_coordinator:
            logging.debug("No cleanup coordinator available, skipping registration")
            return False

        if self._cleanup_registered:
            logging.debug("Cleanup task already registered")
            return False

        # Register session ID with coordinator
        await self._cleanup_coordinator.register_session_id(self._session_id)

        elected = await self._cleanup_coordinator.register_cleanup_task(
            self.cleanup_stale_subscriptions
        )
        self._cleanup_registered = True

        if elected:
            logging.info("🧹 Elected as active cleanup manager")
        else:
            logging.info("🧹 Registered as passive cleanup manager")

        return elected


    async def __aenter__(self) -> "SubscriptionManager":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        if self._cleanup_coordinator and self._cleanup_registered:
            await self._cleanup_coordinator.unregister_cleanup_task(
                self.cleanup_stale_subscriptions
            )
            await self._cleanup_coordinator.unregister_session_id(self._session_id)
            self._cleanup_registered = False
        await self.unsubscribe_all()

    async def _handle_subscription_request(
        self, body: dict[str, Any], channel_id: str
    ) -> bool:
        """Handle the subscription API request and process response.

        Args:
            body (dict[str, Any]): The request body.
            channel_id (str): The channel ID.

        Returns:
            bool: True if successful.

        Raises:
            AuthenticationError: On 401.
            SubscriptionError: On other errors.
        """
        data, status, _ = await self._api.request(
            "POST",
            EVENTSUB_SUBSCRIPTIONS,
            access_token=self._token,
            client_id=self._client_id,
            json_body=body,
        )

        if status == 202:
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
            logging.error(
                f"Subscription failed: unauthorized for channel {channel_id}, response: {data}"
            )
            return await self._handle_401_and_retry(body, channel_id)
        elif status == 403:
            logging.error(
                f"Subscription failed: forbidden for channel {channel_id}, response: {data}"
            )
            raise SubscriptionError(
                f"Subscription failed: forbidden for channel {channel_id}",
                operation_type="subscribe",
            )
        else:
            logging.error(
                f"Subscription failed: HTTP {status} for channel {channel_id}, response: {data}"
            )
            raise SubscriptionError(
                f"Subscription failed: HTTP {status} for channel {channel_id}",
                operation_type="subscribe",
            )

    async def _handle_401_and_retry(
        self, body: dict[str, Any], channel_id: str
    ) -> bool:
        """Handle 401 error by refreshing token and retrying.

        Args:
            body (dict[str, Any]): The request body.
            channel_id (str): The channel ID.

        Returns:
            bool: True if successful after retry.

        Raises:
            AuthenticationError: If refresh fails or still 401.
            SubscriptionError: On other retry errors.
        """
        if not self._token_manager:
            raise AuthenticationError(
                f"Subscription failed: unauthorized for channel {channel_id}",
                operation_type="subscribe",
            )

        refreshed = await self._token_manager.refresh_token()
        if not refreshed:
            await self._token_manager.handle_401_error()
            raise AuthenticationError(
                f"Subscription failed: unauthorized for channel {channel_id}",
                operation_type="subscribe",
            )

        try:
            info = await self._token_manager.token_manager.get_info(
                self._token_manager.username
            )
            if not info or not info.access_token:
                await self._token_manager.handle_401_error()
                raise AuthenticationError(
                    f"Subscription failed: unauthorized for channel {channel_id}",
                    operation_type="subscribe",
                )

            async with self._token_lock:
                self._token = info.access_token
            self._token_manager.reset_401_counter()

            # Retry the request
            data, status, _ = await self._api.request(
                "POST",
                EVENTSUB_SUBSCRIPTIONS,
                access_token=self._token,
                client_id=self._client_id,
                json_body=body,
            )
            if status == 202:
                sub_id = self._extract_subscription_id(data)
                if sub_id:
                    self._active_subscriptions[sub_id] = channel_id
                    return True
                else:
                    logging.warning(
                        f"⚠️ EventSub subscription created after retry but no ID returned for channel {channel_id}"
                    )
                    return False
            elif status == 401:
                logging.error(
                    f"Subscription failed after retry: unauthorized for channel {channel_id}, response: {data}"
                )
                await self._token_manager.handle_401_error()
                raise AuthenticationError(
                    f"Subscription failed: unauthorized for channel {channel_id}",
                    operation_type="subscribe",
                )
            else:
                logging.error(
                    f"Subscription failed after retry: HTTP {status} for channel {channel_id}, response: {data}"
                )
                raise SubscriptionError(
                    f"Subscription failed after retry: HTTP {status} for channel {channel_id}",
                    operation_type="subscribe",
                )
        except Exception as e:
            logging.warning(
                f"⚠️ Token refresh failed during subscription for channel {channel_id}: {str(e)}"
            )
            await self._token_manager.handle_401_error()
            raise AuthenticationError(
                f"Subscription failed: unauthorized for channel {channel_id}",
                operation_type="subscribe",
            ) from e

    async def _handle_401_and_retry_unsubscribe(self, sub_id: str) -> None:
        """Handle 401 error by refreshing token and retrying unsubscribe.

        Args:
            sub_id (str): The subscription ID.

        Raises:
            AuthenticationError: If refresh fails or still 401.
            SubscriptionError: On other retry errors.
        """
        if not self._token_manager:
            raise AuthenticationError(
                f"Unsubscribe failed: unauthorized for {sub_id}",
                operation_type="unsubscribe",
            )

        refreshed = await self._token_manager.refresh_token()
        if not refreshed:
            await self._token_manager.handle_401_error()
            raise AuthenticationError(
                f"Unsubscribe failed: unauthorized for {sub_id}",
                operation_type="unsubscribe",
            )

        try:
            info = await self._token_manager.token_manager.get_info(
                self._token_manager.username
            )
            if not info or not info.access_token:
                await self._token_manager.handle_401_error()
                raise AuthenticationError(
                    f"Unsubscribe failed: unauthorized for {sub_id}",
                    operation_type="unsubscribe",
                )

            async with self._token_lock:
                self._token = info.access_token
            self._token_manager.reset_401_counter()

            # Retry the request
            _, status, _ = await self._api.request(
                "DELETE",
                f"{EVENTSUB_SUBSCRIPTIONS}?id={sub_id}",
                access_token=self._token,
                client_id=self._client_id,
            )
            if status == 204:
                logging.debug(f"✅ EventSub unsubscribed from {sub_id} after retry")
            elif status == 401:
                await self._token_manager.handle_401_error()
                raise AuthenticationError(
                    f"Unsubscribe failed: unauthorized for {sub_id}",
                    operation_type="unsubscribe",
                )
            else:
                raise SubscriptionError(
                    f"Unsubscribe failed after retry: HTTP {status} for {sub_id}",
                    operation_type="unsubscribe",
                )
        except Exception as e:
            logging.warning(
                f"⚠️ Token refresh failed during unsubscribe for {sub_id}: {str(e)}"
            )
            await self._token_manager.handle_401_error()
            raise AuthenticationError(
                f"Unsubscribe failed: unauthorized for {sub_id}",
                operation_type="unsubscribe",
            ) from e

    def _build_subscription_body(self, channel_id: str, user_id: str) -> dict[str, Any]:
        """Build the JSON body for subscription request.

        Args:
            channel_id (str): The broadcaster user ID.
            user_id (str): The user ID to filter messages for.

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

    def _extract_active_channel_ids_from_data(self, data: Any) -> list[str]:
        """Extract active channel IDs from API response data.

        Args:
            data (Any): The API response data.

        Returns:
            list[str]: List of active channel IDs.
        """
        if not isinstance(data, dict):
            logging.warning("⚠️ Invalid API response data type for subscriptions")
            return []

        rows = data.get("data")
        if not isinstance(rows, list):
            logging.warning("⚠️ Invalid data structure in subscriptions response")
            return []

        active_channel_ids = []
        session_ids_found = set()
        mismatched_count = 0
        for entry in rows:
            if not isinstance(entry, dict):
                logging.debug("⚠️ Skipping non-dict entry in subscriptions")
                continue

            if entry.get("type") != EVENTSUB_CHAT_MESSAGE:
                logging.debug(f"⚠️ Skipping entry with type {entry.get('type')}")
                continue

            transport = entry.get("transport", {})
            if not isinstance(transport, dict):
                logging.debug("⚠️ Skipping entry with invalid transport")
                continue

            session_id = transport.get("session_id")
            if isinstance(session_id, str):
                session_ids_found.add(session_id)
                if session_id != self._session_id:
                    logging.debug("⚠️ Skipping entry with mismatched session_id")
                    mismatched_count += 1
                    continue

            cond = entry.get("condition", {})
            if not isinstance(cond, dict):
                logging.debug("⚠️ Skipping entry with invalid condition")
                continue

            channel_id = cond.get("broadcaster_user_id")
            if not isinstance(channel_id, str):
                logging.debug("⚠️ Skipping entry with invalid broadcaster_user_id")
                continue

            active_channel_ids.append(channel_id)

        logging.debug(f"🔍 Verification session_ids found: {sorted(session_ids_found)}, mismatched: {mismatched_count} for session {self._session_id}")
        return active_channel_ids

    async def _refresh_token_and_retry_get(self) -> tuple[Any, int]:
        """Refresh token and retry GET request for subscriptions.

        Returns:
            tuple[Any, int]: The response data and status code.

        Raises:
            AuthenticationError: If refresh fails.
        """
        if not self._token_manager:
            raise AuthenticationError(
                SUBSCRIPTION_VERIFICATION_FAILED_UNAUTHORIZED,
                operation_type="verify",
            )

        refreshed = await self._token_manager.refresh_token()
        if not refreshed:
            await self._token_manager.handle_401_error()
            raise AuthenticationError(
                SUBSCRIPTION_VERIFICATION_FAILED_UNAUTHORIZED,
                operation_type="verify",
            )

        try:
            info = await self._token_manager.token_manager.get_info(
                self._token_manager.username
            )
            if not info or not info.access_token:
                await self._token_manager.handle_401_error()
                raise AuthenticationError(
                    SUBSCRIPTION_VERIFICATION_FAILED_UNAUTHORIZED,
                    operation_type="verify",
                )

            async with self._token_lock:
                self._token = info.access_token
            self._token_manager.reset_401_counter()

            # Retry the request
            data, status, _ = await self._api.request(
                "GET",
                EVENTSUB_SUBSCRIPTIONS,
                access_token=self._token,
                client_id=self._client_id,
            )
            return data, status
        except Exception as e:
            logging.warning(f"⚠️ Token refresh failed during verification: {str(e)}")
            await self._token_manager.handle_401_error()
            raise AuthenticationError(
                SUBSCRIPTION_VERIFICATION_FAILED_UNAUTHORIZED,
                operation_type="verify",
            ) from e

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
                data, status = await self._refresh_token_and_retry_get()
                if status == 401:
                    raise AuthenticationError(
                        SUBSCRIPTION_VERIFICATION_FAILED_UNAUTHORIZED,
                        operation_type="verify",
                    )

            if status != 200:
                raise SubscriptionError(
                    f"Subscription verification failed: HTTP {status}",
                    operation_type="verify",
                )

            return self._extract_active_channel_ids_from_data(data)

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
                return
            elif status == 401:
                await self._handle_401_and_retry_unsubscribe(sub_id)
                return
            elif status == 404:
                logging.warning(
                    f"⚠️ EventSub subscription {sub_id} not found (already unsubscribed)"
                )
                return
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
