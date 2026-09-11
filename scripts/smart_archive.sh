#!/bin/bash
# 智能归档 v2 - 由调用方提供项目标签，脚本只负责写入
# 用法: smart_archive.sh <标题> <内容> [项目标签]
# 项目标签: 留空=自动归到 daily
#          "preferences" | "incidents" | "<项目名>"
# 改进: 项目名由我（Hermes）从上下文识别后传入，更准

set -e
VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
TITLE="${1:?用法: smart_archive.sh <标题> <内容> [标签]}"
CONTENT="${2:-（无内容）}"
TAG="${3:-}"

DATE=$(date +%Y-%m-%d)
TIME=$(date +%H:%M)
TIMESTAMP=$(date +%Y-%m-%d_%H:%M:%S)

# ============ 强制检查：必须有摘要 ============
if ! echo "$CONTENT" | grep -q "^## 摘要"; then
  echo "❌ 拒绝归档：内容必须有「## 摘要」段落"
  echo ""
  echo "正确格式："
  echo "## 摘要"
  echo "一句话说清楚：完成了什么 + 产出了什么。"
  echo ""
  echo "## 完成内容"
  echo "具体做了什么..."
  echo ""
  echo "## 产出物"
  echo "可交付的文件/代码/报告路径..."
  exit 1
fi

# 检查摘要是否有实质内容（至少10个字符）
SUMMARY=$(echo "$CONTENT" | sed -n '/^## 摘要/,/^##/p' | sed '1d;$d' | tr -d '[:space:]')
if [ ${#SUMMARY} -lt 10 ]; then
  echo "❌ 拒绝归档：摘要太短（至少10个字符）"
  echo "摘要要一句话说清楚：完成了什么 + 产出了什么"
  exit 1
fi

# ============ 安全：TAG 白名单净化（防目录穿越）============
# 禁 /、\、..、控制字符；只保留字母数字、中文、-、_
TAG=$(TAG_SRC="$TAG" python3 -c '
import os, re
tag = os.environ.get("TAG_SRC", "").strip()
# 路径字符/穿越直接清空（拒绝服务式输入降级为自动分类，不报错中断归档）
if any(x in tag for x in ("/", "\\", "..", "\x00")) or tag.startswith("."):
    print(""); raise SystemExit(0)
tag = re.sub(r"[^\w\u4e00-\u9fff-]", "", tag, flags=re.UNICODE)
print(tag[:50])
')

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
# 用 python3 净化（跨 locale 稳：tr 的 [:alnum:]-_中文 在 C locale 下会断字乱码）
SAFE_TITLE=$(TITLE_SRC="$TITLE" python3 -c '
import os, re, unicodedata
s = os.environ["TITLE_SRC"]
s = s.replace(" ", "-")
# 只保留 CJK、字母、数字、-、_，其余替换为 -
s = re.sub(r"[^\w\u4e00-\u9fff-]", "-", s, flags=re.UNICODE)
s = s.strip("-").strip()
print(s[:50])
')
# 净化后为空（如纯特殊字符标题）→ 兜底用时间戳，避免空文件名
[ -z "$SAFE_TITLE" ] && SAFE_TITLE="untitled-$(date +%H%M%S)"
FILENAME="${DATE}-${SAFE_TITLE}.md"
FILEPATH="$FULL_DIR/$FILENAME"

# ============ 安全：resolve 校验最终路径必须在 vault 内 ============
if ! VAULT="$VAULT" FINAL_PATH="$FILEPATH" python3 -c '
import os, sys
from pathlib import Path
vault = Path(os.environ["VAULT"]).resolve()
final = Path(os.environ["FINAL_PATH"]).resolve()
sys.exit(0 if str(final).startswith(str(vault) + os.sep) else 1)
'; then
  echo "❌ 拒绝归档：目标路径逃出 vault（$FILEPATH）" >&2
  exit 1
fi

# ============ 同名不覆盖（零丢失硬规则）============
# 已存在则追加 -HHMMSS；再撞加随机后缀（并发归档兜底）
if [ -f "$FILEPATH" ]; then
  FILEPATH="$FULL_DIR/${DATE}-${SAFE_TITLE}-$(date +%H%M%S).md"
fi
while [ -f "$FILEPATH" ]; do
  FILEPATH="$FULL_DIR/${DATE}-${SAFE_TITLE}-$(date +%H%M%S)-$RANDOM.md"
done
# 并发安全：noclobber 原子占位——同秒并发的多个进程都过了上面的检查，
# 只有占位成功者才拥有该文件名，失败者换随机名重试（防互相覆盖）
ATTEMPTS=0
while ! ( set -o noclobber; : > "$FILEPATH" ) 2>/dev/null; do
  ATTEMPTS=$((ATTEMPTS+1))
  [ "$ATTEMPTS" -gt 20 ] && { echo "❌ 并发占位失败（20 次）" >&2; exit 1; }
  FILEPATH="$FULL_DIR/${DATE}-${SAFE_TITLE}-$(date +%H%M%S)-$RANDOM$RANDOM.md"
done

# ============ 写入 ============
cat > "$FILEPATH" <<EOF
# $TITLE

> **归档时间**：$TIMESTAMP
> **分类**：$CATEGORY
> **触发**：smart_archive

$CONTENT
EOF

echo "✅ $FILEPATH"
[ -d "$VAULT/$CATEGORY" ] && echo "📂 分类目录: $CATEGORY"

# 归档后自动跑后处理（反向链接 + 时间线 + INDEX）
POSTPROCESS="${HERMES_HOME:-$HOME/.hermes}/scripts/vault_postprocess.py"
if [ -f "$POSTPROCESS" ]; then
  python3 "$POSTPROCESS" 2>&1 | tail -5
fi
