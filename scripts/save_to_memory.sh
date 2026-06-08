#!/bin/bash
# 归档对话到 Hermes 冷记忆
# 用法: save_to_memory.sh <分类> <标题> [内容]
# 分类: daily / projects / preferences / incidents

set -e
VAULT="${HERMES_VAULT:-$HOME/Documents/HermesMemory}"
CATEGORY="${1:?用法: save_to_memory.sh <daily|projects|preferences|incidents> <标题> [内容]}"
TITLE="${2:?缺少标题}"
DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y-%m-%d_%H:%M)

# 文件名：日期-标题.md
SAFE_TITLE=$(echo "$TITLE" | tr ' ' '-' | tr -cd '[:alnum:]-_中文')
FILENAME="${DATE}-${SAFE_TITLE}.md"
FILEPATH="$VAULT/$CATEGORY/$FILENAME"

# 写入模板
cat > "$FILEPATH" <<EOF
# $TITLE

> **归档时间**：$TIMESTAMP
> **分类**：$CATEGORY

## 上下文

${3:-（无附加内容）}

## 关键要点

-

## 相关链接

- [[INDEX|📑 记忆索引]]
EOF

echo "✅ 已归档: $FILEPATH"
open -a Obsidian "$FILEPATH" 2>/dev/null && echo "📖 已在 Obsidian 中打开" || echo "💡 提示：用 Obsidian 打开 $VAULT 即可"
