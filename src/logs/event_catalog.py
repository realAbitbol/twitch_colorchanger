"""Event template catalog loader (single authoritative JSON)."""

from __future__ import annotations

import json
from pathlib import Path

EVENT_TEMPLATES: dict[tuple[str, str], str] = {}
_JSON_FILENAME = "event_templates.json"  # co-located inside logging/ directory


def _load_event_templates() -> dict[tuple[str, str], str]:
    """Load event templates from the co-located JSON file.

    Root-level fallback & merge logic removed now that the full file
    has been migrated into the logging package.
    """
    path = Path(__file__).with_name(_JSON_FILENAME)
    templates: dict[tuple[str, str], str] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
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
    global EVENT_TEMPLATES  # noqa: PLW0603
    EVENT_TEMPLATES = _load_event_templates()


reload_event_templates()

__all__ = ["EVENT_TEMPLATES", "reload_event_templates"]
