#!/bin/bash
# 智能归档 v2 - 由调用方提供项目标签，脚本只负责写入
# 用法: smart_archive.sh <标题> <内容> [项目标签]
# 项目标签: 留空=自动归到 daily
#          "preferences" | "incidents" | "<项目名>"
# 改进: 项目名由我（Hermes）从上下文识别后传入，更准

set -e
VAULT="${HERMES_VAULT:-$HOME/Documents/HermesMemory}"
TITLE="${1:?用法: smart_archive.sh <标题> <内容> [标签]}"
CONTENT="${2:-（无内容）}"
TAG="${3:-}"

DATE=$(date +%Y-%m-%d)
TIME=$(date +%H:%M)
TIMESTAMP=$(date +%Y-%m-%d_%H:%M:%S)

# ============ 分类决策 ============
resolve_category() {
  local tag="$1"
  local text="$2"

  # 显式标签优先（强保留，绝不丢给项目归并）
  case "$tag" in
    "preferences"|"incidents"|"daily")
      echo "$tag"
      return
      ;;
    "")
      # 检查文本是否提到已有项目名（兜底）
      if [ -d "$VAULT/projects" ]; then
        for existing in "$VAULT/projects"/*/; do
          [ -d "$existing" ] || continue
          local proj_name=$(basename "$existing")
          local short=$(echo "$proj_name" | sed 's/[:： ]//g' | cut -c1-4)
          if [ -n "$short" ] && echo "$text" | grep -qF "$short"; then
            echo "projects/$proj_name"
            return
          fi
        done
      fi
      # 启发式：含偏好/坑/项目/工具关键词
      if echo "$text" | grep -qiE "我喜欢|我的偏好|我习惯|我从不|我总是|preference|我以后"; then
        echo "preferences"
        return
      fi
      if echo "$text" | grep -qiE "出错了|失败了|报错|解决|修复|踩坑|bug"; then
        echo "incidents"
        return
      fi
      echo "daily"
      ;;
    *)
      # 任何其他标签都当项目名
      echo "projects/$tag"
      ;;
  esac
}

CATEGORY=$(resolve_category "$TAG" "$TITLE $CONTENT")

# ============ 建目录 ============
if [[ "$CATEGORY" == projects/* ]]; then
  PROJ_NAME="${CATEGORY#projects/}"
  mkdir -p "$VAULT/projects/$PROJ_NAME"
  FULL_DIR="$VAULT/projects/$PROJ_NAME"
else
  mkdir -p "$VAULT/$CATEGORY"
  FULL_DIR="$VAULT/$CATEGORY"
fi

# ============ 文件名 ============
SAFE_TITLE=$(echo "$TITLE" | tr ' ' '-' | tr -cd '[:alnum:]-_中文' | cut -c1-50)
FILENAME="${DATE}-${SAFE_TITLE}.md"
FILEPATH="$FULL_DIR/$FILENAME"

# ============ 写入 ============
cat > "$FILEPATH" <<EOF
# $TITLE

> **归档时间**：$TIMESTAMP
> **分类**：$CATEGORY
> **触发**：smart_archive

## 内容

$CONTENT

## 关键要点

EOF

echo "✅ $FILEPATH"
[ -d "$VAULT/$CATEGORY" ] && echo "📂 分类目录: $CATEGORY"

# 归档后自动跑后处理（反向链接 + 时间线 + INDEX）
if [ -f "$HOME/.hermes/scripts/vault_postprocess.py" ]; then
  python3 "$HOME/.hermes/scripts/vault_postprocess.py" 2>&1 | tail -5
fi
