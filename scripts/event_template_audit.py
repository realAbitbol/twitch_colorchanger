"""Audit tool for event templates.

Moved to scripts/ directory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.event_catalog import EVENT_TEMPLATES, reload_event_templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent / "src"
SRC_ROOT = PROJECT_ROOT
TEMPLATES_JSON = PROJECT_ROOT / "event_templates.json"

_RE_POSITIONAL = re.compile(
    r"logger\.log_event\(\s*(['\"])(?P<domain>[^'\"]+)\1\s*,\s*(['\"])(?P<action>[^'\"]+)\3"
)
_RE_KEYWORD = re.compile(
    r"logger\.log_event\([^)]*?domain\s*=\s*(['\"])(?P<domain>[^'\"]+)\1[^)]*?action\s*=\s*(['\"])(?P<action>[^'\"]+)\3",
    re.DOTALL,
)


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if path.name.startswith("."):
            continue
        yield path


def extract_references(paths: Iterable[Path]) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for m in _RE_POSITIONAL.finditer(text):
            refs.add((m.group("domain"), m.group("action")))
        for m in _RE_KEYWORD.finditer(text):
            refs.add((m.group("domain"), m.group("action")))
    return refs


def load_templates_from_json() -> set[tuple[str, str]]:
    try:
        with TEMPLATES_JSON.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return set()
    result: set[tuple[str, str]] = set()
    if isinstance(raw, dict):
        for domain, actions in raw.items():
            if isinstance(actions, dict):
                for action in actions:
                    result.add((domain, action))
    return result


def compute_diff() -> tuple[
    set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]
]:
    reload_event_templates()
    code_refs = extract_references(iter_python_files(SRC_ROOT))
    json_templates = load_templates_from_json()
    loaded_templates = set(EVENT_TEMPLATES.keys())
    missing = code_refs - json_templates
    unused = json_templates - code_refs
    discrepancy = loaded_templates ^ json_templates
    return missing, unused, discrepancy


def prune_unused(unused: set[tuple[str, str]]) -> bool:
    if not unused:
        return False
    try:
        with TEMPLATES_JSON.open("r", encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for domain, action in unused:
            domain_map = data.get(domain)
            if isinstance(domain_map, dict) and action in domain_map:
                del domain_map[action]
                changed = True
        empty = [d for d, mapping in data.items() if not mapping]
        for d in empty:
            del data[d]
            changed = True
        if changed:
            with TEMPLATES_JSON.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
        return changed
    except Exception as e:  # noqa: BLE001
        print(f"Failed to prune unused templates: {e}", file=sys.stderr)
        return False


@dataclass(slots=True)
class DiffResult:
    missing: set[tuple[str, str]]
    unused: set[tuple[str, str]]
    discrepancy: set[tuple[str, str]]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit event templates vs code usages")
    parser.add_argument(
        "--json-output", action="store_true", help="Emit JSON diff result"
    )
    parser.add_argument(
        "--prune-unused",
        action="store_true",
        help="Remove unused templates from JSON file",
    )
    return parser.parse_args(argv)


def diff() -> DiffResult:
    missing, unused, discrepancy = compute_diff()
    return DiffResult(missing=missing, unused=unused, discrepancy=discrepancy)


def maybe_prune(args: argparse.Namespace, d: DiffResult) -> DiffResult:
    if args.prune_unused and d.unused and prune_unused(d.unused):
        print(f"Pruned {len(d.unused)} unused templates from JSON file")
        return diff()
    return d


def emit_json(d: DiffResult) -> None:
    print(
        json.dumps(
            {
                "missing": sorted(d.missing),
                "unused": sorted(d.unused),
                "discrepancy": sorted(d.discrepancy),
            },
            indent=2,
        )
    )


def emit_human(d: DiffResult) -> None:
    print("Event Template Audit Report")
    print("============================")
    print(
        f"Referenced in code (unique): {len(extract_references(iter_python_files(SRC_ROOT)))}"
    )
    print(f"Templates in JSON:           {len(load_templates_from_json())}")
    print(f"Loaded at runtime:           {len(EVENT_TEMPLATES)}")
    print()
    if d.missing:
        print(f"Missing templates ({len(d.missing)}):")
        for domain, action in sorted(d.missing):
            print(f"  - {domain}:{action}")
        print()
    else:
        print("No missing templates found.\n")
    if d.unused:
        print(f"Unused templates ({len(d.unused)}):")
        for domain, action in sorted(d.unused):
            print(f"  - {domain}:{action}")
        print()
    else:
        print("No unused templates found.\n")
    if d.discrepancy:
        print("Discrepancy between JSON and loaded templates (likely load error):")
        for domain, action in sorted(d.discrepancy):
            print(f"  - {domain}:{action}")
        print()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = diff()
    result = maybe_prune(args, result)
    if args.json_output:
        emit_json(result)
    else:
        emit_human(result)
    return 1 if result.missing else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
