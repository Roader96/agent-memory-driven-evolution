#!/bin/bash
# 每日 23:50 总结 - 由 cron 调用
# 写今日 daily 总结 + 跑后处理 + 报告状态

VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
# 允许手动补跑历史日期：DATE_OVERRIDE=2026-08-11 TIME_OVERRIDE=23:50 bash daily_summary.sh
DATE=${DATE_OVERRIDE:-$(date +%Y-%m-%d)}
TIME=${TIME_OVERRIDE:-$(date +%H:%M)}

# 带重试的 python 调用：3次失败 -> 静默，不让 cron 红
run_py() {
  local script="$1"
  local tries=0
  while [ $tries -lt 3 ]; do
    if python3 "$script" 2>&1 | tail -8; then
      return 0
    fi
    tries=$((tries + 1))
    echo "⚠️ $script 第 $tries 次失败，2s 后重试" >&2
    sleep 2
  done
  echo "⚠️ $script 3次都失败，跳过（不影响 daily 写入）" >&2
  return 0  # 不让 set -e 杀进程
}

# ============ 1. 今日 daily 总结（仅首次）============
DAILY_FILE="$VAULT/daily/${DATE}-每日总结.md"
if [ ! -f "$DAILY_FILE" ]; then
  # 调用增强版 Python 脚本（读正文提炼实质内容）
  run_py "$HOME/.hermes/scripts/daily_summary_enhanced.py"
else
  echo "⏭️ 今日 daily 已存在，跳过"
fi

# 2. 跑后处理（带重试 + 离线兜底）
run_py "$HOME/.hermes/scripts/vault_postprocess.py"

# 2.5 扫描 learnings 高频项（自我提升，带重试 + 离线兜底）
run_py "$HOME/.hermes/scripts/scan_learnings.py"

# ============ 3. hook 状态 ============
echo ""
echo "=== 系统状态 ==="
$HOME/.hermes/scripts/auto_archive_hook.sh status
