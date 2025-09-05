from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path


def test_event_catalog_missing_file() -> None:
    # Create a temp dir and copy the module file but remove the json to force fallback
    from src.logs import event_catalog as original
    py_path = Path(original.__file__)
    temp_dir = Path(tempfile.mkdtemp())
    try:
        temp_module = temp_dir / "event_catalog.py"
        temp_module.write_text(py_path.read_text(encoding="utf-8"), encoding="utf-8")
        # Intentionally do NOT copy event_templates.json
        spec = importlib.util.spec_from_file_location("logs.event_catalog_temp", temp_module)
        if not (spec and spec.loader):  # pragma: no cover
            raise AssertionError("Spec creation failed")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        templates = mod.EVENT_TEMPLATES
        if ("app", "load_error") not in templates:
            raise AssertionError("Expected load_error fallback when file missing")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
