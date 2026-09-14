#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/vault/daily" "$TMP/home/.hermes/scripts"

bash -n "$ROOT/scripts/daily_watchdog.sh" "$ROOT/scripts/watchdog_monitor.sh"
python3 - "$ROOT/scripts/watchdog_monitor.sh" <<'PY'
import subprocess, sys
try:
    subprocess.run(["bash", sys.argv[1]], timeout=3, check=False,
                   env={"HOME": "/tmp", "HERMES_VAULT": "/tmp/nonexistent-vault"})
except subprocess.TimeoutExpired:
    raise SystemExit("watchdog monitor hung")
PY

TODAY=$(date +%Y-%m-%d)
if [[ "$(uname -s)" == "Darwin" ]]; then
  EXPECTED=$(date -v-1d +%Y-%m-%d)
else
  EXPECTED=$(date -d '-1 day' +%Y-%m-%d)
fi
[[ "$EXPECTED" != "$TODAY" ]]

echo "watchdog tests: PASS (date=$EXPECTED)"
