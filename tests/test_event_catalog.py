"""Tests for event catalog loading and basic integrity."""

from __future__ import annotations

from src.event_catalog import EVENT_TEMPLATES, reload_event_templates


def test_event_templates_loads():
    assert EVENT_TEMPLATES, "EVENT_TEMPLATES should not be empty"


def test_reload_idempotent():
    before = set(EVENT_TEMPLATES.keys())
    reload_event_templates()
    after = set(EVENT_TEMPLATES.keys())
    assert before == after
