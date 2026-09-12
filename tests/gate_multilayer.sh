#!/usr/bin/env bash
# ============================================================
# 开发验证门禁（dev gate）— 日常快速检查用
#
#   bash tests/gate_multilayer.sh
#
# 四层：1-static 静态语法/密钥扫描 / 2-unit 核心单测 /
#       3-isolated-integration 隔离集成 / 4-hermes-readonly 只读校验
#
# ⚠️ 这不是完整发布门禁！
# 正式发布前必须跑 tests/gate_release.sh（3 轮隔离安装 + 静态检查 +
# 适配层 + 引用完整性 + 单测 + 归档安全 + 发布门禁标记写入）
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="${TMPDIR:-/tmp}/agent-memory-gate.$(date +%Y%m%d-%H%M%S).$$"
mkdir -p "$REPORT_DIR"
trap 'rm -rf "$REPORT_DIR"' EXIT

PASS=0
FAIL=0
run_gate() {
  local name="$1"; shift
  local log="$REPORT_DIR/${name}.log"
  printf '\n=== %s ===\n' "$name"
  if "$@" >"$log" 2>&1; then
    PASS=$((PASS + 1))
    echo "PASS: $name"
  else
    FAIL=$((FAIL + 1))
    echo "FAIL: $name"
    tail -40 "$log" | sed 's/^/  /'
  fi
}

static_gate() {
  cd "$ROOT"
  git diff --check
  bash -n install.sh uninstall.sh scripts/*.sh scripts/lib/*.sh
  python3 -m compileall -q scripts tests/test_core_logic.py
  if rg -n 'ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|FEISHU_WEBHOOK|https://[^ ]*webhook' scripts; then
    echo 'possible secret or webhook found' >&2
    return 1
  fi
  if rg -n 'rm -rf ["'"'"']?\$HOME|rm -rf /Users|curl[^\n]*\|[^\n]*(sh|bash)' install.sh uninstall.sh scripts; then
    echo 'unsafe destructive/download pattern found' >&2
    return 1
  fi
}

unit_gate() {
  cd "$ROOT"
  python3 -m unittest discover -s tests -v
}

integration_gate() {
  cd "$ROOT"
  bash tests/test_install.sh
  bash tests/test_archive_security.sh
  bash tests/test_adapter.sh
  bash tests/test_references.sh
}

hermes_gate() {
  local hermes_home="${HERMES_HOME:-$HOME/.hermes}"
  test -d "$hermes_home"
  test -f "$hermes_home/state.db"
  python3 - "$hermes_home/state.db" <<'PY'
import sqlite3, sys
db = sys.argv[1]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
assert 'messages' in tables, f"messages table missing: {tables}"
cols = {r[1] for r in con.execute("pragma table_info(messages)")}
assert {'id', 'session_id', 'role'}.issubset(cols), cols
count = con.execute("select count(*) from messages").fetchone()[0]
print(f"state.db readable; messages={count}; tool_call_id={'yes' if 'tool_call_id' in cols else 'no'}")
con.close()
PY
  AGENT_TYPE=auto python3 scripts/adapters/agent_adapter.py
  python3 scripts/skill_evolution/metrics.py >/dev/null
}

run_gate "1-static" static_gate
run_gate "2-unit" unit_gate
run_gate "3-isolated-integration" integration_gate
run_gate "4-hermes-readonly" hermes_gate

echo
echo "Summary: $PASS passed / $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
  echo "Reports were stored temporarily under: $REPORT_DIR" >&2
  exit 1
fi
echo "All multilayer gates passed"
