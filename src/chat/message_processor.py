"""MessageProcessor for parsing and dispatching EventSub WebSocket messages.

This module provides the MessageProcessor class that handles incoming EventSub
WebSocket messages, parses them, validates JSON, and dispatches to appropriate
handlers based on message type and content.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from ..errors.eventsub import MessageProcessingError
from .protocols import MessageProcessorProtocol

# Type alias for message handlers
MessageHandler = Callable[[str, str, str], Any]

# EventSub message types
EVENTSUB_NOTIFICATION = "notification"
EVENTSUB_CHAT_MESSAGE = "channel.chat.message"


class ChatEvent:
    """Represents a parsed chat message event from EventSub.

    Attributes:
        chatter_user_name (str): The username of the user who sent the message.
        broadcaster_user_name (str): The username of the channel broadcaster.
        message_text (str): The text content of the message.
    """

    def __init__(
        self,
        chatter_user_name: str,
        broadcaster_user_name: str,
        message_text: str,
    ) -> None:
        """Initialize a ChatEvent.

        Args:
            chatter_user_name: Username of the message sender.
            broadcaster_user_name: Username of the channel broadcaster.
            message_text: The message text content.
        """
        self.chatter_user_name = chatter_user_name
        self.broadcaster_user_name = broadcaster_user_name
        self.message_text = message_text


class MessageProcessor(MessageProcessorProtocol):
    """Processes EventSub WebSocket messages and dispatches to handlers.

    This class is responsible for parsing raw JSON messages from the EventSub
    WebSocket, validating their structure, extracting chat events, and
    dispatching them to the appropriate message handlers.

    Attributes:
        message_handler (MessageHandler): Handler for regular chat messages.
        color_handler (MessageHandler): Handler for color/command messages.
    """

    def __init__(
        self,
        message_handler: MessageHandler,
        color_handler: MessageHandler,
    ) -> None:
        """Initialize the MessageProcessor.

        Args:
            message_handler: Callable to handle regular chat messages.
                Should accept (username, channel, message) parameters.
            color_handler: Callable to handle color/command messages.
                Should accept (username, channel, message) parameters.
        """
        self.message_handler = message_handler
        self.color_handler = color_handler

    async def process_message(self, raw_message: str) -> None:
        """Process a raw WebSocket message from EventSub.

        Parses the JSON message, validates its structure, extracts chat events,
        and dispatches to the appropriate handlers. Handles JSON parsing errors
        and message validation failures gracefully.

        Args:
            raw_message: The raw JSON string received from the WebSocket.

        Raises:
            MessageProcessingError: If the message cannot be processed due to
                JSON parsing errors, invalid structure, or missing required fields.
        """
        try:
            # Parse JSON
            data = self._parse_json(raw_message)

            # Check if it's a notification
            if not self._is_notification(data):
                return

            # Parse the chat event
            event = self._parse_event(data)
            if event is None:
                return

            # Dispatch to handlers
            await self._dispatch_event(event)

        except MessageProcessingError:
            # Re-raise MessageProcessingError from _parse_json or other methods
            raise
        except KeyError as e:
            raise MessageProcessingError(
                f"Missing required field in message: {str(e)}",
                operation_type="parse_event",
            ) from e
        except Exception as e:
            raise MessageProcessingError(
                f"Unexpected error processing message: {str(e)}",
                operation_type="process_message",
            ) from e

    def _parse_json(self, raw_message: str) -> dict[str, Any]:
        """Parse a JSON string into a dictionary.

        Args:
            raw_message: The JSON string to parse.

        Returns:
            The parsed dictionary.

        Raises:
            MessageProcessingError: If JSON parsing fails or result is not a dict.
        """
        try:
            data = json.loads(raw_message)
            if isinstance(data, dict):
                return data
            raise MessageProcessingError(
                "EventSub message is not a JSON object",
                operation_type="parse_json",
            )
        except json.JSONDecodeError as e:
            raise MessageProcessingError(
                f"EventSub message contains invalid JSON: {str(e)}",
                operation_type="parse_json",
            ) from e

    def _is_notification(self, data: dict[str, Any]) -> bool:
        """Check if the message is a notification.

        Args:
            data: The parsed message data.

        Returns:
            True if this is a notification message, False otherwise.
        """
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            return False
        message_type = metadata.get("message_type")
        return message_type == EVENTSUB_NOTIFICATION

    def _parse_event(self, data: dict[str, Any]) -> ChatEvent | None:
        """Parse a chat event from the notification data.

        Args:
            data: The parsed notification message data.

        Returns:
            A ChatEvent instance if parsing succeeds, None otherwise.
        """
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return None

        subscription = payload.get("subscription")
        if not isinstance(subscription, dict):
            return None

        # Check if this is a chat message event
        event_type = subscription.get("type")
        if event_type != EVENTSUB_CHAT_MESSAGE:
            return None

        event = payload.get("event")
        if not isinstance(event, dict):
            return None

        # Extract required fields
        chatter_user_name = event.get("chatter_user_name")
        broadcaster_user_name = event.get("broadcaster_user_name")
        message_obj = event.get("message")

        if not isinstance(message_obj, dict):
            return None

        message_text = message_obj.get("text")

        # Validate all required fields are present and strings
        if not (
            isinstance(chatter_user_name, str)
            and isinstance(broadcaster_user_name, str)
            and isinstance(message_text, str)
        ):
            logging.warning("EventSub chat event missing required string fields")
            return None

        return ChatEvent(
            chatter_user_name=chatter_user_name,
            broadcaster_user_name=broadcaster_user_name,
            message_text=message_text,
        )

    async def _dispatch_event(self, event: ChatEvent) -> None:
        """Dispatch the chat event to the appropriate handlers.

        Args:
            event: The parsed chat event to dispatch.
        """
        username = event.chatter_user_name
        channel = event.broadcaster_user_name.lower()
        message = event.message_text

        # Always call the message handler
        try:
            result = self.message_handler(username, channel, message)
            if hasattr(result, "__await__"):
                await result
        except Exception as e:
            logging.warning(f"Error in message handler: {str(e)}")

        # Call color handler for messages starting with "!"
        if message.startswith("!"):
            try:
                result = self.color_handler(username, channel, message)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logging.warning(f"Error in color handler: {str(e)}")

    async def __aenter__(self) -> MessageProcessor:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit with cleanup."""
        # No specific cleanup needed for MessageProcessor
        pass
