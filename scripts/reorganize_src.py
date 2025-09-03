#!/usr/bin/env python3
"""Automated source tree reorganization helper.

Detects legacy *flat* modules in ``src/`` that should live inside
newer packages (irc/, manager/, color/, utils/) and moves them while
optionally rewriting simple import statements.

Current heuristics (dynamic so script stays useful after future refactors):
 - irc_*.py          -> irc/<name>.py
 - manager_*.py      -> manager/<name>.py
 - color_change_service.py -> color/service.py
 - color_utils.py    -> color/utils.py
 - utils.py (when utils/ package exists) -> (deletion candidate)

The script supports a dry-run by default. Use --apply to perform changes.

Import rewriting (best effort):
For each moved file X (e.g. irc_connection.py) we rewrite occurrences of
  from .irc_connection import ...  -> from .irc.connection import ...
  import .irc_connection          -> import .irc.connection

If you prefer aggregated package exports (``from .irc import AsyncTwitchIRC``),
adjust manually or extend the script.

Idempotent: Running when no legacy files remain yields a no-op summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# ----------------------------- Configuration ----------------------------- #

# Regex relocation patterns: (pattern, target_subdir, reason)
RELOCATION_PATTERNS: Sequence[tuple[str, str, str]] = (
    (r"irc_(.+)\.py", "irc", "flattened irc module"),
    (r"manager_(.+)\.py", "manager", "flattened manager module"),
)

# Direct single-file mappings (legacy_name -> (new_relative_path, reason))
CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # rate limiting / backoff into rate/
    "backoff_strategy.py": (
        "rate/backoff_strategy.py",
        "categorize backoff_strategy.py",
    ),
    "rate_limit_headers.py": (
        "rate/rate_limit_headers.py",
        "categorize rate_limit_headers.py",
    ),
    "rate_limiter.py": ("rate/rate_limiter.py", "categorize rate_limiter.py"),
    "retry_policies.py": ("rate/retry_policies.py", "categorize retry_policies.py"),
    # bot support into bot/
    "bot_persistence.py": ("bot/bot_persistence.py", "categorize bot_persistence.py"),
    "bot_registrar.py": ("bot/bot_registrar.py", "categorize bot_registrar.py"),
    "bot_stats.py": ("bot/bot_stats.py", "categorize bot_stats.py"),
    # scheduling into scheduler/
    "adaptive_scheduler.py": (
        "scheduler/adaptive_scheduler.py",
        "categorize adaptive_scheduler.py",
    ),
    # manager helper
    "task_watchdog.py": ("manager/task_watchdog.py", "categorize task_watchdog.py"),
    # config support
    "config_repository.py": ("config/repository.py", "categorize config_repository.py"),
    "config_watcher.py": ("config/watcher.py", "categorize config_watcher.py"),
    "user_config_model.py": ("config/model.py", "categorize user_config_model.py"),
    "watcher_globals.py": ("config/globals.py", "categorize watcher_globals.py"),
    # errors
    "error_handling.py": ("errors/handling.py", "categorize error_handling.py"),
    "internal_errors.py": ("errors/internal.py", "categorize internal_errors.py"),
    # api
    "twitch_api.py": ("api/twitch.py", "categorize twitch_api.py"),
    # auth (device flow)
    "device_flow.py": ("auth_token/device_flow.py", "categorize device_flow.py"),
}

EVENT_TEMPLATES = "event_templates.json"
UTILS_DUPLICATE = "utils.py"
STALE_MANAGER_FILES = {
    "manager_health.py",
    "manager_reconnect.py",
    "manager_statistics.py",
}


@dataclass(slots=True)
class PlannedAction:
    """Represents a pending action the script will perform."""

    action: str  # 'move' | 'delete'
    source: Path  # existing file
    destination: Path | None  # target path for moves
    reason: str

    def describe(self) -> str:  # pragma: no cover - presentation only
        if self.action == "move" and self.destination:
            return (
                f"MOVE  {self.source.relative_to(ROOT)} -> "
                f"{self.destination.relative_to(ROOT)}  ({self.reason})"
            )
        return f"DELETE {self.source.relative_to(ROOT)}  ({self.reason})"


def _match_pattern(name: str, entry: Path) -> PlannedAction | None:
    for pat, target_dir, reason in RELOCATION_PATTERNS:
        if m := re.match(pat, name):
            return PlannedAction(
                "move", entry, SRC / target_dir / f"{m.group(1)}.py", reason
            )
    return None


def _direct_mappings(name: str, entry: Path) -> PlannedAction | None:
    direct_map = {
        "color_change_service.py": (
            SRC / "color" / "service.py",
            "color service relocation",
        ),
        "color_utils.py": (SRC / "color" / "utils.py", "color utils relocation"),
    }
    if name in direct_map:
        dest, reason = direct_map[name]
        return PlannedAction("move", entry, dest, reason)
    if name == UTILS_DUPLICATE and (SRC / "utils").is_dir():
        return PlannedAction(
            "delete", entry, None, "duplicate replaced by utils/ package"
        )
    return None


def _category_mapping(name: str, entry: Path) -> PlannedAction | None:
    if name in CATEGORY_MAP:
        rel_path, reason = CATEGORY_MAP[name]
        return PlannedAction("move", entry, SRC / rel_path, reason)
    return None


def _stale_manager_deletion(name: str, entry: Path) -> PlannedAction | None:
    if name in STALE_MANAGER_FILES and (SRC / "manager").is_dir():
        return PlannedAction("delete", entry, None, "stale after manager/ package")
    return None


def _event_templates_move(name: str, entry: Path) -> PlannedAction | None:
    if name == EVENT_TEMPLATES:
        return PlannedAction(
            "move",
            entry,
            SRC / "logging" / EVENT_TEMPLATES,
            "relocate logging event templates JSON",
        )
    return None


def detect_legacy_files() -> list[PlannedAction]:
    """Discover legacy flat modules and produce actions.

    Split into small focused helpers so cognitive complexity remains low.
    """
    if not SRC.exists():
        return []

    actions: list[PlannedAction] = []
    for entry in SRC.iterdir():
        name = entry.name
        if not entry.is_file() or name.startswith("__"):
            continue
        # Non-python special case first
        if name == EVENT_TEMPLATES:
            actions.append(
                PlannedAction(
                    "move",
                    entry,
                    SRC / "logging" / EVENT_TEMPLATES,
                    "relocate logging event templates JSON",
                )
            )
            continue
        if entry.suffix != ".py":
            continue
        # Try each classifier (order matters)
        classifier_chain = (
            _stale_manager_deletion,
            _category_mapping,
            lambda n, e: _match_pattern(n, e),
            _direct_mappings,
        )
        for classifier in classifier_chain:
            act = classifier(name, entry)  # type: ignore[arg-type]
            if act:
                actions.append(act)
                break
    return actions


def _apply_move(act: PlannedAction, dry_run: bool):
    dest = act.destination
    if dest is None:  # Bandit B101: avoid bare assert for runtime logic
        raise RuntimeError("PlannedAction missing destination for move")
    if dest.exists():
        if _maybe_merge_event_templates(act, dest, dry_run):
            return
        print(f"[skip] {dest} already exists (would move {act.source.name})")
        return
    if dry_run:
        print(f"[dry-run] move {act.source} -> {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.rename(act.source, dest)
    print(f"[moved] {act.source.name} -> {dest.relative_to(ROOT)}")


def _maybe_merge_event_templates(act: PlannedAction, dest: Path, dry_run: bool) -> bool:
    """Handle the special merge/update logic for event_templates.json.

    Returns True if a merge was performed (or skipped due to dry-run).
    """
    if act.source.name != EVENT_TEMPLATES or dest.suffix != ".json":
        return False
    if dry_run:
        print(
            f"[dry-run] merge {act.source} -> {dest} (overwrite with superset) and delete source"
        )
        return True
    try:
        with act.source.open("r", encoding="utf-8") as f_src:
            src_data = json.load(f_src)
        with dest.open("r", encoding="utf-8") as f_dest:
            dest_data = json.load(f_dest)
        merged = dest_data
        for domain, mapping in src_data.items():
            if isinstance(mapping, dict):
                existing = (
                    merged.get(domain, {})
                    if isinstance(merged.get(domain), dict)
                    else {}
                )
                new_domain = dict(existing)
                new_domain.update(mapping)
                merged[domain] = new_domain
            else:
                merged[domain] = mapping
        with dest.open("w", encoding="utf-8") as f_out:
            json.dump(merged, f_out, indent=2, sort_keys=True)
            f_out.write("\n")
        act.source.unlink(missing_ok=True)
        print(
            f"[merged+deleted] {act.source.name} -> {dest.relative_to(ROOT)} (full content migrated)"
        )
    except Exception as e:  # noqa: BLE001
        print(f"[error] failed merging {act.source} into {dest}: {e}")
    return True


def _apply_delete(act: PlannedAction, dry_run: bool):
    if dry_run:
        print(f"[dry-run] delete {act.source}")
        return
    try:
        act.source.unlink()
        print(f"[deleted] {act.source.name}")
    except FileNotFoundError:
        print(f"[missing] {act.source}")


def apply_actions(actions: Iterable[PlannedAction], *, dry_run: bool) -> None:
    for act in actions:
        if act.action == "move":
            _apply_move(act, dry_run)
        elif act.action == "delete":
            _apply_delete(act, dry_run)


def build_import_replacements(actions: Iterable[PlannedAction]) -> dict[str, str]:
    """Return mapping of old relative module tokens to new dotted paths.

    Only handles very simple (shallow) relative import forms to keep logic
    predictable and low-risk.
    """
    replacements: dict[str, str] = {}
    for act in actions:
        if act.action == "move" and act.destination:
            old = act.source.stem
            new_rel = act.destination.relative_to(SRC).with_suffix("")
            replacements[f".{old}"] = "." + str(new_rel).replace(os.sep, ".")
    return replacements


def rewrite_imports(replacements: dict[str, str], *, dry_run: bool) -> int:
    if not replacements:
        return 0
    changed = 0
    from_pattern_cache: list[tuple[re.Pattern[str], str]] = []
    import_pattern_cache: list[tuple[re.Pattern[str], str]] = []
    for old, new in replacements.items():
        from_pattern_cache.append(
            (re.compile(rf"from\s+\{old}\s+import"), f"from {new} import")
        )
        import_pattern_cache.append(
            (re.compile(rf"import\s+\{old}(\b)"), f"import {new}\\1")
        )

    for py in SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        original = text
        for pattern, repl in from_pattern_cache:
            text = pattern.sub(repl, text)
        for pattern, repl in import_pattern_cache:
            text = pattern.sub(repl, text)
        if text != original:
            changed += 1
            if dry_run:
                print(f"[dry-run] would rewrite imports in {py.relative_to(ROOT)}")
            else:
                py.write_text(text, encoding="utf-8")
                print(f"[updated] imports in {py.relative_to(ROOT)}")
    return changed


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reorganize legacy flat modules into packages"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Perform changes (default dry-run)"
    )
    parser.add_argument(
        "--rewrite-imports",
        action="store_true",
        help="Rewrite simple import statements referencing moved modules",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    dry_run = not args.apply
    actions = detect_legacy_files()
    if not actions:
        print("No legacy modules detected. Nothing to do.")
        return 0
    print("Planned actions:\n" + "\n".join(" - " + a.describe() for a in actions))
    apply_actions(actions, dry_run=dry_run)
    if args.rewrite_imports:
        repl = build_import_replacements(actions)
        count = rewrite_imports(repl, dry_run=dry_run)
        print(f"Import rewrite candidates applied: {count} file(s)")
    if dry_run:
        print("Dry-run complete. Re-run with --apply to make changes.")
    else:
        print("Reorganization complete.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
