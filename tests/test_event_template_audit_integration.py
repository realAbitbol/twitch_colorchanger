"""Integration test for event template audit ensuring no missing templates.

Runs the audit directly in test code (no dependency on scripts/).
"""
from __future__ import annotations

import ast
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# --- Minimal loader for event catalog without importing project as a package ---
_SRC = Path(__file__).parents[1] / "src"
_CATALOG = _SRC / "logs" / "event_catalog.py"
spec = importlib.util.spec_from_file_location("logs.event_catalog", _CATALOG)
if not (spec and spec.loader):  # Avoid bare assert (Bandit B101)
    raise AssertionError("Could not create spec for event_catalog")
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)  # type: ignore[assignment]
reload_event_templates = getattr(_mod, "reload_event_templates")
EVENT_TEMPLATES: dict[tuple[str, str], str] = getattr(_mod, "EVENT_TEMPLATES")
TEMPLATES_JSON = _SRC / "logs" / "event_templates.json"


# --- AST helpers (subset of scripts/event_template_audit.py, tailored for tests) ---
def iter_python_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        # Skip tests and third-party
        if "/tests/" in str(p) or p.name.startswith("_"):
            continue
        yield p


def _is_log_event_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "log_event"


def _select_domain_and_action_expr(
    call: ast.Call,
) -> tuple[ast.AST | None, ast.AST | None]:
    domain_expr: ast.AST | None = None
    action_expr: ast.AST | None = None
    if call.args:
        if len(call.args) >= 1:
            domain_expr = call.args[0]
        if len(call.args) >= 2:
            action_expr = call.args[1]
    for kw in call.keywords or []:
        if kw.arg == "domain":
            domain_expr = kw.value
        elif kw.arg == "action":
            action_expr = kw.value
    return domain_expr, action_expr


def _gather_string_literals(expr: ast.AST) -> set[str]:
    values: set[str] = set()
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        values.add(expr.value)
        return values
    if isinstance(expr, ast.IfExp):  # capture ternary branches
        values |= _gather_string_literals(expr.body)
        values |= _gather_string_literals(expr.orelse)
        return values
    if isinstance(expr, (ast.Tuple, ast.List)):
        for elt in expr.elts:
            values |= _gather_string_literals(elt)
        return values
    # For other complex expressions, we conservatively return empty
    return values


def _collect_module_consts(tree: ast.AST) -> dict[str, str]:
    consts: dict[str, str] = {}
    for stmt in getattr(tree, "body", []):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            tgt = stmt.targets[0]
            if (
                isinstance(tgt, ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
                and tgt.id not in consts
            ):
                consts[tgt.id] = stmt.value.value
    return consts


def _collect_function_consts(tree: ast.AST) -> dict[ast.FunctionDef, dict[str, str]]:
    result: dict[ast.FunctionDef, dict[str, str]] = {}
    for node in getattr(tree, "body", []) or []:
        if isinstance(node, ast.FunctionDef):
            result[node] = _collect_consts_in_function(node)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef):
                    result[sub] = _collect_consts_in_function(sub)
    return result


def _collect_consts_in_function(fn: ast.FunctionDef) -> dict[str, str]:
    local: dict[str, str] = {}
    for stmt in fn.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            tgt = stmt.targets[0]
            if (
                isinstance(tgt, ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
                and tgt.id not in local
            ):
                local[tgt.id] = stmt.value.value
    return local


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _nearest_function(
    node: ast.AST, parent: dict[ast.AST, ast.AST]
) -> ast.FunctionDef | None:
    cur = node
    while cur in parent:
        cur = parent[cur]
        if isinstance(cur, ast.FunctionDef):
            return cur
    return None


def _resolve_domain_value(
    expr: ast.AST, module_consts: dict[str, str], local_map: dict[str, str] | None
) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        if local_map and expr.id in local_map:
            return local_map[expr.id]
        return module_consts.get(expr.id)
    return None


def _collect_action_values(
    action_expr: ast.AST,
    module_consts: dict[str, str],
    local_map: dict[str, str] | None,
) -> set[str]:
    values: set[str] = set()
    if isinstance(action_expr, ast.Name):
        name = action_expr.id
        if local_map and name in local_map:
            values.add(local_map[name])
        elif name in module_consts:
            values.add(module_consts[name])
    values |= _gather_string_literals(action_expr)
    return values


def _extract_from_call(node: ast.Call) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    domain_expr, action_expr = _select_domain_and_action_expr(node)
    if not (
        domain_expr
        and isinstance(domain_expr, ast.Constant)
        and isinstance(domain_expr.value, str)
    ):
        return pairs
    if not action_expr:
        return pairs
    domain = domain_expr.value
    for action in _gather_string_literals(action_expr):
        pairs.add((domain, action))
    return pairs


def _extract_with_resolution(
    call: ast.Call, module_consts: dict[str, str], local_map: dict[str, str] | None
) -> set[tuple[str, str]]:
    domain_expr, action_expr = _select_domain_and_action_expr(call)
    if domain_expr is None or action_expr is None:
        return set()
    domain_val = _resolve_domain_value(domain_expr, module_consts, local_map)
    if domain_val is None:
        return set()
    action_values = _collect_action_values(action_expr, module_consts, local_map)
    if not action_values:
        return set()
    return {(domain_val, a) for a in action_values}


def extract_references(paths: Iterable[Path]) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        parent = _build_parent_map(tree)
        module_consts = _collect_module_consts(tree)
        func_consts = _collect_function_consts(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_log_event_call(node):
                fn = _nearest_function(node, parent)
                local_map = func_consts.get(fn) if fn else None
                refs.update(_extract_from_call(node))
                refs.update(_extract_with_resolution(node, module_consts, local_map))
    return refs


def load_templates_from_json() -> set[tuple[str, str]]:
    try:
        raw = json.loads(TEMPLATES_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    result: set[tuple[str, str]] = set()
    if isinstance(raw, dict):
        for domain, actions in raw.items():
            if isinstance(actions, dict):
                for action in actions:
                    result.add((domain, action))
    return result


@dataclass(slots=True)
class DiffResult:
    missing: set[tuple[str, str]]
    unused: set[tuple[str, str]]
    discrepancy: set[tuple[str, str]]


def diff() -> DiffResult:
    reload_event_templates()
    code_refs = extract_references(iter_python_files(_SRC))
    json_templates = load_templates_from_json()
    loaded_templates = set(EVENT_TEMPLATES.keys())
    missing = code_refs - json_templates
    unused = json_templates - code_refs
    discrepancy = loaded_templates ^ json_templates
    return DiffResult(missing=missing, unused=unused, discrepancy=discrepancy)


def test_event_template_audit_no_missing():  # noqa: D401
    result = diff()
    if result.missing:  # Use conditional raise to satisfy security linters
        raise AssertionError(f"Missing event templates: {sorted(result.missing)}")


def test_event_template_audit_no_unused():  # noqa: D401
    result = diff()
    if result.unused:
        raise AssertionError(f"Unused event templates: {sorted(result.unused)}")
