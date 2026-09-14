#!/bin/bash
# watchdog_monitor.sh — 独立监视器：盯住 daily_watchdog 有没有干活
# 每天 9:00 由 launchd com.roader.hermes-watchdog-monitor 调用（Linux: crontab）
# 职责：检查昨天(以及昨天之前最近几天)的 daily 是否生成；没生成 → 飞书告警
#       不重复修，只报告——修复归 watchdog 自己（回填窗口已扩到 7 天）
#
# 通用版：飞书脚本存在才告警（`FEISHU_SCRIPT` 环境变量可覆盖路径）；
#         没有飞书配置 → 静默跳到 macOS 通知兜底，不报错。
set -u
VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
LOG="${WATCHDOG_MONITOR_LOG:-$HOME/.hermes/logs/watchdog_monitor.log}"
FEISHU="${FEISHU_SCRIPT:-$HOME/.hermes/scripts/send_feishu_dm.py}"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

date_days_ago() {
  if date -v-1d +%Y-%m-%d >/dev/null 2>&1; then
    date -v-"$1"d +%Y-%m-%d
  else
    date -d "-$1 day" +%Y-%m-%d
  fi
}

notify() {
  log "notify: $1"
  if [ -x "$FEISHU" ]; then
    /usr/bin/python3 "$FEISHU" "🚨 Hermes 每日总结异常：$1" >> "$LOG" 2>&1 || true
  fi
  # macOS 通知兜底（Linux 无 osascript 会静默忽略）
  /usr/bin/osascript -e "display notification \"$1\" with title \"Hermes 每日总结异常\" sound name \"Basso\"" 2>/dev/null || true
}

TODAY=$(date +%Y-%m-%d)
log "===== monitor run (today=$TODAY) ====="

# 检查昨天 + 最近 3 天有没有 daily（昨天必查，更早的天缺失说明回填也失败了）
missing=""
for back in 1 2 3; do
  D=$(date_days_ago "$back" 2>/dev/null) || continue
  F="$VAULT/daily/${D}-每日总结.md"
  if [ ! -s "$F" ]; then
    missing="${missing} ${D}"
  fi
done

if [ -n "$missing" ]; then
  notify "昨天/近期 daily 缺失：${missing}。看门狗可能没跑，请查 ${LOG}"
  exit 0  # 不红，防 launchd 无脑重跑
fi

log "all recent dailies present: OK"
exit 0
