#!/usr/bin/env bash
# Codex standalone memory maintenance wrapper.
# Installed at <codex-memory-home>/run_maintenance.sh and works after Hermes
# and ~/HermesMemory have been removed.
set -euo pipefail

export TZ="${TZ:-Asia/Shanghai}"

CODEX_MEMORY_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
MAINT="$CODEX_MEMORY_HOME/bin/codex_memory_maintenance.sh"
LOG="$CODEX_MEMORY_HOME/maintenance.log"
STAMP="$(date '+%Y-%m-%d %H:%M:%S %z')"
TODAY="$(date '+%Y-%m-%d')"
TODAY_FILE="$CODEX_MEMORY_HOME/daily/${TODAY}-maintenance.md"

mkdir -p "$CODEX_MEMORY_HOME/daily"

log() { printf '%s %s\n' "$STAMP" "$*" >> "$LOG"; }

if [[ ! -x "$MAINT" ]]; then
  log "FAIL standalone maintenance script missing: $MAINT"
  exit 1
fi

if ! CODEX_MEMORY_HOME="$CODEX_MEMORY_HOME" \
     CODEX_HOME="$CODEX_ROOT" \
     "$MAINT" >> "$LOG" 2>&1; then
  log "FAIL structured Codex archive"
  exit 1
fi

for required in INDEX.md OPEN-ITEMS.md DECISIONS.md; do
  if [[ ! -s "$CODEX_MEMORY_HOME/$required" ]]; then
    log "FAIL missing generated $required"
    exit 1
  fi
done
if [[ ! -f "$CODEX_MEMORY_HOME/.index/sessions.jsonl" ]]; then
  log "FAIL missing generated .index/sessions.jsonl"
  exit 1
fi

if [[ ! -e "$TODAY_FILE" ]]; then
  tmp="${TODAY_FILE}.tmp.$$"
  {
    printf '# Codex 记忆维护\n\n'
    printf -- '- 执行时间：%s\n' "$STAMP"
    printf -- '- 检查结果：结构化会话卡、索引已生成\n'
    printf -- '- 运行模式：独立 CodexMemory，不依赖 Hermes 或 HermesMemory\n'
  } > "$tmp"
  mv -n "$tmp" "$TODAY_FILE"
fi

log "OK codex structured memory maintenance"

# Semantic inference is opt-in and offline. Failure must be visible without
# invalidating the successfully retained keyword archive.
if [[ -f "$CODEX_MEMORY_HOME/models/multilingual-e5-small/model-provenance.json" ]]; then
  if "$CODEX_MEMORY_HOME/.runtime/bin/python" "$CODEX_MEMORY_HOME/bin/codex_semantic.py" \
       build --memory-home "$CODEX_MEMORY_HOME" >> "$LOG" 2>&1; then
    log "OK offline semantic index"
  else
    log "WARN offline semantic index failed; keyword archive remains available"
    "${PYTHON_BIN:-/usr/bin/python3}" - "$CODEX_MEMORY_HOME/.index/semantic-health.json" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
p = Path(sys.argv[1])
tmp = p.with_suffix('.error.tmp')
tmp.write_text(json.dumps({'status':'error', 'checked_at':datetime.now(timezone.utc).isoformat(),
    'reason':'Offline embedding build failed; see maintenance.log'}))
tmp.replace(p)
PY
  fi
fi
