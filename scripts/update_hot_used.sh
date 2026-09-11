#!/bin/bash
# 手动更新热记忆用量计数器（每次 Hermes 写 memory 后调用）
# 用法: update_hot_used.sh <当前USER_PROFILE+memory总字符数>

USED="${1:?用法: update_hot_used.sh <字符数>}"
ENV_FILE="$HOME/.hermes/.env"

# 用 sed 更新或追加
if grep -q "^HERMES_HOT_USED=" "$ENV_FILE" 2>/dev/null; then
  sed -i '' "s/^HERMES_HOT_USED=.*/HERMES_HOT_USED=$USED/" "$ENV_FILE"
else
  echo "HERMES_HOT_USED=$USED" >> "$ENV_FILE"
fi

# 计算百分比
PCT=$((USED * 100 / 2200))
echo "📊 热记忆: $USED/2200 (${PCT}%)"

# 自动告警
if [ "$USED" -gt 1800 ]; then
  echo "🚨 紧急: >1800 字符，立即迁移低频项"
elif [ "$USED" -gt 1500 ]; then
  echo "⚠️  警告: >1500 字符，建议迁移"
fi
