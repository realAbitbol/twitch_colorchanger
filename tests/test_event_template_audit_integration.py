"""Integration test for event template audit ensuring no missing templates.

This imports the audit module functions directly rather than executing the script.
"""
from __future__ import annotations

from scripts.event_template_audit import diff


def test_event_template_audit_no_missing():  # noqa: D401
    result = diff()
    if result.missing:  # Use conditional raise to satisfy security linters
        raise AssertionError(f"Missing event templates: {sorted(result.missing)}")
    # Optional: warn (not fail) if unused grows too large could be future policy
    # For now we only enforce non-missing.


def test_event_template_audit_no_unused():  # noqa: D401
    result = diff()
    if result.unused:
        raise AssertionError(f"Unused event templates: {sorted(result.unused)}")
