#!/bin/bash
# 关键词召回 Hermes 冷记忆
# 用法: recall.sh <关键词>

VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
KEYWORD="${1:?用法: recall.sh <关键词>}"

echo "🔍 搜索: $KEYWORD"
echo "📂 范围: $VAULT"
echo "---"

# 用 grep 搜标题和内容
grep -rli "$KEYWORD" "$VAULT" 2>/dev/null | while read -r file; do
  # 提取标题
  title=$(head -1 "$file" | sed 's/^# //')
  # 提取匹配行（带前后 1 行上下文）
  match=$(grep -n -A1 -B1 "$KEYWORD" "$file" 2>/dev/null | head -5 | tr '\n' ' ')
  echo "📄 $title"
  echo "   路径: ${file#$VAULT/}"
  echo "   摘要: $match..."
  echo ""
done

echo "---"
echo "💡 在 Obsidian 中按 Cmd+Shift+F 全局搜索更强大"
