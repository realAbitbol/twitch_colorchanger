"""Event template catalog loader (single authoritative JSON)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

EVENT_TEMPLATES: dict[tuple[str, str], str] = {}
_JSON_FILENAME = "event_templates.json"  # co-located inside logging/ directory


def _add_domain_actions(
    templates: dict[tuple[str, str], str], domain: str, actions: Mapping[str, Any]
) -> None:
    for action, template in actions.items():
        if isinstance(action, str) and isinstance(template, str):
            templates[(domain, action)] = template


def _load_event_templates() -> dict[tuple[str, str], str]:
    """Load event templates from the co-located JSON file.

    Root-level fallback & merge logic removed now that the full file
    has been migrated into the logging package.
    """
    path = Path(__file__).with_name(_JSON_FILENAME)
    templates: dict[tuple[str, str], str] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw: Any = json.load(f)
        if isinstance(raw, Mapping):
            for domain, actions in raw.items():
                if isinstance(domain, str) and isinstance(actions, Mapping):
                    _add_domain_actions(templates, domain, actions)
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
