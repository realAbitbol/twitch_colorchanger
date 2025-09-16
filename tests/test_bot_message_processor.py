"""Unit tests for MessageProcessor class."""

import json
from unittest.mock import MagicMock

import pytest

from src.chat.message_processor import ChatEvent, MessageProcessor
from src.errors.eventsub import MessageProcessingError


class TestChatEvent:
    """Test cases for ChatEvent class."""

    def test_chat_event_creation(self):
        """Test ChatEvent initialization."""
        event = ChatEvent(
            chatter_user_name="testuser",
            broadcaster_user_name="testchannel",
            message_text="Hello world",
        )
        assert event.chatter_user_name == "testuser"
        assert event.broadcaster_user_name == "testchannel"
        assert event.message_text == "Hello world"


class TestMessageProcessor:
    """Test cases for MessageProcessor class."""

    @pytest.fixture
    def mock_handlers(self):
        """Create mock message handlers."""
        message_handler = MagicMock()
        color_handler = MagicMock()
        return message_handler, color_handler

    @pytest.fixture
    def processor(self, mock_handlers):
        """Create MessageProcessor instance with mock handlers."""
        message_handler, color_handler = mock_handlers
        return MessageProcessor(message_handler, color_handler)

    def test_init(self, mock_handlers):
        """Test MessageProcessor initialization."""
        message_handler, color_handler = mock_handlers
        processor = MessageProcessor(message_handler, color_handler)
        assert processor.message_handler == message_handler
        assert processor.color_handler == color_handler

    @pytest.mark.asyncio
    async def test_process_message_valid_chat_event(self, processor, mock_handlers):
        """Test processing a valid chat message event."""
        message_handler, color_handler = mock_handlers

        # Create a valid EventSub chat message
        message_data = {
            "metadata": {"message_type": "notification"},
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "testuser",
                    "broadcaster_user_name": "testchannel",
                    "message": {"text": "Hello world"}
                }
            }
        }
        raw_message = json.dumps(message_data)

        await processor.process_message(raw_message)

        # Verify message handler was called
        message_handler.assert_called_once_with("testuser", "testchannel", "Hello world")
        # Color handler should not be called for non-"!" messages
        color_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_message_color_command(self, processor, mock_handlers):
        """Test processing a color command message."""
        message_handler, color_handler = mock_handlers

        message_data = {
            "metadata": {"message_type": "notification"},
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "testuser",
                    "broadcaster_user_name": "testchannel",
                    "message": {"text": "!color red"}
                }
            }
        }
        raw_message = json.dumps(message_data)

        await processor.process_message(raw_message)

        # Both handlers should be called
        message_handler.assert_called_once_with("testuser", "testchannel", "!color red")
        color_handler.assert_called_once_with("testuser", "testchannel", "!color red")

    @pytest.mark.asyncio
    async def test_process_message_async_handlers(self, processor):
        """Test processing with async handlers."""
        async def async_message_handler(username, channel, message):
            pass

        async def async_color_handler(username, channel, message):
            pass

        processor.message_handler = async_message_handler
        processor.color_handler = async_color_handler

        message_data = {
            "metadata": {"message_type": "notification"},
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "testuser",
                    "broadcaster_user_name": "testchannel",
                    "message": {"text": "!command"}
                }
            }
        }
        raw_message = json.dumps(message_data)

        # Should not raise any exceptions
        await processor.process_message(raw_message)

    @pytest.mark.asyncio
    async def test_process_message_invalid_json(self, processor):
        """Test processing invalid JSON."""
        with pytest.raises(MessageProcessingError) as exc_info:
            await processor.process_message("invalid json")

        assert "EventSub message contains invalid JSON" in str(exc_info.value)
        assert exc_info.value.operation_type == "parse_json"

    @pytest.mark.asyncio
    async def test_process_message_non_notification(self, processor, mock_handlers):
        """Test processing non-notification message."""
        message_handler, color_handler = mock_handlers

        message_data = {
            "metadata": {"message_type": "session_welcome"},
            "payload": {"session": {"id": "123"}}
        }
        raw_message = json.dumps(message_data)

        await processor.process_message(raw_message)

        # Handlers should not be called
        message_handler.assert_not_called()
        color_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_message_wrong_subscription_type(self, processor, mock_handlers):
        """Test processing message with wrong subscription type."""
        message_handler, color_handler = mock_handlers

        message_data = {
            "metadata": {"message_type": "notification"},
            "payload": {
                "subscription": {"type": "channel.follow"},
                "event": {"user_name": "testuser"}
            }
        }
        raw_message = json.dumps(message_data)

        await processor.process_message(raw_message)

        # Handlers should not be called
        message_handler.assert_not_called()
        color_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_message_missing_fields(self, processor):
        """Test processing message with missing required fields."""
        # Missing message_type
        message_data = {
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "testuser",
                    "broadcaster_user_name": "testchannel",
                    "message": {"text": "Hello"}
                }
            }
        }
        raw_message = json.dumps(message_data)

        await processor.process_message(raw_message)
        # Should not raise, just ignore

    @pytest.mark.asyncio
    async def test_process_message_invalid_structure(self, processor):
        """Test processing message with invalid structure."""
        # Non-dict JSON should raise
        with pytest.raises(MessageProcessingError):
            await processor.process_message('"string"')

        # Non-dict payload should not raise (just ignore)
        message_data = {
            "metadata": {"message_type": "notification"},
            "payload": "string"
        }
        raw_message = json.dumps(message_data)
        await processor.process_message(raw_message)

    @pytest.mark.asyncio
    async def test_process_message_handler_exception(self, processor, mock_handlers):
        """Test handling exceptions in message handlers."""
        message_handler, color_handler = mock_handlers
        message_handler.side_effect = Exception("Handler error")

        message_data = {
            "metadata": {"message_type": "notification"},
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "testuser",
                    "broadcaster_user_name": "testchannel",
                    "message": {"text": "Hello"}
                }
            }
        }
        raw_message = json.dumps(message_data)

        # Should not raise, just log warning
        await processor.process_message(raw_message)

        message_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_color_handler_exception(self, processor, mock_handlers):
        """Test handling exceptions in color handler."""
        message_handler, color_handler = mock_handlers
        color_handler.side_effect = Exception("Color handler error")

        message_data = {
            "metadata": {"message_type": "notification"},
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "testuser",
                    "broadcaster_user_name": "testchannel",
                    "message": {"text": "!command"}
                }
            }
        }
        raw_message = json.dumps(message_data)

        # Should not raise, just log warning
        await processor.process_message(raw_message)

        message_handler.assert_called_once()
        color_handler.assert_called_once()

    def test_parse_json_valid(self, processor):
        """Test _parse_json with valid JSON."""
        data = {"key": "value"}
        result = processor._parse_json(json.dumps(data))
        assert result == data

    def test_parse_json_invalid(self, processor):
        """Test _parse_json with invalid JSON."""
        with pytest.raises(MessageProcessingError):
            processor._parse_json("invalid")

    def test_parse_json_non_dict(self, processor):
        """Test _parse_json with non-dict JSON."""
        with pytest.raises(MessageProcessingError):
            processor._parse_json('"string"')

    def test_is_notification_true(self, processor):
        """Test _is_notification with valid notification."""
        data = {"metadata": {"message_type": "notification"}}
        assert processor._is_notification(data) is True

    def test_is_notification_false(self, processor):
        """Test _is_notification with invalid data."""
        # Wrong message type
        data = {"metadata": {"message_type": "welcome"}}
        assert processor._is_notification(data) is False

        # Missing metadata
        data = {"payload": {}}
        assert processor._is_notification(data) is False

        # Non-dict metadata
        data = {"metadata": "string"}
        assert processor._is_notification(data) is False

    def test_parse_event_valid(self, processor):
        """Test _parse_event with valid event data."""
        data = {
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "testuser",
                    "broadcaster_user_name": "testchannel",
                    "message": {"text": "Hello"}
                }
            }
        }
        event = processor._parse_event(data)
        assert isinstance(event, ChatEvent)
        assert event.chatter_user_name == "testuser"
        assert event.broadcaster_user_name == "testchannel"
        assert event.message_text == "Hello"

    def test_parse_event_invalid_subscription_type(self, processor):
        """Test _parse_event with wrong subscription type."""
        data = {
            "payload": {
                "subscription": {"type": "channel.follow"},
                "event": {"user_name": "testuser"}
            }
        }
        event = processor._parse_event(data)
        assert event is None

    def test_parse_event_missing_fields(self, processor):
        """Test _parse_event with missing fields."""
        # Missing payload
        data = {"metadata": {"message_type": "notification"}}
        event = processor._parse_event(data)
        assert event is None

        # Missing subscription
        data = {"payload": {"event": {}}}
        event = processor._parse_event(data)
        assert event is None

        # Missing event
        data = {"payload": {"subscription": {"type": "channel.chat.message"}}}
        event = processor._parse_event(data)
        assert event is None

        # Missing message
        data = {
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": "testuser",
                    "broadcaster_user_name": "testchannel"
                }
            }
        }
        event = processor._parse_event(data)
        assert event is None

    def test_parse_event_non_string_fields(self, processor):
        """Test _parse_event with non-string required fields."""
        data = {
            "payload": {
                "subscription": {"type": "channel.chat.message"},
                "event": {
                    "chatter_user_name": 123,  # Should be string
                    "broadcaster_user_name": "testchannel",
                    "message": {"text": "Hello"}
                }
            }
        }
        event = processor._parse_event(data)
        assert event is None
