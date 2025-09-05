from __future__ import annotations

import logging

from src.logs.logger import BotLogger


def test_logger_template_and_fallback(caplog) -> None:  # type: ignore[no-untyped-def]
    log = BotLogger("test_logger")
    caplog.set_level(logging.INFO)

    # Known template: use one existing template key (choose simple one)
    log.log_event("app", "start")
    # Unknown template should fallback and mark derived
    log.log_event("custom_domain", "custom_action", extra_field=123)

    msgs = [r.message for r in caplog.records]
    # Assert a known template substring appears
    if not any("Starting Twitch Color Changer Bot" in m for m in msgs):
        raise AssertionError("Expected start template message in logs")
    # Fallback should contain spaced domain/action words
    if not any("custom domain: custom action" in m for m in msgs):
        raise AssertionError("Expected derived fallback for unknown template")


def test_logger_privmsg_emoji_addition(caplog) -> None:  # type: ignore[no-untyped-def]
    log = BotLogger("test_logger2")
    caplog.set_level(logging.INFO)
    # Simulate PRIVMSG event with human text lacking emoji
    log.log_event("irc", "privmsg", human="hello world", user="tester", channel="room")
    msgs = [r.message for r in caplog.records]
    if not any("💬 #room hello world" in m for m in msgs):
        raise AssertionError("Expected chat emoji prefix added once")


def test_logger_debug_alignment(caplog, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DEBUG", "1")
    log = BotLogger("test_logger3")
    caplog.set_level(logging.DEBUG)
    log.log_event("app", "start")
    # In debug we expect padded event name column of at least 32 chars before prefix '['
    msgs = [r.message for r in caplog.records]
    first = msgs[0]
    # Event name "app_start" should be left padded to width (ends with spaces then '[')
    if "app_start" not in first:
        raise AssertionError("Expected event name present")
    # Ensure there are at least two spaces after event name somewhere before prefix
    if "app_start" in first:
        segment = first.split("[")[0]
        if len(segment) < 32:
            raise AssertionError("Expected debug alignment width >= 32 for event column")
