#!/bin/bash
# 实时存档钩子 - 每次对话后评估是否要存
# 触发: 每 5 轮 / 每 30 分钟 / 热记忆 > 1500 字符
# 用法: 由 Hermes 在每次工具调用后判断调用

VAULT="${HERMES_VAULT:-$HOME/Documents/HermesMemory}"
HOT_MEM="$HOME/.hermes/memory/"
CHECKPOINT_DIR="$VAULT/.checkpoints"
mkdir -p "$CHECKPOINT_DIR"

ACTION="${1:-check}"  # check | snapshot | alert
TURN_COUNT_FILE="$CHECKPOINT_DIR/turn_count"
LAST_SNAPSHOT_FILE="$CHECKPOINT_DIR/last_snapshot"
LAST_MIGRATION_FILE="$CHECKPOINT_DIR/last_migration"

LAST_SNAPSHOT=$(cat "$LAST_SNAPSHOT_FILE" 2>/dev/null || echo 0)
LAST_MIGRATION=$(cat "$LAST_MIGRATION_FILE" 2>/dev/null || echo 0)
TURN_COUNT=$(cat "$TURN_COUNT_FILE" 2>/dev/null || echo 0)

# ============ 热记忆用量检查 ============
# 优先读 .env 里 HERMES_HOT_USED（由 update_hot_used.sh 维护）
# 兜底：算 ~/.hermes/.skills_prompt_snapshot.json 大小
check_hot_memory() {
  local used=0
  local env_used=$(grep "^HERMES_HOT_USED=" "$HOME/.hermes/.env" 2>/dev/null | cut -d= -f2)
  if [ -n "$env_used" ] && [ "$env_used" -gt 0 ] 2>/dev/null; then
    used=$env_used
  else
    local snap="$HOME/.hermes/.skills_prompt_snapshot.json"
    if [ -f "$snap" ]; then
      local snap_size=$(stat -f%z "$snap" 2>/dev/null || echo 0)
      # 粗略换算：热记忆段 ≈ snapshot 的 15%
      used=$((snap_size * 15 / 100))
    fi
  fi
  local pct=$((used * 100 / 2200))
  echo "$used $pct"
}

HOT_USED=$(check_hot_memory | awk '{print $1}')
HOT_PCT=$(check_hot_memory | awk '{print $2}')

NOW=$(date +%s)

case "$ACTION" in
  check)
    # 每次调用都做检查并递增轮次
    TURN_COUNT=$((TURN_COUNT + 1))
    echo "$TURN_COUNT" > "$TURN_COUNT_FILE"

    SINCE_SNAP=$((NOW - LAST_SNAPSHOT))
    SINCE_MIGRATE=$((NOW - LAST_MIGRATION))

    # 触发 1: 每 5 轮
    if [ $((TURN_COUNT % 5)) -eq 0 ]; then
      echo "🔔 触发: 每 5 轮快照 (轮次 $TURN_COUNT)"
      echo "$NOW" > "$LAST_SNAPSHOT_FILE"
      echo "snapshot_5turn"
      exit 0
    fi

    # 触发 2: 每 30 分钟
    if [ "$LAST_SNAPSHOT" -eq 0 ] || [ $SINCE_SNAP -ge 1800 ]; then
      echo "🔔 触发: 30 分钟定时快照 (距上次 ${SINCE_SNAP}s)"
      echo "$NOW" > "$LAST_SNAPSHOT_FILE"
      echo "snapshot_30min"
      exit 0
    fi

    # 触发 3: 热记忆 > 1500 字符（68%）
    if [ "$HOT_USED" -gt 1500 ]; then
      echo "⚠️ 触发: 热记忆 ${HOT_USED}/2200 (${HOT_PCT}%) — 需迁移"
      echo "$NOW" > "$LAST_MIGRATION_FILE"
      echo "migrate_hot"
      exit 0
    fi

    # 触发 4: 热记忆 > 1800 字符（82%）紧急
    if [ "$HOT_USED" -gt 1800 ]; then
      echo "🚨 紧急: 热记忆 ${HOT_USED}/2200 (${HOT_PCT}%) — 立即迁移"
      echo "$NOW" > "$LAST_MIGRATION_FILE"
      echo "urgent_migrate"
      exit 0
    fi

    # 没事
    echo "✅ 正常 (轮次 $TURN_COUNT, 热记忆 ${HOT_PCT}%, 距上次快照 ${SINCE_SNAP}s)"
    ;;

  status)
    echo "📊 状态面板"
    echo "  轮次: $TURN_COUNT"
    echo "  热记忆: ${HOT_USED}/2200 (${HOT_PCT}%)"
    echo "  上次快照: $(date -r $LAST_SNAPSHOT '+%H:%M:%S' 2>/dev/null || echo '从未')"
    echo "  下次触发:"
    echo "    - 5 轮: 第 $(((TURN_COUNT / 5 + 1) * 5)) 轮"
    echo "    - 30min: $(date -r $((LAST_SNAPSHOT + 1800)) '+%H:%M:%S' 2>/dev/null)"
    ;;
esac
