#!/bin/bash
# 每日 23:50 总结 - 由 cron 调用
# 写今日 daily 总结 + 跑后处理 + 报告状态

set -e
VAULT="${HERMES_VAULT:-$HOME/Documents/HermesMemory}"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H:%M)

# ============ 1. 今日 daily 总结（仅首次）============
DAILY_FILE="$VAULT/daily/${DATE}-每日总结.md"
if [ ! -f "$DAILY_FILE" ]; then
  TOTAL=$(find "$VAULT" -name "*.md" -not -path "*.obsidian*" -not -path "*.checkpoints*" 2>/dev/null | wc -l | tr -d ' ')
  PROJ=$(find "$VAULT/projects" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  PREF=$(find "$VAULT/preferences" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
  INC=$(find "$VAULT/incidents" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
  ERR=$(python3 -c "import json; d=json.loads(open('$VAULT/.checkpoints/errors.json').read()) if __import__('os').path.exists('$VAULT/.checkpoints/errors.json') else []; print(len(d))" 2>/dev/null || echo 0)

  cat > "$DAILY_FILE" <<EOF
# $DATE 每日总结

> **生成时间**：$TIME
> **类型**：cron 自动生成

## 📊 今日归档统计

- 总文件：$TOTAL
- 项目：$PROJ
- 偏好：$PREF
- 踩坑：$INC
- 错误记录：$ERR

## 🆕 今日新增

$(find "$VAULT" -name "${DATE}-*.md" -not -path "*.obsidian*" 2>/dev/null | head -20)

---
_由 cron 每日 23:50 自动生成_
EOF
  echo "✅ 写 daily 总结: $DAILY_FILE"
else
  echo "⏭️ 今日 daily 已存在，跳过"
fi

# 2. 跑后处理
python3 "$HOME/.hermes/scripts/vault_postprocess.py" 2>&1 | tail -8

# 2.5 扫描 learnings 高频项（自我提升）
python3 "$HOME/.hermes/scripts/scan_learnings.py" 2>&1 | tail -15

# ============ 3. hook 状态 ============
echo ""
echo "=== 系统状态 ==="
$HOME/.hermes/scripts/auto_archive_hook.sh status
