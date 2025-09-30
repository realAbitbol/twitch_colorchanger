"""
Unit tests for SubscriptionManager session registry integration.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.chat.subscription_manager import SubscriptionManager
from src.errors.eventsub import AuthenticationError, SubscriptionError


class TestSubscriptionManagerSessionRegistry:
    """Test class for SubscriptionManager session registry integration."""

    def setup_method(self):
        """Setup method called before each test."""
        self.mock_api = Mock()
        self.mock_api.request = AsyncMock()
        self.session_id = "test_session_123"
        self.token = "test_token"
        self.client_id = "test_client_id"
        self.user_id = "test_user"

        # Create SubscriptionManager with mocked dependencies
        self.manager = SubscriptionManager(
            api=self.mock_api,
            session_id=self.session_id,
            token=self.token,
            client_id=self.client_id
        )

    def teardown_method(self):
        """Teardown method called after each test."""
        pass

    @pytest.mark.asyncio
    async def test_update_session_id_registers_new_session(self):
        """Test update_session_id registers new session ID with coordinator."""
        # Arrange
        new_session_id = "new_session_456"
        mock_coordinator = AsyncMock()
        self.manager._cleanup_coordinator = mock_coordinator

        # Act
        await self.manager.update_session_id(new_session_id)

        # Assert
        mock_coordinator.unregister_session_id.assert_called_once_with(self.session_id)
        mock_coordinator.register_session_id.assert_called_once_with(new_session_id)
        assert self.manager._session_id == new_session_id

    @pytest.mark.asyncio
    async def test_update_session_id_same_session_no_registry_change(self):
        """Test update_session_id with same session ID doesn't change registry."""
        # Arrange
        mock_coordinator = AsyncMock()
        self.manager._cleanup_coordinator = mock_coordinator

        # Act
        await self.manager.update_session_id(self.session_id)

        # Assert
        mock_coordinator.unregister_session_id.assert_not_called()
        mock_coordinator.register_session_id.assert_not_called()
        assert self.manager._session_id == self.session_id

    @pytest.mark.asyncio
    async def test_update_session_id_without_coordinator(self):
        """Test update_session_id works without cleanup coordinator."""
        # Arrange
        new_session_id = "new_session_456"
        self.manager._cleanup_coordinator = None

        # Act
        await self.manager.update_session_id(new_session_id)

        # Assert
        assert self.manager._session_id == new_session_id

    @pytest.mark.asyncio
    async def test_update_session_id_with_cleanup_old_subscriptions(self):
        """Test update_session_id cleans up old session subscriptions."""
        # Arrange
        new_session_id = "new_session_456"
        mock_coordinator = AsyncMock()
        self.manager._cleanup_coordinator = mock_coordinator

        # Mock the cleanup method
        with patch.object(self.manager, '_cleanup_old_session_subscriptions', new_callable=AsyncMock) as mock_cleanup:
            # Act
            await self.manager.update_session_id(new_session_id)

            # Assert
            mock_cleanup.assert_called_once_with(self.session_id)

    @pytest.mark.asyncio
    async def test_update_session_id_invalid_session_id_raises_error(self):
        """Test update_session_id raises ValueError for invalid session ID."""
        # Act & Assert
        with pytest.raises(ValueError, match="Valid session_id required"):
            await self.manager.update_session_id("")

        with pytest.raises(ValueError, match="Valid session_id required"):
            await self.manager.update_session_id(None)

    @pytest.mark.asyncio
    async def test_register_cleanup_task_registers_session(self):
        """Test register_cleanup_task registers session ID with coordinator."""
        # Arrange
        mock_coordinator = AsyncMock()
        mock_coordinator.register_cleanup_task.return_value = True
        self.manager._cleanup_coordinator = mock_coordinator

        # Act
        result = await self.manager.register_cleanup_task()

        # Assert
        assert result is True
        mock_coordinator.register_session_id.assert_called_once_with(self.session_id)
        mock_coordinator.register_cleanup_task.assert_called_once()
        assert self.manager._cleanup_registered is True

    @pytest.mark.asyncio
    async def test_register_cleanup_task_without_coordinator(self):
        """Test register_cleanup_task returns False without coordinator."""
        # Arrange
        self.manager._cleanup_coordinator = None

        # Act
        result = await self.manager.register_cleanup_task()

        # Assert
        assert result is False
        assert self.manager._cleanup_registered is False

    @pytest.mark.asyncio
    async def test_register_cleanup_task_already_registered(self):
        """Test register_cleanup_task returns False when already registered."""
        # Arrange
        mock_coordinator = AsyncMock()
        self.manager._cleanup_coordinator = mock_coordinator
        self.manager._cleanup_registered = True

        # Act
        result = await self.manager.register_cleanup_task()

        # Assert
        assert result is False
        mock_coordinator.register_session_id.assert_not_called()
        mock_coordinator.register_cleanup_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_cleanup_task_elected_as_active(self):
        """Test register_cleanup_task logs when elected as active."""
        # Arrange
        mock_coordinator = AsyncMock()
        mock_coordinator.register_cleanup_task.return_value = True
        self.manager._cleanup_coordinator = mock_coordinator

        # Act
        with patch('src.chat.subscription_manager.logging') as mock_logging:
            result = await self.manager.register_cleanup_task()

        # Assert
        assert result is True
        mock_logging.info.assert_called_with("🧹 Elected as active cleanup manager")

    @pytest.mark.asyncio
    async def test_register_cleanup_task_registered_as_passive(self):
        """Test register_cleanup_task logs when registered as passive."""
        # Arrange
        mock_coordinator = AsyncMock()
        mock_coordinator.register_cleanup_task.return_value = False
        self.manager._cleanup_coordinator = mock_coordinator

        # Act
        with patch('src.chat.subscription_manager.logging') as mock_logging:
            result = await self.manager.register_cleanup_task()

        # Assert
        assert result is False
        mock_logging.info.assert_called_with("🧹 Registered as passive cleanup manager")

    @pytest.mark.asyncio
    async def test_context_manager_aexit_unregisters_session(self):
        """Test async context manager exit unregisters session ID."""
        # Arrange
        mock_coordinator = AsyncMock()
        self.manager._cleanup_coordinator = mock_coordinator
        self.manager._cleanup_registered = True

        # Act
        await self.manager.__aexit__(None, None, None)

        # Assert
        mock_coordinator.unregister_cleanup_task.assert_called_once()
        mock_coordinator.unregister_session_id.assert_called_once_with(self.session_id)
        assert self.manager._cleanup_registered is False

    @pytest.mark.asyncio
    async def test_context_manager_aexit_without_coordinator(self):
        """Test async context manager exit works without coordinator."""
        # Arrange
        self.manager._cleanup_coordinator = None

        # Act
        await self.manager.__aexit__(None, None, None)

        # Assert
        # Should not raise any errors

    @pytest.mark.asyncio
    async def test_context_manager_aexit_not_registered(self):
        """Test async context manager exit handles non-registered cleanup."""
        # Arrange
        mock_coordinator = AsyncMock()
        self.manager._cleanup_coordinator = mock_coordinator
        self.manager._cleanup_registered = False

        # Act
        await self.manager.__aexit__(None, None, None)

        # Assert
        mock_coordinator.unregister_cleanup_task.assert_not_called()
        mock_coordinator.unregister_session_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_manager_aexit_unsubscribes_all(self):
        """Test async context manager exit unsubscribes all subscriptions."""
        # Arrange
        self.manager._active_subscriptions = {"sub1": "channel1", "sub2": "channel2"}
        self.manager._cleanup_coordinator = None

        # Mock unsubscribe_single
        with patch.object(self.manager, '_unsubscribe_single', new_callable=AsyncMock) as mock_unsubscribe:
            # Act
            await self.manager.__aexit__(None, None, None)

            # Assert
            assert mock_unsubscribe.call_count == 2
            mock_unsubscribe.assert_any_call("sub1")
            mock_unsubscribe.assert_any_call("sub2")
            assert len(self.manager._active_subscriptions) == 0

    @pytest.mark.asyncio
    async def test_update_session_id_with_logging(self):
        """Test update_session_id logs session ID update."""
        # Arrange
        new_session_id = "new_session_456"
        self.manager._cleanup_coordinator = None

        # Act
        with patch('src.chat.subscription_manager.logging') as mock_logging:
            await self.manager.update_session_id(new_session_id)

        # Assert
        mock_logging.info.assert_called_with(f"🔄 EventSub session ID updated to {new_session_id}")

    @pytest.mark.asyncio
    async def test_update_session_id_cleanup_logging(self):
        """Test update_session_id logs cleanup operations."""
        # Arrange
        new_session_id = "new_session_456"
        self.manager._cleanup_coordinator = None

        # Act
        with patch('src.chat.subscription_manager.logging') as mock_logging:
            await self.manager.update_session_id(new_session_id)

        # Assert
        mock_logging.info.assert_any_call(f"🧹 Starting synchronous cleanup of subscriptions from old session {self.session_id}")
        mock_logging.info.assert_any_call(f"✅ Completed cleanup of old session {self.session_id}")

    @pytest.mark.asyncio
    async def test_register_cleanup_task_with_coordinator_logging(self):
        """Test register_cleanup_task logs coordinator absence."""
        # Arrange
        self.manager._cleanup_coordinator = None

        # Act
        with patch('src.chat.subscription_manager.logging') as mock_logging:
            result = await self.manager.register_cleanup_task()

        # Assert
        assert result is False
        mock_logging.debug.assert_called_with("No cleanup coordinator available, skipping registration")

    @pytest.mark.asyncio
    async def test_register_cleanup_task_already_registered_logging(self):
        """Test register_cleanup_task logs when already registered."""
        # Arrange
        self.manager._cleanup_registered = True
        mock_coordinator = AsyncMock()
        self.manager._cleanup_coordinator = mock_coordinator

        # Act
        with patch('src.chat.subscription_manager.logging') as mock_logging:
            result = await self.manager.register_cleanup_task()

        # Assert
        assert result is False
        mock_logging.debug.assert_called_with("Cleanup task already registered")

    @pytest.mark.asyncio
    async def test_update_session_id_propagates_cleanup_exceptions(self):
        """Test update_session_id propagates cleanup exceptions."""
        # Arrange
        new_session_id = "new_session_456"
        self.manager._cleanup_coordinator = None

        # Act & Assert
        with patch.object(self.manager, '_cleanup_old_session_subscriptions', side_effect=Exception("Cleanup failed")):
            with pytest.raises(Exception, match="Cleanup failed"):
                await self.manager.update_session_id(new_session_id)

    @pytest.mark.asyncio
    async def test_context_manager_aexit_handles_exceptions(self):
        """Test context manager exit handles unsubscription exceptions."""
        # Arrange
        self.manager._active_subscriptions = {"sub1": "channel1"}
        self.manager._cleanup_coordinator = None

        # Mock unsubscribe_single to raise exception
        with patch.object(self.manager, '_unsubscribe_single', side_effect=Exception("Unsubscribe failed")):
            # Act & Assert
            with pytest.raises(Exception):  # Should raise SubscriptionError
                await self.manager.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_integration_session_lifecycle(self):
        """Test complete session lifecycle integration with coordinator."""
        # Arrange
        mock_coordinator = AsyncMock()
        mock_coordinator.register_cleanup_task.return_value = True
        self.manager._cleanup_coordinator = mock_coordinator

        # Act & Assert - Register cleanup task
        result = await self.manager.register_cleanup_task()
        assert result is True
        mock_coordinator.register_session_id.assert_called_once_with(self.session_id)

        # Act & Assert - Update session ID
        new_session_id = "new_session_456"
        await self.manager.update_session_id(new_session_id)
        mock_coordinator.unregister_session_id.assert_called_once_with(self.session_id)
        mock_coordinator.register_session_id.assert_called_with(new_session_id)

        # Act & Assert - Context manager exit
        await self.manager.__aexit__(None, None, None)
        mock_coordinator.unregister_cleanup_task.assert_called_once()
        mock_coordinator.unregister_session_id.assert_called_with(new_session_id)

    @pytest.mark.asyncio
    async def test_register_cleanup_task_handles_coordinator_exception(self):
        """Test register_cleanup_task handles coordinator exceptions."""
        # Arrange
        mock_coordinator = AsyncMock()
        mock_coordinator.register_session_id.side_effect = Exception("Coordinator error")
        self.manager._cleanup_coordinator = mock_coordinator

        # Act & Assert
        with pytest.raises(Exception, match="Coordinator error"):
            await self.manager.register_cleanup_task()

    @pytest.mark.asyncio
    async def test_update_session_id_handles_coordinator_register_exception(self):
        """Test update_session_id handles coordinator register exception."""
        # Arrange
        new_session_id = "new_session_456"
        mock_coordinator = AsyncMock()
        mock_coordinator.register_session_id.side_effect = Exception("Register failed")
        self.manager._cleanup_coordinator = mock_coordinator

        # Act & Assert
        with pytest.raises(Exception, match="Register failed"):
            await self.manager.update_session_id(new_session_id)

    @pytest.mark.asyncio
    async def test_update_session_id_handles_coordinator_unregister_exception(self):
        """Test update_session_id handles coordinator unregister exception."""
        # Arrange
        new_session_id = "new_session_456"
        mock_coordinator = AsyncMock()
        mock_coordinator.unregister_session_id.side_effect = Exception("Unregister failed")
        self.manager._cleanup_coordinator = mock_coordinator

        # Act & Assert
        with pytest.raises(Exception, match="Unregister failed"):
            await self.manager.update_session_id(new_session_id)

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_success(self):
        """Test subscribe_channel_chat creates subscription successfully."""
        # Arrange
        channel_id = "12345"
        user_id = "67890"
        mock_response = {"data": [{"id": "sub123"}]}
        self.mock_api.request.return_value = (mock_response, 202, None)

        # Act
        result = await self.manager.subscribe_channel_chat(channel_id, user_id)

        # Assert
        assert result is True
        assert "sub123" in self.manager._active_subscriptions
        assert self.manager._active_subscriptions["sub123"] == channel_id
        self.mock_api.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_rate_limited(self):
        """Test subscribe_channel_chat respects rate limiting."""
        # Arrange
        channel_id = "12345"
        user_id = "67890"
        mock_response = {"data": [{"id": "sub123"}]}
        self.mock_api.request.return_value = (mock_response, 202, None)

        # Fill rate limiter
        self.manager._rate_limiter = asyncio.Semaphore(0)

        # Act
        # This should wait but timeout in test
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                self.manager.subscribe_channel_chat(channel_id, user_id),
                timeout=0.1
            )

    @pytest.mark.asyncio
    async def test_subscribe_channel_chat_api_error(self):
        """Test subscribe_channel_chat handles API errors."""
        # Arrange
        channel_id = "12345"
        user_id = "67890"
        self.mock_api.request.return_value = ({"error": "Bad Request"}, 400, None)

        # Act & Assert
        with pytest.raises(SubscriptionError, match="Subscription failed: HTTP 400"):
            await self.manager.subscribe_channel_chat(channel_id, user_id)

    @pytest.mark.asyncio
    async def test_verify_subscriptions_success(self):
        """Test verify_subscriptions fetches and updates active subscriptions."""
        # Arrange
        mock_response = {
            "data": [
                {
                    "type": "channel.chat.message",
                    "transport": {"session_id": self.session_id},
                    "condition": {"broadcaster_user_id": "12345"}
                }
            ]
        }
        self.mock_api.request.return_value = (mock_response, 200, None)

        # Act
        result = await self.manager.verify_subscriptions()

        # Assert
        assert result == ["12345"]
        self.mock_api.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_subscriptions_with_existing_subscriptions(self):
        """Test verify_subscriptions updates existing subscription tracking."""
        # Arrange
        self.manager._active_subscriptions = {"old_sub": "99999"}
        mock_response = {
            "data": [
                {
                    "type": "channel.chat.message",
                    "transport": {"session_id": self.session_id},
                    "condition": {"broadcaster_user_id": "12345"}
                }
            ]
        }
        self.mock_api.request.return_value = (mock_response, 200, None)

        # Act
        result = await self.manager.verify_subscriptions()

        # Assert
        assert result == ["12345"]
        # Old subscription should be removed since it's not in the response
        assert "old_sub" not in self.manager._active_subscriptions

    @pytest.mark.asyncio
    async def test_cleanup_stale_subscriptions_success(self):
        """Test cleanup_stale_subscriptions removes stale subscriptions."""
        # Arrange
        mock_coordinator = AsyncMock()
        mock_coordinator.get_active_session_ids.return_value = [self.session_id]
        self.manager._cleanup_coordinator = mock_coordinator

        mock_response = {
            "data": [
                {
                    "id": "stale_sub",
                    "type": "channel.chat.message",
                    "transport": {"session_id": "old_session"}
                }
            ]
        }
        self.mock_api.request.return_value = (mock_response, 200, None)

        # Act
        await self.manager.cleanup_stale_subscriptions()

        # Assert
        # Should have called API for cleanup attempt
        assert self.mock_api.request.call_count == 1

    @pytest.mark.asyncio
    async def test_cleanup_stale_subscriptions_no_coordinator(self):
        """Test cleanup_stale_subscriptions works without coordinator."""
        # Arrange
        self.manager._cleanup_coordinator = None
        self.mock_api.request.return_value = ({"data": []}, 200, None)

        # Act
        await self.manager.cleanup_stale_subscriptions()

        # Assert
        # Should not crash
        self.mock_api.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_unsubscribe_all_success(self):
        """Test unsubscribe_all removes all active subscriptions."""
        # Arrange
        self.manager._active_subscriptions = {"sub1": "chan1", "sub2": "chan2"}
        self.mock_api.request.return_value = (None, 204, None)

        # Act
        await self.manager.unsubscribe_all()

        # Assert
        assert len(self.manager._active_subscriptions) == 0
        assert self.mock_api.request.call_count == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_all_with_errors(self):
        """Test unsubscribe_all continues despite individual errors."""
        # Arrange
        self.manager._active_subscriptions = {"sub1": "chan1", "sub2": "chan2"}
        self.mock_api.request.side_effect = [
            (None, 204, None),  # First unsubscribe succeeds
            ({"error": "Server error"}, 500, None)  # Second fails
        ]

        # Act & Assert
        with pytest.raises(SubscriptionError, match="Unsubscribe errors"):
            await self.manager.unsubscribe_all()

    @pytest.mark.asyncio
    async def test_get_active_channel_ids(self):
        """Test get_active_channel_ids returns unique channel IDs."""
        # Arrange
        self.manager._active_subscriptions = {
            "sub1": "chan1",
            "sub2": "chan1",  # Duplicate channel
            "sub3": "chan2"
        }

        # Act
        result = self.manager.get_active_channel_ids()

        # Assert
        assert set(result) == {"chan1", "chan2"}

    @pytest.mark.asyncio
    async def test_update_access_token(self):
        """Test update_access_token updates the token."""
        # Arrange
        new_token = "new_token_123"

        # Act
        self.manager.update_access_token(new_token)

        # Assert
        assert self.manager._token == new_token

    @pytest.mark.asyncio
    async def test_update_access_token_invalid(self):
        """Test update_access_token rejects invalid tokens."""
        # Act & Assert
        with pytest.raises(ValueError, match="Valid access_token required"):
            self.manager.update_access_token("")

        with pytest.raises(ValueError, match="Valid access_token required"):
            self.manager.update_access_token(None)

    @pytest.mark.asyncio
    async def test_build_subscription_body(self):
        """Test _build_subscription_body creates correct payload."""
        # Arrange
        channel_id = "12345"
        user_id = "67890"

        # Act
        result = self.manager._build_subscription_body(channel_id, user_id)

        # Assert
        expected = {
            "type": "channel.chat.message",
            "version": "1",
            "condition": {
                "broadcaster_user_id": channel_id,
                "user_id": user_id,
            },
            "transport": {"method": "websocket", "session_id": self.session_id},
        }
        assert result == expected

    @pytest.mark.asyncio
    async def test_extract_subscription_id_success(self):
        """Test _extract_subscription_id extracts ID from response."""
        # Arrange
        response = {"data": [{"id": "sub123"}]}

        # Act
        result = self.manager._extract_subscription_id(response)

        # Assert
        assert result == "sub123"

    @pytest.mark.asyncio
    async def test_extract_subscription_id_no_data(self):
        """Test _extract_subscription_id handles missing data."""
        # Arrange
        response = {}

        # Act
        result = self.manager._extract_subscription_id(response)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_active_channel_ids_from_data(self):
        """Test _extract_active_channel_ids_from_data filters by session."""
        # Arrange
        data = {
            "data": [
                {
                    "type": "channel.chat.message",
                    "transport": {"session_id": self.session_id},
                    "condition": {"broadcaster_user_id": "12345"}
                },
                {
                    "type": "channel.chat.message",
                    "transport": {"session_id": "other_session"},
                    "condition": {"broadcaster_user_id": "67890"}
                }
            ]
        }

        # Act
        result = self.manager._extract_active_channel_ids_from_data(data)

        # Assert
        assert result == ["12345"]

    @pytest.mark.asyncio
    async def test_extract_stale_subscription_ids(self):
        """Test _extract_stale_subscription_ids identifies stale subscriptions."""
        # Arrange
        data = {
            "data": [
                {
                    "id": "sub1",
                    "type": "channel.chat.message",
                    "transport": {"session_id": "active_session"}
                },
                {
                    "id": "sub2",
                    "type": "channel.chat.message",
                    "transport": {"session_id": "stale_session"}
                }
            ]
        }
        active_sessions = ["active_session"]

        # Act
        result = self.manager._extract_stale_subscription_ids(data, active_sessions)

        # Assert
        assert result == ["sub2"]

    @pytest.mark.asyncio
    async def test_extract_subscription_ids_for_session(self):
        """Test _extract_subscription_ids_for_session filters by session."""
        # Arrange
        data = {
            "data": [
                {
                    "id": "sub1",
                    "transport": {"session_id": "target_session"}
                },
                {
                    "id": "sub2",
                    "transport": {"session_id": "other_session"}
                }
            ]
        }

        # Act
        result = self.manager._extract_subscription_ids_for_session(data, "target_session")

        # Assert
        assert result == ["sub1"]

    @pytest.mark.asyncio
    async def test_cleanup_old_session_subscriptions_success(self):
        """Test _cleanup_old_session_subscriptions removes old subscriptions."""
        # Arrange
        old_session = "old_session_123"
        mock_response = {
            "data": [
                {
                    "id": "old_sub",
                    "transport": {"session_id": old_session}
                }
            ]
        }
        self.mock_api.request.side_effect = [
            (mock_response, 200, None),  # GET request
            (None, 204, None)  # DELETE request
        ]

        # Act
        await self.manager._cleanup_old_session_subscriptions(old_session)

        # Assert
        assert self.mock_api.request.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_active_channel_ids_success(self):
        """Test _fetch_active_channel_ids retrieves active channels."""
        # Arrange
        mock_response = {
            "data": [
                {
                    "type": "channel.chat.message",
                    "transport": {"session_id": self.session_id},
                    "condition": {"broadcaster_user_id": "12345"}
                }
            ]
        }
        self.mock_api.request.return_value = (mock_response, 200, None)

        # Act
        result = await self.manager._fetch_active_channel_ids()

        # Assert
        assert result == ["12345"]

    @pytest.mark.asyncio
    async def test_unsubscribe_single_success(self):
        """Test _unsubscribe_single removes subscription."""
        # Arrange
        sub_id = "sub123"
        self.mock_api.request.return_value = (None, 204, None)

        # Act
        await self.manager._unsubscribe_single(sub_id)

        # Assert
        self.mock_api.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_unsubscribe_single_not_found(self):
        """Test _unsubscribe_single handles 404 gracefully."""
        # Arrange
        sub_id = "sub123"
        self.mock_api.request.return_value = ({"error": "Not found"}, 404, None)

        # Act
        await self.manager._unsubscribe_single(sub_id)

        # Assert
        # Should not raise exception
        self.mock_api.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_subscription_request_202_success(self):
        """Test _handle_subscription_request processes 202 response."""
        # Arrange
        body = {"type": "channel.chat.message", "version": "1", "condition": {}, "transport": {}}
        channel_id = "12345"
        mock_response = {"data": [{"id": "sub123"}]}
        self.mock_api.request.return_value = (mock_response, 202, None)

        # Act
        result = await self.manager._handle_subscription_request(body, channel_id)

        # Assert
        assert result is True
        assert "sub123" in self.manager._active_subscriptions

    @pytest.mark.asyncio
    async def test_handle_subscription_request_401_retry(self):
        """Test _handle_subscription_request handles 401 with retry."""
        # Arrange
        body = {"type": "channel.chat.message", "version": "1", "condition": {}, "transport": {}}
        channel_id = "12345"

        # Mock token manager
        mock_token_manager = AsyncMock()
        mock_token_manager.refresh_token.return_value = True
        mock_token_manager.token_manager.get_info.return_value = Mock(access_token="new_token")
        mock_token_manager.reset_401_counter = AsyncMock()
        self.manager._token_manager = mock_token_manager

        self.mock_api.request.side_effect = [
            ({"error": "Unauthorized"}, 401, None),  # First call fails
            ({"data": [{"id": "sub123"}]}, 202, None)  # Retry succeeds
        ]

        # Act
        result = await self.manager._handle_subscription_request(body, channel_id)

        # Assert
        assert result is True
        assert self.mock_api.request.call_count == 2

    @pytest.mark.asyncio
    async def test_handle_subscription_request_403_error(self):
        """Test _handle_subscription_request handles 403 forbidden."""
        # Arrange
        body = {"type": "channel.chat.message", "version": "1", "condition": {}, "transport": {}}
        channel_id = "12345"
        self.mock_api.request.return_value = ({"error": "Forbidden"}, 403, None)

        # Act & Assert
        with pytest.raises(SubscriptionError, match="Subscription failed: forbidden"):
            await self.manager._handle_subscription_request(body, channel_id)

    @pytest.mark.asyncio
    async def test_refresh_token_and_retry_get_success(self):
        """Test _refresh_token_and_retry_get refreshes token and retries."""
        # Arrange
        mock_token_manager = AsyncMock()
        mock_token_manager.refresh_token.return_value = True
        mock_token_manager.token_manager.get_info.return_value = Mock(access_token="new_token")
        mock_token_manager.reset_401_counter = AsyncMock()
        mock_token_manager.handle_401_error = AsyncMock()
        self.manager._token_manager = mock_token_manager

        self.mock_api.request.side_effect = [
            ({"error": "Unauthorized"}, 401, None),  # First call fails
            ({"data": []}, 200, None)  # Retry succeeds
        ]

        # Act
        data, status = await self.manager._refresh_token_and_retry_get()

        # Assert
        assert status == 200
        assert self.manager._token == "new_token"