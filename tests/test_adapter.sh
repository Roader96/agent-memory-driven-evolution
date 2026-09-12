#!/usr/bin/env bash
# test_adapter.sh — Agent 适配层门禁测试
# 验证 agent_adapter.py 在三种环境下的行为：
#   1. Hermes 环境（本机，state.db 存在）→ 读真库
#   2. Generic 环境（无 hermes，临时 HOME）→ 文件系统降级
#   3. LLM/归档缺失 → 优雅降级不崩溃
#
# 用法: bash tests/test_adapter.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADAPTER="$PROJECT_DIR/scripts/adapters/agent_adapter.py"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL+1)); echo "  ✗ $1"; }

echo "== Agent 适配层门禁测试 =="

# ─── 场景 1：Hermes 环境（本机）───────────────
echo "[1/3] Hermes 环境检测"
AGENT=$(env -u HERMES_HOME -u HERMES_BIN AGENT_TYPE=auto python3 "$ADAPTER")
echo "  输出: $AGENT"
if echo "$AGENT" | grep -q "auto→hermes"; then
  ok "auto 检测到 hermes"
elif echo "$AGENT" | grep -q "auto→generic"; then
  ok "当前 runner 无 Hermes，auto 正确降级到 generic"
else
  fail "auto 未检测到 hermes（输出: $AGENT）"
fi

# Hermes 模式读 state.db 不崩溃
echo "[2/3] Hermes 模式 skill_facts"
RESULT=$(env -u HERMES_HOME -u HERMES_BIN python3 -c "
import sys; sys.path.insert(0, '$PROJECT_DIR/scripts/adapters')
import agent_adapter as A
f = A.generic_skill_facts()
print('count', len(f))
print('sample', f[0]['name'] if f else 'none')
")
echo "  输出: $RESULT"
if echo "$RESULT" | grep -q "^count [0-9]"; then
  ok "Hermes 模式成功读取技能统计"
else
  fail "Hermes 模式读取失败"
fi

# ─── 场景 2：Generic 降级（临时 HOME + 无 hermes）────────
echo "[2/3] Generic 降级（隔离 HOME）"
TMPHOME=$(mktemp -d)
trap 'rm -rf "$TMPHOME"' EXIT
mkdir -p "$TMPHOME/.hermes/skills/test-skill"
printf -- '---\nname: test-skill\n---\n# Test\n' > "$TMPHOME/.hermes/skills/test-skill/SKILL.md"

GEN_OUT=$(env -u HERMES_HOME -u HERMES_BIN AGENT_TYPE=generic HOME="$TMPHOME" python3 -c "
import sys; sys.path.insert(0, '$PROJECT_DIR/scripts/adapters')
import agent_adapter as A
print('detect', A.detect())
print('hermes_home', A._hermes_home())
f = A.generic_skill_facts()
print('count', len(f))
print('names', [x['name'] for x in f])
")
echo "  输出: $GEN_OUT"
if echo "$GEN_OUT" | grep -q "detect generic"; then
  ok "generic 检测生效"
else
  fail "generic 检测失败"
fi
if echo "$GEN_OUT" | grep -q "test-skill"; then
  ok "generic 降级读到隔离技能（不串本机）"
else
  fail "generic 降级读错目录"
fi

# 不设 AGENT_TYPE 的自动检测也应工作（无 state.db → generic）
AUTO_OUT=$(env -u HERMES_HOME -u HERMES_BIN AGENT_TYPE=auto HOME="$TMPHOME" python3 -c "
import sys; sys.path.insert(0, '$PROJECT_DIR/scripts/adapters')
import agent_adapter as A
print('detect', A.detect())
")
echo "  输出: $AUTO_OUT"
if echo "$AUTO_OUT" | grep -q "detect generic"; then
  ok "auto 检测在无 hermes 环境降级到 generic"
else
  fail "auto 检测未降级"
fi

# ─── 场景 3：LLM/归档缺失优雅降级 ────────────────
echo "[3/3] LLM/归档缺失降级"
LLM_OUT=$(env -u HERMES_HOME -u HERMES_BIN AGENT_TYPE=generic HOME="$TMPHOME" AGENT_LLM="/nonexistent/llm" python3 -c "
import sys; sys.path.insert(0, '$PROJECT_DIR/scripts/adapters')
import agent_adapter as A
r = A.llm_call('test')
print('llm_return', repr(r))
a = A.archive_session('test-src')
print('archive_return', a)
")
echo "  输出: $LLM_OUT"
if echo "$LLM_OUT" | grep -q "llm_return ''"; then
  ok "LLM 缺失返回空串（不抛异常）"
else
  fail "LLM 缺失未优雅降级"
fi
if echo "$LLM_OUT" | grep -q "archive_return False"; then
  ok "归档缺失返回 False（不抛异常）"
else
  fail "归档缺失未优雅降级"
fi

echo
echo "结果: $PASS 通过, $FAIL 失败"
[ "$FAIL" -eq 0 ] || exit 1
echo "✓ 适配层门禁通过"
