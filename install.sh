#!/bin/bash
# =============================================================================
# agent-memory-driven-evolution · 安装器
# -----------------------------------------------------------------------------
# 用法：
#   ./install.sh                 # 安装到 ~/.hermes（交互式确认）
#   ./install.sh --yes           # 静默安装（CI / 脚本友好）
#   ./install.sh --vault <path>  # 指定 HermesMemory vault 位置（默认 ~/HermesMemory）
#   ./install.sh --help          # 帮助
#
# 支持平台：macOS 26+ / Linux (GNU coreutils)
# 参考成熟开源项目的安装器模式：一键安装 + 可卸载 + 幂等。
# =============================================================================

set -euo pipefail

# ---- 参数解析 ------------------------------------------------------------------
MODE="interactive"        # interactive / silent
VAULT_DEFAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
VAULT="$VAULT_DEFAULT"
SKIP_CRON=0

usage() {
    cat <<'EOF'
agent-memory-driven-evolution installer

Usage:
  ./install.sh [options]

Options:
  --yes          Non-interactive install (no confirmation prompts)
  --vault PATH   Set the memory vault location (default: ~/HermesMemory)
  --no-cron      Skip installing scheduled tasks (launchd/crontab)
  --help         Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) MODE="silent" ;;
        --vault) VAULT="$2"; shift ;;
        --no-cron) SKIP_CRON=1 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "❌ 未知参数: $1"; usage; exit 1 ;;
    esac
    shift
done

# ---- 平台检测 ------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_OS="$(uname -s)"

case "$PLATFORM_OS" in
    Darwin)  echo "✅ 检测到 macOS" ;;
    Linux)   echo "✅ 检测到 Linux" ;;
    *)
        echo "❌ 不支持的平台: $PLATFORM_OS（仅支持 macOS / Linux）"
        exit 1
        ;;
esac

# 检查依赖
for dep in bash python3 git; do
    if ! command -v "$dep" >/dev/null 2>&1; then
        echo "❌ 缺少依赖: $dep（请先安装）"
        exit 1
    fi
done
echo "✅ 依赖检查通过 (bash / python3 / git)"

# ---- 目标目录 ------------------------------------------------------------------
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SCRIPTS_DIR="$HERMES_HOME/scripts"
SKILLS_DIR="$HERMES_HOME/skills"
LOGS_DIR="$HERMES_HOME/logs"

echo ""
echo "📦 将安装到:"
echo "   脚本:   $SCRIPTS_DIR"
echo "   Skills: $SKILLS_DIR"
echo "   Vault:  $VAULT"
echo ""

if [ "$MODE" = "interactive" ]; then
    read -r -p "继续安装? [Y/n] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]] && [ -n "$confirm" ]; then
        echo "❌ 已取消"
        exit 1
    fi
fi

# ---- 安装 scripts -------------------------------------------------------------
echo ""
echo "📦 安装脚本..."
mkdir -p "$SCRIPTS_DIR" "$SKILLS_DIR" "$LOGS_DIR"
cp -R "$SCRIPT_DIR/scripts/". "$SCRIPTS_DIR/"
# 不要覆盖平台无关的 lib
chmod +x "$SCRIPTS_DIR"/*.sh "$SCRIPTS_DIR"/*.py 2>/dev/null || true

# ---- 安装 skills --------------------------------------------------------------
echo "📦 安装 skills..."
# 只安装 v2 版（roader-*），旧版 hermes-* 不装
for skill_dir in "$SCRIPT_DIR"/skills/roader-*/; do
    if [ -d "$skill_dir" ]; then
        # glob 展开带尾部斜杠，去掉它避免 cp 展开目录内容
        skill_dir="${skill_dir%/}"
        skill_name="$(basename "$skill_dir")"
        # 保留用户已存在的同名 skill（不覆盖用户修改）？—— 为幂等，覆盖前备份
        if [ -d "$SKILLS_DIR/$skill_name" ]; then
            mv "$SKILLS_DIR/$skill_name" "$SKILLS_DIR/$skill_name.bak-$(date +%Y%m%d-%H%M%S)"
        fi
        cp -R "$skill_dir" "$SKILLS_DIR/"
        echo "  ✔ $skill_name"
    fi
done

# ---- 创建 vault ---------------------------------------------------------------
if [ ! -d "$VAULT" ]; then
    echo "📦 创建 vault: $VAULT"
    mkdir -p "$VAULT"/{daily,projects,preferences,incidents}
    # 从示例复制 INDEX
    if [ -f "$SCRIPT_DIR/examples/vault-sample/INDEX.md" ]; then
        cp "$SCRIPT_DIR/examples/vault-sample/INDEX.md" "$VAULT/INDEX.md"
    fi
fi

# ---- 写入配置文件 ---------------------------------------------------------------
echo "📦 写入配置..."
CONFIG_FILE="$HERMES_HOME/.env"
if [ -f "$CONFIG_FILE" ] && grep -q "HERMES_VAULT" "$CONFIG_FILE"; then
    # 保留用户已有
    echo "  (保留已有 HERMES_VAULT)"
else
    {
        echo "# agent-memory-driven-evolution"
        echo "HERMES_VAULT=$VAULT"
        echo "HERMES_HOME=$HERMES_HOME"
    } >> "$CONFIG_FILE" 2>/dev/null || true
fi

# ---- 定时任务 -------------------------------------------------------------------
if [ "$SKIP_CRON" = "0" ]; then
    echo ""
    echo "📦 安装定时任务..."
    source "$SCRIPTS_DIR/lib/platform.sh"
    if [ "$PLATFORM_OS" = "Darwin" ]; then
        platform_install_cron "com.roader.skill-evolution-weekly" \
            "python3 $SCRIPTS_DIR/skill_evolution/run_weekly.py" \
            "30 21 * * 0"
    else
        platform_install_cron "skill-evolution-weekly" \
            "python3 $SCRIPTS_DIR/skill_evolution/run_weekly.py" \
            "30 21 * * 0"
    fi
    echo "  ✔ 每周日 21:30 技能自进化审计已安装"
else
    echo "⏭️  跳过定时任务（--no-cron）"
fi

# ---- 验证安装 -------------------------------------------------------------------
echo ""
echo "🔍 验证安装..."
FAIL=0
[ -x "$SCRIPTS_DIR/smart_archive.sh" ] || { echo "  ❌ smart_archive.sh 缺失"; FAIL=1; }
[ -f "$SCRIPTS_DIR/skill_evolution/run_weekly.py" ] || { echo "  ❌ skill_evolution 缺失"; FAIL=1; }
[ -d "$SKILLS_DIR/roader-skill-evolution" ] || { echo "  ❌ roader-skill-evolution skill 缺失"; FAIL=1; }
[ -d "$SKILLS_DIR/roader-auto-memory-archiving" ] || { echo "  ❌ roader-auto-memory-archiving skill 缺失"; FAIL=1; }
[ -d "$VAULT" ] || { echo "  ❌ vault 缺失"; FAIL=1; }
if [ "$FAIL" = "0" ]; then
    echo "  ✅ 全部通过"
else
    echo "  ⚠️  有 $FAIL 项未通过，请检查"
    exit 1
fi

# ---- 完成 ------------------------------------------------------------------------
echo ""
echo "🎉 安装完成！"
echo ""
echo "下一步："
echo "  1. 用 Obsidian 打开 $VAULT"
echo "  2. 手动跑一次周审: python3 $SCRIPTS_DIR/skill_evolution/run_weekly.py"
echo "  3. 卸载: rm -rf ~/.hermes  （或运行 ./uninstall.sh）"
echo ""
if [ "$PLATFORM_OS" = "Darwin" ]; then
    echo "提示: 若想彻底卸载, 运行 $SCRIPT_DIR/uninstall.sh"
fi