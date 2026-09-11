#!/usr/bin/env bash
# test_references.sh — 引用完整性门禁测试
# 验证：仓库内所有脚本/文档引用的辅助脚本，在安装后真实存在（开箱即用）
#
# 背景：历史教训——send_feishu_dm.py / daily_summary_enhanced.py 等 6 个被
# 核心流程(每周周报 run_weekly.py / 每日总结 daily_summary.sh)引用的脚本，
# 曾被遗漏发布，导致用户安装后"每天静默失败"。
# 本测试保证：任何被引用的辅助脚本缺失 → 门禁失败。
#
# 用法: bash tests/test_references.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL+1)); echo "  ✗ $1"; }

echo "== 引用完整性门禁测试 =="

# 收集所有被引用的辅助脚本名（scripts/*.py *.sh 里被调用的）
# 1. daily_summary.sh 引用的每日流程
for s in daily_summary_enhanced.py vault_postprocess.py scan_learnings.py auto_archive_hook.sh; do
  if [ -f "$PROJECT_DIR/scripts/$s" ]; then
    ok "daily 流程脚本存在: $s"
  else
    fail "daily 流程脚本缺失: $s"
  fi
done

# 2. run_weekly.py 引用的周报
for s in send_feishu_dm.py; do
  if [ -f "$PROJECT_DIR/scripts/$s" ]; then
    ok "周报脚本存在: $s"
  else
    fail "周报脚本缺失: $s"
  fi
done

# 3. 记忆系统核心（SKILL.md 承诺的机制）
for s in hot_memory_watchdog.sh daily_watchdog.sh daily_summary_from_db.py verify_daily_pipeline.py; do
  if [ -f "$PROJECT_DIR/scripts/$s" ]; then
    ok "记忆系统脚本存在: $s"
  else
    fail "记忆系统脚本缺失: $s"
  fi
done

# 4. 全量扫描：scripts 目录内互相引用但文件不存在的脚本名（防遗漏）
echo "  --- 全量引用扫描 ---"
missing=0
# 从所有 .py/.sh 里提取被引用的 scripts/xxx.py|sh（相对 HOME/.hermes/scripts 的调用）
while IFS= read -r name; do
  [ -z "$name" ] && continue
  if [ ! -f "$PROJECT_DIR/scripts/$name" ] && [ ! -f "$PROJECT_DIR/scripts/skill_evolution/$name" ] \
     && [ ! -f "$PROJECT_DIR/scripts/lib/$name" ] && [ ! -f "$PROJECT_DIR/scripts/adapters/$name" ] \
     && [ ! -f "$PROJECT_DIR/$name" ]; then
    echo "    ⚠️ 引用但缺失: $name"
    missing=$((missing+1))
  fi
done < <(grep -rhoE '([a-zA-Z0-9_./-]*/)?[a-zA-Z0-9_./-]+\.(py|sh)' "$PROJECT_DIR/scripts" 2>/dev/null \
         | sed 's|.*/||' | sort -u)
if [ "$missing" -eq 0 ]; then
  ok "全量引用扫描：无缺失脚本"
else
  fail "全量引用扫描：$missing 个脚本被引用但缺失"
fi

echo
echo "结果: $PASS 通过, $FAIL 失败"
[ "$FAIL" -eq 0 ] || exit 1
echo "✓ 引用完整性门禁通过"