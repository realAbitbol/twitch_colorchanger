#!/usr/bin/env python3
"""Import smoke test.

Adds ./src to sys.path and attempts to import every discoverable top-level
module/package beneath it, reporting failures and a summary.

Usage:
  python scripts/import_smoke_test.py

Exit code 0 if all imports succeed, 1 otherwise.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

failures: dict[str, str] = {}
loaded: list[str] = []

# Discover modules/packages directly under src (recursive)
SKIP = {"main", "async_irc", "bot"}
OPTIONAL_DEPS = {"aiohttp", "watchdog"}

for mod in pkgutil.walk_packages([str(SRC)], prefix=""):
    name = mod.name
    if name.startswith("__") or name in SKIP:
        continue
    try:
        importlib.import_module(name)
        loaded.append(name)
    except ModuleNotFoundError as e:  # noqa: BLE001
        missing = getattr(e, "name", "")
        if missing in OPTIONAL_DEPS:
            print(f"[skip-missing-dep] {name} (needs {missing})")
            continue
        failures[name] = traceback.format_exc()
    except Exception:  # noqa: BLE001
        failures[name] = traceback.format_exc()

loaded.sort()

print(f"Imported modules: {len(loaded)}")
if failures:
    print(f"Failures: {len(failures)}")
    for k, tb in sorted(failures.items()):
        print(f"--- FAILURE: {k} ---")
        print("\n".join(tb.splitlines()[-25:]))
else:
    print("All imports succeeded.")

# Non‑zero exit if any failures
if failures:
    sys.exit(1)
