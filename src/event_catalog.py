"""Catalog loader for structured log event templates.

Event templates have been moved to an external JSON file for easier
maintenance, diff readability, and potential future localization.

Public API preserved: import EVENT_TEMPLATES from this module.
"""

from __future__ import annotations

import json
from pathlib import Path

EVENT_TEMPLATES: dict[tuple[str, str], str] = {}

_JSON_FILENAME = "event_templates.json"


def _load_event_templates() -> dict[tuple[str, str], str]:
    path = Path(__file__).with_name(_JSON_FILENAME)
    templates: dict[tuple[str, str], str] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # data format: { domain: { action: template } }
        for domain, actions in data.items():
            if isinstance(actions, dict):
                for action, template in actions.items():
                    if isinstance(template, str):
                        templates[(domain, action)] = template
    except FileNotFoundError:
        templates[("app", "load_error")] = "Event templates file missing"
    except Exception as e:  # noqa: BLE001
        templates[("app", "load_error")] = f"Failed to load event templates: {e}"[:200]
    return templates


def reload_event_templates() -> None:
    """Reload templates from disk (hot-reload support)."""
    global EVENT_TEMPLATES  # noqa: PLW0603
    EVENT_TEMPLATES = _load_event_templates()


# Initial load at import time
reload_event_templates()

__all__ = ["EVENT_TEMPLATES", "reload_event_templates"]
