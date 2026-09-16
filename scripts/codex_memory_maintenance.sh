#!/usr/bin/env bash
set -euo pipefail

HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"
VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
SCRIPT="$HERMES_ROOT/scripts/codex_memory.py"
LOG_DIR="$HERMES_ROOT/logs"
LOG_FILE="$LOG_DIR/codex_memory.log"
LOCK_DIR="$HERMES_ROOT/locks/codex_memory.lock"

mkdir -p "$LOG_DIR" "$HERMES_ROOT/locks"
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

if [[ ! -f "$SCRIPT" ]]; then
  printf '%s FAIL codex_memory.py missing: %s\n' "$(stamp)" "$SCRIPT" >> "$LOG_FILE"
  exit 1
fi

# daily_watchdog and the standalone Codex LaunchAgent may fire at 23:55.
# mkdir is atomic; a live second runner exits successfully instead of rebuilding
# the same vault concurrently. Stale locks from killed runs are reclaimed.
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

if /usr/bin/python3 "$SCRIPT" --vault "$VAULT" --codex-home "$CODEX_ROOT" >> "$LOG_FILE" 2>&1; then
  printf '%s OK codex structured memory\n' "$(stamp)" >> "$LOG_FILE"
else
  printf '%s FAIL codex structured memory\n' "$(stamp)" >> "$LOG_FILE"
  exit 1
fi
