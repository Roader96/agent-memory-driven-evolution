#!/usr/bin/env bash
# Structured Codex memory maintenance entrypoint.
#
# Standalone layout:
#   ~/CodexMemory/bin/codex_memory.py
#   ~/CodexMemory/bin/codex_memory_maintenance.sh
#   ~/CodexMemory/logs, locks, sessions, ...
#
# It does not require ~/.hermes, ~/HermesMemory, Hermes state.db, an LLM
# service, or Obsidian at runtime.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(basename "$SCRIPT_DIR")" = "bin" ]; then
  DEFAULT_MEMORY_HOME="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  DEFAULT_MEMORY_HOME="$HOME/CodexMemory"
fi
CODEX_MEMORY_HOME="${CODEX_MEMORY_HOME:-$DEFAULT_MEMORY_HOME}"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
LOG_DIR="$CODEX_MEMORY_HOME/logs"
LOG_FILE="$LOG_DIR/codex_memory.log"
LOCK_DIR="$CODEX_MEMORY_HOME/locks/codex_memory.lock"
PYTHON_SCRIPT="$CODEX_MEMORY_HOME/bin/codex_memory.py"

if [[ ! -f "$PYTHON_SCRIPT" && -f "$SCRIPT_DIR/codex_memory.py" ]]; then
  PYTHON_SCRIPT="$SCRIPT_DIR/codex_memory.py"
fi

mkdir -p "$LOG_DIR" "$CODEX_MEMORY_HOME/locks"
stamp() { date '+%Y-%m-%d %H:%M:%S%z'; }

release_lock() {
  if [[ -f "$LOCK_DIR/pid" ]] && [[ "$(cat "$LOCK_DIR/pid" 2>/dev/null || true)" == "$$" ]]; then
    rm -rf "$LOCK_DIR"
  fi
}
trap release_lock EXIT

if [[ ! -d "$CODEX_ROOT" ]]; then
  printf '%s SKIP codex home missing: %s\n' "$(stamp)" "$CODEX_ROOT" >> "$LOG_FILE"
  exit 0
fi

if [[ ! -f "$PYTHON_SCRIPT" ]]; then
  printf '%s FAIL codex_memory.py missing: %s\n' "$(stamp)" "$PYTHON_SCRIPT" >> "$LOG_FILE"
  exit 1
fi

# The standalone Codex LaunchAgent is the only production scheduler for this
# component. mkdir is atomic; a live second runner exits successfully instead
# of rebuilding the same memory home concurrently. Stale locks are reclaimed.
for _ in 1 2 3 4 5; do
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$LOCK_DIR/pid"
    break
  fi
  old_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    printf '%s SKIP codex memory maintenance already running (pid %s)\n' "$(stamp)" "$old_pid" >> "$LOG_FILE"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$LOCK_DIR/pid"
    break
  fi
  sleep 1
done
if [[ ! -f "$LOCK_DIR/pid" ]] || [[ "$(cat "$LOCK_DIR/pid" 2>/dev/null || true)" != "$$" ]]; then
  printf '%s FAIL could not acquire codex memory lock\n' "$(stamp)" >> "$LOG_FILE"
  exit 1
fi

if "$PYTHON_BIN" "$PYTHON_SCRIPT" --memory-home "$CODEX_MEMORY_HOME" --codex-home "$CODEX_ROOT" >> "$LOG_FILE" 2>&1; then
  printf '%s OK codex structured memory (%s)\n' "$(stamp)" "$PYTHON_SCRIPT" >> "$LOG_FILE"
else
  printf '%s FAIL codex structured memory (%s)\n' "$(stamp)" "$PYTHON_SCRIPT" >> "$LOG_FILE"
  exit 1
fi
