"""Audit tool for event templates.

Moved to scripts/ directory.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Manually load event_catalog without creating a top-level 'src' package import that
# causes our 'token' package to shadow the stdlib 'token' during early import graph.
_SRC = Path(__file__).resolve().parent.parent / "src"
_CATALOG = _SRC / "logs" / "event_catalog.py"
_spec = importlib.util.spec_from_file_location("logs.event_catalog", _CATALOG)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    print("Failed to load event catalog spec", file=sys.stderr)
    EVENT_TEMPLATES: dict[tuple[str, str], str] = {}

    def reload_event_templates() -> None:
        """Fallback no-op when catalog can't be loaded."""
        pass
else:
    _mod = importlib.util.module_from_spec(_spec)
    # exec_module is dynamically typed; acceptable to suppress type checking locally
    _spec.loader.exec_module(_mod)
    loaded = getattr(_mod, "EVENT_TEMPLATES", {})
    if isinstance(loaded, dict):
        EVENT_TEMPLATES = loaded
    else:  # pragma: no cover - unexpected shape
        EVENT_TEMPLATES = {}
    reload_event_templates = getattr(_mod, "reload_event_templates", lambda: None)

PROJECT_ROOT = _SRC
SRC_ROOT = _SRC
TEMPLATES_JSON = _SRC / "logs" / "event_templates.json"

# Legacy regex (kept only as fallback for extremely small edge cases). AST-based
# extraction below is authoritative and captures ternary (IfExp) branches.
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


def _gather_string_literals(expr: ast.AST) -> set[str]:
    """Return all string literal values contained in expr.

    Supports:
      - ast.Constant (str)
      - ast.JoinedStr (f-strings) -> ignored (dynamic)
      - ast.IfExp: recursively gather from body/orelse
    """
    out: set[str] = set()
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        out.add(expr.value)
    elif isinstance(expr, ast.IfExp):  # ternary expression
        out.update(_gather_string_literals(expr.body))
        out.update(_gather_string_literals(expr.orelse))
    # Other expression kinds (Name, Attribute, Call, etc.) are dynamic -> skipped.
    return out


def _is_log_event_call(node: ast.Call) -> bool:
    """Heuristically determine if call is *.log_event (logger or self.logger)."""
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "log_event":
        return True
    return False


def _extract_from_call(node: ast.Call) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    domain_expr: ast.AST | None = None
    action_expr: ast.AST | None = None
    # Positional arguments
    if node.args:
        if len(node.args) >= 1:
            domain_expr = node.args[0]
        if len(node.args) >= 2:
            action_expr = node.args[1]
    # Keywords override / supplement
    for kw in node.keywords or []:
        if kw.arg == "domain":
            domain_expr = kw.value
        elif kw.arg == "action":
            action_expr = kw.value
    # Extract concrete domain
    if not (
        domain_expr
        and isinstance(domain_expr, ast.Constant)
        and isinstance(domain_expr.value, str)
    ):
        return pairs
    domain = domain_expr.value
    if not action_expr:
        return pairs
    for action in _gather_string_literals(action_expr):
        pairs.add((domain, action))
    return pairs


def extract_references(paths: Iterable[Path]) -> set[tuple[str, str]]:
    """Extract (domain, action) pairs via AST parsing.

    Falls back to regex scan only if AST parsing fails for a file (syntax error).
    Captures all branches of ternary expressions used for the action argument.
    """
    refs: set[tuple[str, str]] = set()
    for path in paths:
        _extract_file_references(path, refs)
    return refs


def _extract_file_references(path: Path, refs: set[tuple[str, str]]) -> None:
    """Populate refs with (domain, action) pairs from a single file."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):  # unreadable file
        return
    tree = _parse_ast(source, path)
    if tree is None:
        _regex_fallback(source, refs)
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_log_event_call(node):
            refs.update(_extract_from_call(node))


def _parse_ast(source: str, path: Path) -> ast.AST | None:
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def _regex_fallback(source: str, refs: set[tuple[str, str]]) -> None:
    for m in _RE_POSITIONAL.finditer(source):
        refs.add((m.group("domain"), m.group("action")))
    for m in _RE_KEYWORD.finditer(source):
        refs.add((m.group("domain"), m.group("action")))


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
