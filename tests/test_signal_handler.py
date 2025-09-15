from __future__ import annotations

import signal
from unittest.mock import patch

from src.bot.signal_handler import SignalHandler


def test_setup_signal_handlers_sigint_handling():
    """Test SIGINT signal handling sets shutdown_initiated."""
    handler = SignalHandler()
    with patch('signal.signal') as mock_signal:
        handler.setup_signal_handlers()
        # Get the handler function that was registered
        sigint_handler = None
        sigterm_handler = None
        for call in mock_signal.call_args_list:
            if call[0][0] == signal.SIGINT:
                sigint_handler = call[0][1]
            elif call[0][0] == signal.SIGTERM:
                sigterm_handler = call[0][1]
        assert sigint_handler is not None
        assert sigterm_handler is not None
        # Simulate SIGINT
        sigint_handler(signal.SIGINT, None)
        assert handler.shutdown_initiated is True


def test_setup_signal_handlers_sigterm_handling():
    """Test SIGTERM signal handling sets shutdown_initiated."""
    handler = SignalHandler()
    with patch('signal.signal') as mock_signal:
        handler.setup_signal_handlers()
        sigint_handler = None
        sigterm_handler = None
        for call in mock_signal.call_args_list:
            if call[0][0] == signal.SIGINT:
                sigint_handler = call[0][1]
            elif call[0][0] == signal.SIGTERM:
                sigterm_handler = call[0][1]
        assert sigint_handler is not None
        assert sigterm_handler is not None
        # Simulate SIGTERM
        sigterm_handler(signal.SIGTERM, None)
        assert handler.shutdown_initiated is True


def test_setup_signal_handlers_multiple_signals():
    """Test multiple signals are handled idempotently."""
    handler = SignalHandler()
    with patch('signal.signal') as mock_signal:
        handler.setup_signal_handlers()
        sigint_handler = None
        for call in mock_signal.call_args_list:
            if call[0][0] == signal.SIGINT:
                sigint_handler = call[0][1]
                break
        assert sigint_handler is not None
        # First signal
        sigint_handler(signal.SIGINT, None)
        assert handler.shutdown_initiated is True
        initial_state = handler.shutdown_initiated
        # Second signal should not change
        sigint_handler(signal.SIGINT, None)
        assert handler.shutdown_initiated == initial_state


def test_stop_already_shutdown():
    """Test stop method when already shutdown."""
    handler = SignalHandler()
    handler.stop()
    assert handler.shutdown_initiated is True
    # Call stop again
    handler.stop()
    assert handler.shutdown_initiated is True
