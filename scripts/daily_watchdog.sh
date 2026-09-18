#!/bin/bash
# daily_watchdog.sh — 每日 23:55 唯一生成入口（launchd，零常驻）
#
# 直接跑 daily_summary_from_db.py（读 state.db 全量会话 → 证据版写盘 →
# 模型润色 → 覆盖门禁 → 飞书一条）。不再依赖会 broken pipe/超时的
# agent cron，也不依赖白天「自觉归档」。
#
# 可靠性：
#  - 生成失败重试 3 次；脚本内部润色挂了会自动降级证据版（仍有实质内容）
#  - 飞书发送失败 → 只写日志（macOS 弹窗已移除 2026-09-17）
#  - 睡眠错过 → launchd 唤醒补跑；脚本自己保证幂等（重跑覆盖当天）
#  - 顺手静默回填最近 3 天缺失的 daily（不推送）

set -u
VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
LOG="$HOME/.hermes/logs/daily_watchdog.log"
SCRIPT="${HERMES_HOME:-$HOME/.hermes}/scripts/daily_summary_from_db.py"
FEISHU="$HOME/.hermes/scripts/send_feishu_dm.py"
mkdir -p "$HOME/.hermes/logs"

# 测试/隔离环境检测：HOME 不是真实用户目录（如 mktemp /tmp /var/folders）→ 静默跑，不弹系统通知
if [ "${WATCHDOG_SILENT:-0}" = "1" ] || [ -n "${HERMES_VAULT_TEST:-}" ] || \
   case "$HOME" in /var/folders/*|/tmp/*|/private/tmp/*) true;; *) false;; esac; then
  SILENT=1
else
  SILENT=0
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

notify() {
  [ "$SILENT" = "1" ] && { log "notify(静默): $1"; return 0; }
  # ① 飞书告警（最高优先，用户手机能看到；没配飞书则静默跳过）
  [ -x "$FEISHU" ] && /usr/bin/python3 "$FEISHU" "⚠️ Hermes 每日总结异常：$1（日志：$LOG）" >> "$LOG" 2>&1 || true
  # ② macOS 弹窗已移除（2026-09-17），只留飞书
}

TODAY=$(date +%Y-%m-%d)
log "===== watchdog run (today=$TODAY) ====="

# ---- 0. 静默回填最近 7 天缺失的 daily（睡眠/关机/失败漏跑都兜住）----
for back in 1 2 3 4 5 6 7; do
  D=$(date -v-"${back}"d +%Y-%m-%d 2>/dev/null) || continue
  F="$VAULT/daily/${D}-每日总结.md"
  if [ ! -s "$F" ]; then
    log "backfill missing daily: $D"
    DATE_OVERRIDE="$D" NO_LLM=1 /usr/bin/python3 "$SCRIPT" >> "$LOG" 2>&1 \
      && log "backfill OK $D" || log "backfill FAILED $D"
  fi
done

# ---- 1. 生成今天（含润色）；静默写 OB，重试 3 次 ----
# 想临时推送：PUSH_FEISHU=1 手动跑脚本即可
ok=0
for try in 1 2 3; do
  log "generate attempt $try"
  if /usr/bin/python3 "$SCRIPT" >> "$LOG" 2>&1; then
    ok=1
    break
  fi
  log "attempt $try failed, retry in 10s"
  sleep 10
done

DAILY="$VAULT/daily/${TODAY}-每日总结.md"
if [ "$ok" = "1" ] && [ -s "$DAILY" ]; then
  log "daily OK: $DAILY ($(wc -c < "$DAILY" | tr -d ' ') bytes)"
else
  log "FATAL: daily generation failed after 3 tries"
  notify "每日总结连续3次生成失败，查 $LOG"
  exit 1
fi

# ---- 2. vault 后处理（反向链接/TIMELINE/INDEX），失败不杀主流程 ----
/usr/bin/python3 "$HOME/.hermes/scripts/vault_postprocess.py" >> "$LOG" 2>&1 \
  || log "WARN: vault_postprocess failed (不影响 daily)"
[ -f "$HOME/.hermes/scripts/scan_learnings.py" ] && \
  /usr/bin/python3 "$HOME/.hermes/scripts/scan_learnings.py" >> "$LOG" 2>&1 \
  || true

# ---- 2.5 每日成长扫描 ----
/usr/bin/python3 "$HOME/.hermes/scripts/skill_evolution/daily_growth_check.py" >> "$LOG" 2>&1 \
  || log "WARN: daily_growth_check failed (不影响 daily)"

# ---- 3. 内容门禁（防空壳）：必须有实质段落且超过 600 字节 ----
if ! grep -q "今日实际工作" "$DAILY" || [ "$(wc -c < "$DAILY" | tr -d ' ')" -lt 600 ]; then
  log "FATAL: daily content gate failed (空壳?)"
  notify "每日总结内容门禁未过，疑似空壳"
  exit 1
fi

# ---- 4. 成长门禁：每日总结必须含"自我审视"段（正向成长主航道）----
if ! grep -q "自我审视" "$DAILY"; then
  log "FATAL: growth gate failed (缺自我审视段)"
  notify "每日总结缺自我审视段，成长门禁未过"
  exit 1
fi
log "成长门禁 OK：自省段已生成"

# Codex structured memory has its own com.codex.memory scheduler and is intentionally
# not invoked by the Hermes watchdog, keeping the two memory systems decoupled.

log "watchdog done OK"
