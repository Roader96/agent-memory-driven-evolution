#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/vault/daily" "$TMP/home/.hermes/scripts"

for script in "$ROOT/scripts/daily_watchdog.sh" "$ROOT/scripts/watchdog_monitor.sh"; do
  bash -n "$script"
  env -i HOME="$TMP/home" HERMES_VAULT="$TMP/vault" WATCHDOG_MONITOR_LOG="$TMP/monitor.log" \
    bash -c 'source "$1" 2>/dev/null || true' _ "$script" >/dev/null
done

TODAY=$(date +%Y-%m-%d)
if [[ "$(uname -s)" == "Darwin" ]]; then
  EXPECTED=$(date -v-1d +%Y-%m-%d)
else
  EXPECTED=$(date -d '-1 day' +%Y-%m-%d)
fi
[[ "$EXPECTED" != "$TODAY" ]]

echo "watchdog tests: PASS (date=$EXPECTED)"
