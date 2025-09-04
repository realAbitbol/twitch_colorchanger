"""Tests for event catalog loading and basic integrity.

Avoid stdlib shadowing: append project src path instead of inserting at front so
the stdlib module `token` (used by `tokenize`) isn't shadowed by our `token` package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SRC = Path(__file__).parents[1] / "src"
_CATALOG = _SRC / "logs" / "event_catalog.py"
spec = importlib.util.spec_from_file_location("logs.event_catalog", _CATALOG)
assert spec and spec.loader, "Could not create spec for event_catalog"
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)

EVENT_TEMPLATES: dict[tuple[str, str], str] = _mod.EVENT_TEMPLATES
reload_event_templates = _mod.reload_event_templates


def test_event_templates_loads() -> None:
    assert EVENT_TEMPLATES, "EVENT_TEMPLATES should not be empty"


def test_reload_idempotent() -> None:
    before = set(EVENT_TEMPLATES.keys())
    reload_event_templates()
    after = set(EVENT_TEMPLATES.keys())
    assert before == after
