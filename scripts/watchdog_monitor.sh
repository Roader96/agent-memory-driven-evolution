#!/bin/bash
# watchdog_monitor.sh — 独立监视器：盯住两条关键链有没有干活
# 每天 9:00 由 launchd com.roader.hermes-watchdog-monitor 调用（Linux: crontab）
#
# 链①：daily_watchdog（23:55）→ 昨天 daily 有没有生成
# 链②：hermes-auto-update（02:00）→ 最近一次自动更新 stamp 是否 success
# 任一挂了 → 飞书告警 + macOS 通知（不重复修，只报告——修复归各自 watchdog）
#
# 通用版：飞书脚本存在才告警（`FEISHU_SCRIPT` 环境变量可覆盖路径）；
#         没有飞书配置 → 静默跳到 macOS 通知兜底，不报错。
set -u
VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
LOG="${WATCHDOG_MONITOR_LOG:-$HOME/.hermes/logs/watchdog_monitor.log}"
FEISHU="${FEISHU_SCRIPT:-$HOME/.hermes/scripts/send_feishu_dm.py}"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

notify() {
  log "notify: $1"
  if [ -x "$FEISHU" ]; then
    /usr/bin/python3 "$FEISHU" "🚨 Hermes 系统监视器：$1" >> "$LOG" 2>&1 || true
  fi
  # macOS 通知兜底（Linux 无 osascript 会静默忽略）
  /usr/bin/osascript -e "display notification \"$1\" with title \"Hermes 系统监视器\" sound name \"Basso\"" 2>/dev/null || true
}

TODAY=$(date +%Y-%m-%d)
log "===== monitor run (today=$TODAY) ====="

problems=""

# ---- 链①：daily 检查（昨天 + 最近 3 天）----
missing=""
for back in 1 2 3; do
  D=$(date -v-"${back}"d +%Y-%m-%d 2>/dev/null) || continue
  F="$VAULT/daily/${D}-每日总结.md"
  if [ ! -s "$F" ]; then
    missing="${missing} ${D}"
  fi
done
if [ -n "$missing" ]; then
  problems="${problems} [daily缺失:${missing}]"
fi

# ---- 链②：自动更新检查（最近一次 stamp 是否 updated，且不超过 2 天）----
STAMP="${AUTO_UPDATE_STAMP:-$HOME/.hermes/.last_auto_update.json}"
if [ -f "$STAMP" ]; then
  status=$(/usr/bin/python3 -c "
import json,sys
try:
    d=json.load(open('$STAMP'))
    print(d.get('status','none'))
except Exception as e:
    print('unreadable')
" 2>/dev/null)
  ts=$(/usr/bin/python3 -c "
import json
try:
    d=json.load(open('$STAMP'))
    print(d.get('ts',''))
except Exception:
    print('')
" 2>/dev/null)
  # 用 date 判断 stamp 是否太旧（>2 天 = 更新链可能挂了）
  if [ "$status" != "updated" ]; then
    problems="${problems} [auto-update 状态=${status}]"
  elif [ -n "$ts" ]; then
    # 比较 stamp 的日期，超过 2 天没成功更新 → 告警
    stamp_day=$(echo "$ts" | cut -d' ' -f1)
    if [ -n "$stamp_day" ]; then
      stamp_epoch=$(date -j -f "%Y-%m-%d" "$stamp_day" "+%s" 2>/dev/null) || stamp_epoch=0
      now_epoch=$(date "+%s")
      age_days=$(( (now_epoch - stamp_epoch) / 86400 ))
      if [ "$age_days" -gt 2 ]; then
        problems="${problems} [auto-update 已${age_days}天未更新(${status}@${ts})]"
      fi
    fi
  fi
else
  problems="${problems} [auto-update 无状态文件]"
fi

if [ -n "$problems" ]; then
  notify "系统链异常：${problems}。请查 daily_watchdog.log / auto_update.log"
  exit 0  # 不红，防 launchd 无脑重跑
fi

log "all chains healthy: daily OK, auto-update OK"
exit 0