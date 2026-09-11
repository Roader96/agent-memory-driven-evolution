#!/bin/bash
# 热记忆看门狗：直接 wc -m 扫真实文件。不依赖 .env 死数字，不依赖 agent 记性。
# no_agent cron 用：正常静默（空 stdout）。
# 超载不再告警轰炸，改写标记文件让 agent 自行迁移压缩。

HOT="${HERMES_HOME:-$HOME/.hermes}/memories/MEMORY.md"
LIMIT=2200
WARN=1500
URGENT=1800
MARKER="${HERMES_HOME:-$HOME/.hermes}/data/.memory_overload_pending"

if [ ! -f "$HOT" ]; then
  exit 0
fi

USED=$(wc -m < "$HOT" 2>/dev/null | tr -d ' ')

if [ -z "$USED" ] || ! [[ "$USED" =~ ^[0-9]+$ ]]; then
  exit 0
fi

if [ "$USED" -ge "$URGENT" ]; then
  # 接近上限才写标记文件（agent 下次会话看到就自行迁移低频项），stdout 保持静默不推告警
  mkdir -p "$(dirname "$MARKER")"
  echo "${USED}/${LIMIT} $(date '+%Y-%m-%d %H:%M:%S')" > "$MARKER"
else
  # 恢复正常则清标记
  rm -f "$MARKER"
fi
exit 0
