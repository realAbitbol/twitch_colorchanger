from __future__ import annotations

from src.logs import logger as global_logger
from src.logs.event_catalog import EVENT_TEMPLATES


def _extract_fields(template: str) -> set[str]:
    fields: set[str] = set()
    buf = ""
    in_brace = False
    for ch in template:
        if ch == "{" and not in_brace:
            in_brace = True
            buf = ""
        elif ch == "}" and in_brace:
            in_brace = False
            if buf and not buf.startswith("\\") and not buf.endswith("!r"):
                core = buf.split(":", 1)[0].split(".", 1)[0]
                if core:
                    fields.add(core)
        elif in_brace:
            buf += ch
    return fields


def _dummy_values(fields: set[str]) -> dict[str, object]:
    dummy: dict[str, object] = dict.fromkeys(fields, 1)
    for k in dummy:
        if "error" in k or "message" in k or k.endswith("_human"):
            dummy[k] = "x"
        elif k in {"user", "username", "channel", "channels", "color"}:
            dummy[k] = "abc"
        elif k.endswith("seconds") or k in {"remaining", "count", "attempt", "attempts"} or k.endswith("s") and isinstance(dummy[k], int):
            dummy[k] = 1
    return dummy


def test_event_catalog_placeholders_renderable():  # type: ignore[no-untyped-def]
    failures: list[tuple[str, str, str]] = []
    for (domain, action), template in EVENT_TEMPLATES.items():
        fields = _extract_fields(template)
        dummy = _dummy_values(fields)
        try:
            template.format(**dummy)
        except Exception as e:  # noqa: BLE001
            failures.append((domain, action, str(e)))
    if failures:
        raise AssertionError(f"Unrenderable templates: {failures[:5]} (total {len(failures)})")


def test_logger_unknown_event_marks_derived(caplog):  # type: ignore[no-untyped-def]
    caplog.set_level(20)
    global_logger.log_event("nonexistent_domain", "some_event", foo=1)
    msgs = [r.message for r in caplog.records]
    if not any("nonexistent domain: some event" in m for m in msgs):
        raise AssertionError("Expected derived fallback message for unknown template")


def test_event_template_keys_lowercase():  # type: ignore[no-untyped-def]
    # Enforce convention that domain/action keys are lowercase in storage
    for (domain, action) in EVENT_TEMPLATES:
        if domain.lower() != domain or action.lower() != action:
            raise AssertionError(f"Template key not lowercase: {(domain, action)}")
