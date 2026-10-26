#!/bin/bash
# watchdog_monitor.sh — 独立监视器：盯住两条关键链有没有干活
# 每天 9:00 由 launchd com.roader.hermes-watchdog-monitor 调用（Linux: crontab）
#
# 链①：daily_watchdog（23:55）→ 昨天 daily 有没有生成
# 链②：每周技能审查 → 内容健康（降级/过期不能只看退出码）
# 自动更新检查仅在 CHECK_AUTO_UPDATE=1 时启用。
# 异常沿用已配置的飞书告警；WATCHDOG_SILENT=1 可用于本地验证。
set -u
VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
LOG="${WATCHDOG_MONITOR_LOG:-$HOME/.hermes/logs/watchdog_monitor.log}"
FEISHU="${FEISHU_SCRIPT:-$HOME/.hermes/scripts/send_feishu_dm.py}"
mkdir -p "$(dirname "$LOG")"

# 测试/隔离环境检测：HOME 不是真实用户目录（如 mktemp /tmp /var/folders）→ 静默跑，不弹系统通知
# 覆盖：WATCHDOG_SILENT=1 强制静默；标准测试 env 也自动识别
if [ "${WATCHDOG_SILENT:-0}" = "1" ] || [ -n "${HERMES_VAULT_TEST:-}" ] || \
   case "$HOME" in /var/folders/*|/tmp/*|/private/tmp/*) true;; *) false;; esac; then
  SILENT=1
else
  SILENT=0
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

notify() {
  log "notify: $1"
  [ "$SILENT" = "1" ] && { log "  (静默模式，跳过系统通知)"; return 0; }
  local helper="$(dirname "${BASH_SOURCE[0]}")/health_alert.py"
  local alert_state="${ALERT_STATE:-$HOME/.hermes/logs/memory-alert-state.json}"
  if [ ! -f "$helper" ]; then log "FAIL missing alert helper"; return 1; fi
  if ! /usr/bin/python3 "$helper" plan --state "$alert_state" --message "$1"; then
    log "unchanged alert suppressed"
    return 0
  fi
  local delivered=0
  if [ -x "$FEISHU" ] && /usr/bin/python3 "$FEISHU" "🚨 记忆系统：$1" >> "$LOG" 2>&1; then
    delivered=1
  fi
  /usr/bin/python3 "$helper" ack --state "$alert_state" --delivered "$delivered"
  [ "$delivered" = "1" ] || log "FAIL alert delivery; retained for retry"
}

TODAY=$(date +%Y-%m-%d)
log "===== monitor run (today=$TODAY) ====="

problems=""

# ---- 链①：daily 检查（昨天 + 最近 3 天）----
missing=""
for back in 1 2 3; do
  D=$(date -v-"${back}"d +%Y-%m-%d 2>/dev/null) || \
    D=$(date -d "${back} days ago" +%Y-%m-%d 2>/dev/null) || continue
  F="$VAULT/daily/${D}-每日总结.md"
  if [ ! -s "$F" ]; then
    missing="${missing} ${D}"
  fi
done
if [ -n "$missing" ]; then
  problems="${problems} [daily缺失:${missing}]"
fi

# Weekly jobs may exit 0 while the LLM review is degraded. Inspect content
# health separately from launchd exit status. Missing optional installations
# are ignored; an installed review must have a recent, healthy result.
weekly_problem=$(/usr/bin/python3 - "$VAULT" <<'PY'
import json, sys
from datetime import datetime
from pathlib import Path
vault = Path(sys.argv[1])
import os
memory = Path(os.environ.get('CODEX_MEMORY_HOME', str(Path.home() / 'CodexMemory')))
settings = memory / 'skill-evolution/settings.json'
backend = json.loads(settings.read_text()).get('backend') if settings.exists() else 'legacy'
hp = (memory / 'skill-evolution/review-health.json') if backend == 'codex_direct' else vault / '.checkpoints/evolution-health.json'
reports = sorted((vault / 'skill-evolution').glob('*-skill-evolution-weekly.md'))
try:
    if backend == 'codex_direct':
        archive_path = memory / '.index/health.json'
        if not archive_path.exists():
            print('Codex归档缺少健康记录')
        else:
            archive = json.loads(archive_path.read_text())
            stamp = datetime.fromisoformat(archive['checked_at'])
            if (datetime.now(stamp.tzinfo) - stamp).total_seconds() > 7200:
                print('Codex归档超过2小时未更新')
        ledger = Path(os.environ.get('HERMES_HOME', str(Path.home()/'.hermes'))) / 'skill_evolution/state.json'
        if ledger.exists():
            doc = json.loads(ledger.read_text())
            proposals = doc.get('proposals', [])
            ids = [p.get('id') for p in proposals]
            if len(ids) != len(set(ids)):
                print('提案身份冲突')
            by_id = {p['id']:p for p in proposals}
            if any(f.get('link_status') != 'unresolved' and
                   (by_id.get(f.get('proposal_id'),{}).get('target') != f.get('target') or
                    by_id.get(f.get('proposal_id'),{}).get('uid') != f.get('proposal_uid'))
                   for f in doc.get('follow_ups',[])):
                print('回测身份关联失效')
        semantic = memory / '.index/semantic-health.json'
        if (memory / 'models/multilingual-e5-small/model-provenance.json').exists():
            if not semantic.exists() or json.loads(semantic.read_text()).get('status') != 'ok':
                print('本地语义索引未就绪')
    if hp.exists():
        health = json.loads(hp.read_text())
        stamp = datetime.fromisoformat(health['checked_at'])
        current = datetime.now(stamp.tzinfo) if stamp.tzinfo else datetime.now()
        age = (current - stamp).total_seconds()
        if age > 9 * 86400:
            print('weekly审查超过9天未更新')
        elif health.get('findings_count', 0):
            print('GPT审查存在待处理问题:' + str(health['findings_count']))
        elif health.get('status') not in ('ok', 'reviewed_with_findings'):
            print('weekly审查降级:' + str(health.get('reason', 'unknown'))[:160])
    elif backend == 'codex_direct':
        print('GPT审查尚无完成记录')
    elif reports:
        latest = reports[-1]
        age = (datetime.now() - datetime.strptime(latest.name[:10], '%Y-%m-%d')).days
        if age > 9:
            print('weekly周报超过9天未更新')
        elif '本周 LLM 未产出' in latest.read_text():
            print('weekly审查降级:见最新周报')
except (ValueError, KeyError, OSError, TypeError):
    print('weekly健康记录损坏')
PY
)
if [ -n "$weekly_problem" ]; then
  problems="${problems} [$weekly_problem]"
fi

# ---- 可选自动更新检查：仅仍启用自动更新的安装设置 CHECK_AUTO_UPDATE=1 ----
if [ "${CHECK_AUTO_UPDATE:-0}" = "1" ]; then
STAMP="$HOME/.hermes/.last_auto_update.json"
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

fi

if [ -n "$problems" ]; then
  notify "系统链异常：${problems}。请查 daily_watchdog.log / skill_evolution.log / evolution-health.json"
  exit 0  # 不红，防 launchd 无脑重跑
fi

# Reset the active fingerprint after recovery so a later recurrence is notified.
/usr/bin/python3 - "${ALERT_STATE:-$HOME/.hermes/logs/memory-alert-state.json}" <<'PYRECOVER'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
if p.exists():
    data = json.loads(p.read_text())
    data.pop('delivered_fingerprint', None)
    data.pop('attempt_fingerprint', None)
    p.write_text(json.dumps(data))
PYRECOVER
log "all chains healthy: daily and weekly checks OK"
exit 0
