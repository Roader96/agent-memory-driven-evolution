#!/usr/bin/env bash
# Codex standalone memory maintenance wrapper.
# Installed at <vault>/codex/run_maintenance.sh; it must work after Hermes
# (~/.hermes) has been removed.
set -euo pipefail

export TZ="${TZ:-Asia/Shanghai}"

CODEX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT="${HERMES_VAULT:-$(dirname "$CODEX_DIR")}"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
MAINT="$CODEX_DIR/bin/codex_memory_maintenance.sh"
LOG="$CODEX_DIR/maintenance.log"
STAMP="$(date '+%Y-%m-%d %H:%M:%S %z')"
TODAY="$(date '+%Y-%m-%d')"
TODAY_FILE="$CODEX_DIR/daily/${TODAY}-maintenance.md"

mkdir -p "$CODEX_DIR/daily"

log() { printf '%s %s\n' "$STAMP" "$*" >> "$LOG"; }

if [[ ! -d "$CODEX_DIR" ]]; then
  exit 1
fi
if [[ ! -x "$MAINT" ]]; then
  log "FAIL standalone maintenance script missing: $MAINT"
  exit 1
fi

if ! CODEX_MEMORY_HOME="$CODEX_DIR" \
     HERMES_VAULT="$VAULT" \
     CODEX_HOME="$CODEX_ROOT" \
     "$MAINT" >> "$LOG" 2>&1; then
  log "FAIL structured Codex archive"
  exit 1
fi

for required in INDEX.md OPEN-ITEMS.md DECISIONS.md; do
  if [[ ! -s "$CODEX_DIR/$required" ]]; then
    log "FAIL missing generated $required"
    exit 1
  fi
done
if [[ ! -f "$CODEX_DIR/.index/sessions.jsonl" ]]; then
  log "FAIL missing generated .index/sessions.jsonl"
  exit 1
fi

if [[ ! -e "$TODAY_FILE" ]]; then
  tmp="${TODAY_FILE}.tmp.$$"
  {
    printf '# Codex 记忆维护\n\n'
    printf -- '- 执行时间：%s\n' "$STAMP"
    printf -- '- 检查结果：结构化会话卡、索引和命名空间已生成\n'
    printf -- '- 运行模式：独立 Codex 维护，不依赖 ~/.hermes\n'
  } > "$tmp"
  mv -n "$tmp" "$TODAY_FILE"
fi

log "OK codex structured memory maintenance"
