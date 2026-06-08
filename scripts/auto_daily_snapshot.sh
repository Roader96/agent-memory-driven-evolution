#!/bin/bash
# 每日会话快照 - 记录今天聊了什么关键内容
# 用法: 由我（Hermes）在每日首次对话结束自动调用

VAULT="${HERMES_VAULT:-$HOME/Documents/HermesMemory}"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H:%M)
FILE="$VAULT/daily/$DATE-会话摘要.md"

# 如已存在则追加
if [ -f "$FILE" ]; then
  echo "" >> "$FILE"
  echo "## $TIME 续" >> "$FILE"
  echo "" >> "$FILE"
  echo "- （会话进行中...）" >> "$FILE"
else
  cat > "$FILE" <<EOF
# $DATE 会话摘要

> **首条时间**：$TIME
> **分类**：daily

## 今日要点

EOF
fi

echo "✅ 日快照已更新: $FILE"
