"""Lightweight test to ensure every explicit logger.log_event(domain, action) pair has a template.
Run manually or integrate into your test runner.
"""

from __future__ import annotations

import ast
from pathlib import Path

from event_catalog import EVENT_TEMPLATES

SRC_DIR = Path(__file__).parent

ALLOWED_MISSING: set[tuple[str, str]] = set()  # Add allowed (domain, action) pairs here


def extract_events(path: Path):
    tree = ast.parse(path.read_text())
    events: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_obj = getattr(node, "func", None)
            if (
                isinstance(func_obj, ast.Attribute)
                and func_obj.attr == "log_event"
                and node.args
                and len(node.args) >= 2
            ):
                domain_node = node.args[0]
                action_node = node.args[1]
                if isinstance(domain_node, ast.Constant) and isinstance(
                    action_node, ast.Constant
                ):
                    events.add((str(domain_node.value), str(action_node.value)))
    return events


def test_event_templates_complete():  # pragma: no cover - optional quality gate
    all_events: set[tuple[str, str]] = set()
    for py in SRC_DIR.glob("*.py"):
        if py.name.startswith("test_"):
            continue
        all_events |= extract_events(py)

    missing = [
        ea
        for ea in sorted(all_events)
        if ea not in EVENT_TEMPLATES and ea not in ALLOWED_MISSING
    ]
    if missing:  # Avoid assert (Bandit B101)
        raise RuntimeError(f"Missing templates for: {missing}")


if __name__ == "__main__":  # Allow running directly
    try:
        test_event_templates_complete()
        print("OK: All event templates present")
    except AssertionError as e:
        print(str(e))
        raise
