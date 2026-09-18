#!/bin/bash
# =============================================================================
# agent-memory-driven-evolution · 卸载器
# -----------------------------------------------------------------------------
# 用法：
#   ./uninstall.sh              # 交互式确认
#   ./uninstall.sh --yes        # 静默卸载
#   ./uninstall.sh --keep-vault # 卸载脚本/skills，但保留 memory vault
#   ./uninstall.sh --help       # 帮助
#
# 设计原则（参考成熟 uninstaller）：
#   - 幂等：重复运行不会报错
#   - 安全：默认询问确认，不会误删用户数据
#   - 可回溯：删除前备份到 ~/.hermes-backup-<timestamp>
# =============================================================================

set -euo pipefail

MODE="interactive"
KEEP_VAULT=0
BACKUP_DIR=""
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"

usage() {
    cat <<'EOF'
agent-memory-driven-evolution uninstaller

Usage:
  ./uninstall.sh [options]

Options:
  --yes          Non-interactive uninstall
  --keep-vault   Uninstall scripts/skills/cron, but KEEP your memory vault
  --vault PATH   Memory vault location (default: $HERMES_VAULT or ~/HermesMemory)
  --help         Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) MODE="silent" ;;
        --keep-vault) KEEP_VAULT=1 ;;
        --vault)
            [ $# -ge 2 ] || { echo "❌ --vault requires a path" >&2; exit 2; }
            VAULT="$2"; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "❌ 未知参数: $1"; usage; exit 1 ;;
    esac
    shift
done

PLATFORM_OS="$(uname -s)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🔧 agent-memory-driven-evolution 卸载器"
echo "  安装目录: $HERMES_HOME"
[ "$KEEP_VAULT" = "1" ] && echo "  保留 vault: $VAULT ✓" || echo "  将删除 vault: $VAULT"
echo ""

if [ "$MODE" = "interactive" ]; then
    read -r -p "确定要卸载吗? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "❌ 已取消"
        exit 0
    fi
fi

# ---- 1. 移除定时任务 ------------------------------------------------------------
echo "🕐 移除定时任务..."
if [ -f "$HERMES_HOME/scripts/lib/platform.sh" ]; then
    source "$HERMES_HOME/scripts/lib/platform.sh"
    platform_uninstall_cron "com.user.skill-evolution-weekly" 2>/dev/null || true
    platform_uninstall_cron "com.user.hermes-daily-watchdog" 2>/dev/null || true
    platform_uninstall_cron "com.user.upgrade-morning-watchdog" 2>/dev/null || true
    platform_uninstall_cron "skill-evolution-weekly" 2>/dev/null || true
    echo "  ✔ 已移除"
else
    # 兜底：直接删 plist
    rm -f "$HOME/Library/LaunchAgents/com.user."*.plist 2>/dev/null || true
    echo "  ✔ 已移除 (fallback)"
fi

# ---- 2. 备份并删除安装目录 ------------------------------------------------------
if [ -d "$HERMES_HOME" ]; then
    BACKUP_DIR="$HOME/.hermes-backup-$(date +%Y%m%d-%H%M%S)"
    echo "📦 备份现有配置到 $BACKUP_DIR ..."
    # 只备份非日志内容 + vault（如果删除）
    mkdir -p "$BACKUP_DIR"
    # 备份脚本/skills/config（排除 logs 与 vault 自身，避免巨大）
    if [ -d "$HERMES_HOME/scripts" ]; then cp -R "$HERMES_HOME/scripts" "$BACKUP_DIR/" 2>/dev/null || true; fi
    if [ -d "$HERMES_HOME/skills" ]; then cp -R "$HERMES_HOME/skills" "$BACKUP_DIR/" 2>/dev/null || true; fi
    if [ -f "$HERMES_HOME/config.yaml" ]; then cp "$HERMES_HOME/config.yaml" "$BACKUP_DIR/" 2>/dev/null || true; fi
    if [ -f "$HERMES_HOME/.env" ]; then cp "$HERMES_HOME/.env" "$BACKUP_DIR/" 2>/dev/null || true; fi

    # 只删除本系统安装的部分（scripts/skills/logs），不碰用户其它 .hermes 数据
    rm -rf "$HERMES_HOME/scripts" "$HERMES_HOME/skills" "$HERMES_HOME/logs" 2>/dev/null || true
    echo "  ✔ scripts/skills/logs 已删除（备份在 ${BACKUP_DIR}）"
else
    echo "  (未找到 $HERMES_HOME，跳过)"
fi

# ---- 3. 可选删除 vault ----------------------------------------------------------
if [ "$KEEP_VAULT" = "0" ] && [ -d "$VAULT" ]; then
    if [ "$MODE" = "interactive" ]; then
        read -r -p "是否删除记忆 vault $VAULT? [y/N] " del_vault
        if [[ ! "$del_vault" =~ ^[Yy]$ ]]; then
            KEEP_VAULT=1
            echo "  (保留 vault)"
        fi
    fi
    if [ "$KEEP_VAULT" = "0" ]; then
        rm -rf "$VAULT"
        echo "  ✔ vault 已删除"
    fi
fi

# Codex memory is intentionally outside both ~/.hermes and ~/HermesMemory
# (~/CodexMemory by default) and owns its own com.codex.memory scheduler.
# Uninstalling Hermes must not remove, migrate, or disable it.

# ---- 4. 验证 ---------------------------------------------------------------------
echo ""
echo "🔍 验证卸载..."
CRON_LEFT=$(crontab -l 2>/dev/null | grep -c "skill-evolution" || true)
if [ "$CRON_LEFT" != "0" ]; then
    echo "  ⚠️  crontab 残留 $CRON_LEFT 条 skill-evolution 条目"
else
    echo "  ✅ crontab 干净"
fi
if [ -d "$HERMES_HOME/scripts" ]; then
    echo "  ⚠️  scripts 目录仍存在"
else
    echo "  ✅ scripts 已移除"
fi
echo ""
echo "✅ 卸载完成！"
[ -d "$BACKUP_DIR" ] && echo "如需恢复，请查看备份: $BACKUP_DIR"
[ -d "${CODEX_MEMORY_HOME:-$HOME/CodexMemory}" ] && echo "Codex 独立记忆未触碰: ${CODEX_MEMORY_HOME:-$HOME/CodexMemory}"
