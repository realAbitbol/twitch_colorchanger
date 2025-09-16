"""Tests for EventSub SubscriptionManager.

This module provides comprehensive tests for the SubscriptionManager class used in EventSub operations.
Tests cover subscription creation, verification, cleanup, rate limiting, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.twitch import TwitchAPI
from src.chat.subscription_manager import SubscriptionManager
from src.errors.eventsub import AuthenticationError, SubscriptionError


class TestSubscriptionManager:
    """Test suite for SubscriptionManager."""

    @pytest.fixture
    def mock_twitch_api(self):
        """Mock TwitchAPI."""
        api = MagicMock(spec=TwitchAPI)
        api.request = AsyncMock()
        return api

    @pytest.fixture
    def subscription_manager(self, mock_twitch_api):
        """Create SubscriptionManager instance with mocked dependencies."""
        return SubscriptionManager(
            api=mock_twitch_api,
            session_id="test_session_id",
            token="test_token",
            client_id="test_client_id"
        )

    def test_init_valid_params(self, mock_twitch_api):
        """Test SubscriptionManager initialization with valid parameters."""
        sm = SubscriptionManager(
            api=mock_twitch_api,
            session_id="session123",
            token="token123",
            client_id="client123"
        )

        assert sm._api == mock_twitch_api
        assert sm._session_id == "session123"
        assert sm._token == "token123"
        assert sm._client_id == "client123"
        assert sm._active_subscriptions == {}
        assert sm._rate_limiter is not None

    def test_init_invalid_api(self):
        """Test SubscriptionManager initialization with invalid API."""
        with pytest.raises(ValueError, match="TwitchAPI instance required"):
            SubscriptionManager(
                api=None,
                session_id="session123",
                token="token123",
                client_id="client123"
            )

    def test_init_invalid_session_id(self, mock_twitch_api):
        """Test SubscriptionManager initialization with invalid session_id."""
        with pytest.raises(ValueError, match="Valid session_id required"):
            SubscriptionManager(
                api=mock_twitch_api,
                session_id="",
                token="token123",
                client_id="client123"
            )

    def test_init_invalid_token(self, mock_twitch_api):
        """Test SubscriptionManager initialization with invalid token."""
        with pytest.raises(ValueError, match="Valid token required"):
            SubscriptionManager(
                api=mock_twitch_api,
                session_id="session123",
                token=None,
                client_id="client123"
            )

    def test_init_invalid_client_id(self, mock_twitch_api):
        """Test SubscriptionManager initialization with invalid client_id."""
        with pytest.raises(ValueError, match="Valid client_id required"):
            SubscriptionManager(
                api=mock_twitch_api,
                session_id="session123",
                token="token123",
                client_id=""
            )

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_success(self, subscription_manager, mock_twitch_api):
        """Test successful channel chat subscription."""
        # Mock successful subscription response
        mock_twitch_api.request.return_value = (
            {"data": [{"id": "sub123"}]}, 202, {}
        )

        result = await subscription_manager.subscribe_channel_chat("channel123", "user456")

        assert result is True
        assert "sub123" in subscription_manager._active_subscriptions
        assert subscription_manager._active_subscriptions["sub123"] == "channel123"
        mock_twitch_api.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_no_sub_id(self, subscription_manager, mock_twitch_api):
        """Test subscription success but no subscription ID returned."""
        mock_twitch_api.request.return_value = ({"data": [{}]}, 202, {})

        result = await subscription_manager.subscribe_channel_chat("channel123", "user456")

        assert result is False
        assert subscription_manager._active_subscriptions == {}

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_401_error(self, subscription_manager, mock_twitch_api):
        """Test subscription with 401 unauthorized error."""
        mock_twitch_api.request.return_value = ({"error": "Unauthorized"}, 401, {})

        with pytest.raises(AuthenticationError, match="unauthorized for channel channel123"):
            await subscription_manager.subscribe_channel_chat("channel123", "user456")

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_403_error(self, subscription_manager, mock_twitch_api):
        """Test subscription with 403 forbidden error."""
        mock_twitch_api.request.return_value = ({"error": "Forbidden"}, 403, {})

        with pytest.raises(SubscriptionError, match="forbidden for channel channel123"):
            await subscription_manager.subscribe_channel_chat("channel123", "user456")

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_other_error(self, subscription_manager, mock_twitch_api):
        """Test subscription with other HTTP error."""
        mock_twitch_api.request.return_value = ({"error": "Server Error"}, 500, {})

        with pytest.raises(SubscriptionError, match="HTTP 500 for channel channel123"):
            await subscription_manager.subscribe_channel_chat("channel123", "user456")

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_network_error(self, subscription_manager, mock_twitch_api):
        """Test subscription with network error."""
        mock_twitch_api.request.side_effect = Exception("Network error")

        with pytest.raises(SubscriptionError, match="Subscription error for channel channel123"):
            await subscription_manager.subscribe_channel_chat("channel123", "user456")

    @pytest.mark.asyncio
    async def test_verify_subscriptions_success(self, subscription_manager, mock_twitch_api):
        """Test successful subscription verification."""
        # Set up active subscriptions
        subscription_manager._active_subscriptions = {"sub1": "channel1", "sub2": "channel2"}

        # Mock verification response with active subscriptions
        mock_twitch_api.request.return_value = (
            {
                "data": [
                    {
                        "type": "channel.chat.message",
                        "transport": {"session_id": "test_session_id"},
                        "condition": {"broadcaster_user_id": "channel1"}
                    },
                    {
                        "type": "channel.chat.message",
                        "transport": {"session_id": "test_session_id"},
                        "condition": {"broadcaster_user_id": "channel2"}
                    }
                ]
            },
            200,
            {}
        )

        result = await subscription_manager.verify_subscriptions()

        assert result == ["channel1", "channel2"]
        assert subscription_manager._active_subscriptions == {"sub1": "channel1", "sub2": "channel2"}

    @pytest.mark.asyncio
    async def test_verify_subscriptions_partial_active(self, subscription_manager, mock_twitch_api):
        """Test verification with some subscriptions no longer active."""
        subscription_manager._active_subscriptions = {"sub1": "channel1", "sub2": "channel2"}

        # Only channel1 is active
        mock_twitch_api.request.return_value = (
            {
                "data": [
                    {
                        "type": "channel.chat.message",
                        "transport": {"session_id": "test_session_id"},
                        "condition": {"broadcaster_user_id": "channel1"}
                    }
                ]
            },
            200,
            {}
        )

        result = await subscription_manager.verify_subscriptions()

        assert result == ["channel1"]
        assert subscription_manager._active_subscriptions == {"sub1": "channel1"}

    @pytest.mark.asyncio
    async def test_verify_subscriptions_401_error(self, subscription_manager, mock_twitch_api):
        """Test verification with 401 error."""
        mock_twitch_api.request.return_value = ({"error": "Unauthorized"}, 401, {})

        with pytest.raises(AuthenticationError, match="unauthorized"):
            await subscription_manager.verify_subscriptions()

    @pytest.mark.asyncio
    async def test_verify_subscriptions_other_error(self, subscription_manager, mock_twitch_api):
        """Test verification with other error."""
        mock_twitch_api.request.return_value = ({"error": "Server Error"}, 500, {})

        with pytest.raises(SubscriptionError, match="HTTP 500"):
            await subscription_manager.verify_subscriptions()

    @pytest.mark.asyncio
    async def test_unsubscribe_all_success(self, subscription_manager, mock_twitch_api):
        """Test successful unsubscription of all subscriptions."""
        subscription_manager._active_subscriptions = {"sub1": "channel1", "sub2": "channel2"}

        # Mock successful unsubscribes
        mock_twitch_api.request.return_value = ({}, 204, {})

        await subscription_manager.unsubscribe_all()

        assert subscription_manager._active_subscriptions == {}
        assert mock_twitch_api.request.call_count == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_all_partial_failure(self, subscription_manager, mock_twitch_api):
        """Test unsubscription with some failures."""
        subscription_manager._active_subscriptions = {"sub1": "channel1", "sub2": "channel2"}

        # First call succeeds, second fails
        mock_twitch_api.request.side_effect = [
            ({}, 204, {}),
            Exception("Unsubscribe failed")
        ]

        with pytest.raises(SubscriptionError, match="Unsubscribe errors"):
            await subscription_manager.unsubscribe_all()

        # Should still clear subscriptions
        assert subscription_manager._active_subscriptions == {}

    @pytest.mark.asyncio
    async def test_unsubscribe_all_empty(self, subscription_manager, mock_twitch_api):
        """Test unsubscription when no subscriptions exist."""
        await subscription_manager.unsubscribe_all()

        assert subscription_manager._active_subscriptions == {}
        mock_twitch_api.request.assert_not_called()

    def test_get_active_channel_ids(self, subscription_manager):
        """Test getting active channel IDs."""
        subscription_manager._active_subscriptions = {
            "sub1": "channel1",
            "sub2": "channel1",  # Duplicate channel
            "sub3": "channel2"
        }

        result = subscription_manager.get_active_channel_ids()

        assert set(result) == {"channel1", "channel2"}

    def test_update_session_id(self, subscription_manager):
        """Test updating session ID."""
        subscription_manager.update_session_id("new_session_id")

        assert subscription_manager._session_id == "new_session_id"

    def test_update_session_id_invalid(self, subscription_manager):
        """Test updating session ID with invalid value."""
        with pytest.raises(ValueError, match="Valid session_id required"):
            subscription_manager.update_session_id("")

    @pytest.mark.asyncio
    async def test_rate_limiting(self, subscription_manager, mock_twitch_api):
        """Test that rate limiting works (basic check)."""
        # Set up successful responses
        mock_twitch_api.request.return_value = ({"data": [{"id": "sub123"}]}, 202, {})

        # Subscribe multiple times - should work but with rate limiting
        await subscription_manager.subscribe_channel_chat("channel1", "user1")
        await subscription_manager.subscribe_channel_chat("channel2", "user2")

        # Should have made 2 requests
        assert mock_twitch_api.request.call_count == 2

    def test_build_subscription_body(self, subscription_manager):
        """Test building subscription request body."""
        body = subscription_manager._build_subscription_body("broadcaster123", "user456")

        expected = {
            "type": "channel.chat.message",
            "version": "1",
            "condition": {
                "broadcaster_user_id": "broadcaster123",
                "user_id": "user456",
            },
            "transport": {
                "method": "websocket",
                "session_id": "test_session_id"
            },
        }

        assert body == expected

    def test_extract_subscription_id_success(self, subscription_manager):
        """Test extracting subscription ID from response."""
        data = {"data": [{"id": "sub123"}]}

        result = subscription_manager._extract_subscription_id(data)

        assert result == "sub123"

    def test_extract_subscription_id_no_data(self, subscription_manager):
        """Test extracting subscription ID with no data."""
        data = {}

        result = subscription_manager._extract_subscription_id(data)

        assert result is None

    def test_extract_subscription_id_empty_data(self, subscription_manager):
        """Test extracting subscription ID with empty data list."""
        data = {"data": []}

        result = subscription_manager._extract_subscription_id(data)

        assert result is None

    def test_extract_subscription_id_no_id(self, subscription_manager):
        """Test extracting subscription ID with no ID in data."""
        data = {"data": [{}]}

        result = subscription_manager._extract_subscription_id(data)

        assert result is None

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_429_error(self, subscription_manager, mock_twitch_api):
        """Test subscription with 429 rate limit error."""
        mock_twitch_api.request.return_value = ({"error": "Too Many Requests"}, 429, {})

        with pytest.raises(SubscriptionError, match="HTTP 429 for channel channel123"):
            await subscription_manager.subscribe_channel_chat("channel123", "user456")

    @pytest.mark.asyncio
    async def test_verify_subscriptions_invalid_data(self, subscription_manager, mock_twitch_api):
        """Test verification with invalid response data."""
        subscription_manager._active_subscriptions = {"sub1": "channel1"}

        mock_twitch_api.request.return_value = ("not a dict", 200, {})

        result = await subscription_manager.verify_subscriptions()

        assert result == []
        assert subscription_manager._active_subscriptions == {}

    @pytest.mark.asyncio
    async def test_verify_subscriptions_no_data(self, subscription_manager, mock_twitch_api):
        """Test verification with response missing data field."""
        subscription_manager._active_subscriptions = {"sub1": "channel1"}

        mock_twitch_api.request.return_value = ({"no_data": []}, 200, {})

        result = await subscription_manager.verify_subscriptions()

        assert result == []
        assert subscription_manager._active_subscriptions == {}

    @pytest.mark.asyncio
    async def test_verify_subscriptions_empty_data(self, subscription_manager, mock_twitch_api):
        """Test verification with empty data list."""
        subscription_manager._active_subscriptions = {"sub1": "channel1"}

        mock_twitch_api.request.return_value = ({"data": []}, 200, {})

        result = await subscription_manager.verify_subscriptions()

        assert result == []
        assert subscription_manager._active_subscriptions == {}

    @pytest.mark.asyncio
    async def test_verify_subscriptions_wrong_type(self, subscription_manager, mock_twitch_api):
        """Test verification with wrong subscription type."""
        subscription_manager._active_subscriptions = {"sub1": "channel1"}

        mock_twitch_api.request.return_value = (
            {
                "data": [
                    {
                        "type": "wrong_type",
                        "transport": {"session_id": "test_session_id"},
                        "condition": {"broadcaster_user_id": "channel1"}
                    }
                ]
            },
            200,
            {}
        )

        result = await subscription_manager.verify_subscriptions()

        assert result == []
        assert subscription_manager._active_subscriptions == {}

    @pytest.mark.asyncio
    async def test_verify_subscriptions_wrong_session(self, subscription_manager, mock_twitch_api):
        """Test verification with wrong session ID."""
        subscription_manager._active_subscriptions = {"sub1": "channel1"}

        mock_twitch_api.request.return_value = (
            {
                "data": [
                    {
                        "type": "channel.chat.message",
                        "transport": {"session_id": "wrong_session"},
                        "condition": {"broadcaster_user_id": "channel1"}
                    }
                ]
            },
            200,
            {}
        )

        result = await subscription_manager.verify_subscriptions()

        assert result == []
        assert subscription_manager._active_subscriptions == {}
