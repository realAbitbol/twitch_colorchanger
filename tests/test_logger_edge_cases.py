from __future__ import annotations

import logging

from src.logs.logger import BotLogger


def test_logger_long_event_truncation_debug(caplog, monkeypatch):  # type: ignore[no-untyped-def]
    # Force debug to exercise column width + truncation path
    monkeypatch.setenv("DEBUG", "1")
    log = BotLogger("edge_debug")
    caplog.set_level(logging.DEBUG)
    long_domain = "x" * 10
    long_action = "y" * 40  # ensure event_name length > width (32)
    log.log_event(long_domain, long_action, user="u")
    msgs = [r.message for r in caplog.records]
    # Expect truncation with ellipsis
    if not any("…" in m for m in msgs):
        raise AssertionError(f"Expected truncated ellipsis in debug log, got {msgs}")


def test_logger_privmsg_emoji_added_once(caplog):  # type: ignore[no-untyped-def]
    log = BotLogger("edge_privmsg")
    caplog.set_level(logging.INFO)
    log.log_event("chat", "privmsg", human="hello", user="bob", channel="room")
    log.log_event("chat", "privmsg", human="💬 already", user="bob", channel="room")
    msgs = [m.message for m in caplog.records]
    # First should have emoji added, second should keep single emoji (not duplicate)
    if sum(1 for m in msgs if "💬 #room hello" in m) != 1:
        raise AssertionError("Expected single injected emoji for first message")
    if sum(1 for m in msgs if "💬 #room already" in m) != 1:
        raise AssertionError("Expected second message preserved with existing emoji")


def test_logger_unknown_template_with_kwargs(caplog):  # type: ignore[no-untyped-def]
    log = BotLogger("edge_unknown")
    caplog.set_level(logging.INFO)
    log.log_event("mystery", "thing_happened", user="carol", extra="value")
    if not any("mystery: thing happened" in r.message for r in caplog.records):
        raise AssertionError("Derived fallback not present for unknown event")
