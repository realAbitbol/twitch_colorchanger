#!/usr/bin/env bash
set -euo pipefail

# Cleanup script for removing deprecated/legacy files after refactor.
# Maintained automatically by the refactor assistant. Execute manually when ready.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[cleanup] Starting leftover cleanup scan in $ROOT_DIR"

# List of legacy files safe to delete (will be pruned as imports updated)
LEGACY_FILES=(
  # Newly identified leftovers after subsystem packaging
  "src/color_change_service.py"   # replaced by color/service.py
  "src/color_utils.py"            # replaced by color/utils.py
  "src/utils.py"                  # duplicate of utils/ package
  # Second wave: after moving core implementations into packages
  "src/async_irc.py"              # replaced by irc/async_irc.py
  "src/bot.py"                    # replaced by bot/core.py (exported via bot/__init__.py)
  "src/config.py"                 # superseded by config/ package (core.py + __init__ exports)
  "src/bot_manager.py"            # replaced by bot/manager.py (shim removable)
)

deleted=0
for f in "${LEGACY_FILES[@]}"; do
  if [ -f "$ROOT_DIR/$f" ]; then
    echo "[cleanup] Deleting $f"
    git rm -f "$ROOT_DIR/$f" 2>/dev/null || rm -f "$ROOT_DIR/$f"
    deleted=$((deleted+1))
  else
    echo "[cleanup] Already removed: $f"
  fi
done

echo "[cleanup] Completed. Files deleted: $deleted"
echo "[cleanup] Reminder: commit these deletions if satisfied (git add -u && git commit)."
