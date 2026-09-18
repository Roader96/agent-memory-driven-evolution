#!/bin/bash
# =============================================================================
# xxzAgentMemory · 安装器
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
INSTALL_OBSIDIAN=0

usage() {
    cat <<'EOF'
xxzAgentMemory installer

Usage:
  ./install.sh [options]

Options:
  --yes          Non-interactive install (no confirmation prompts)
  --vault PATH   Set the memory vault location (default: ~/HermesMemory)
  --no-cron      Skip installing scheduled tasks (launchd/crontab)
  --install-obsidian  Auto-download Obsidian v1.13.7 (pinned) if missing.
                 默认不自动安装第三方软件——缺失时给手动安装指引
  --no-obsidian  Skip Obsidian requirement (降级模式：核心归档/进化可用，
                 但失去可视化/语义检索/反向链接——不推荐，随时可补装)
  --help         Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) MODE="silent" ;;
        --vault) VAULT="$2"; shift ;;
        --no-cron) SKIP_CRON=1 ;;
        --install-obsidian) INSTALL_OBSIDIAN=1 ;;
        --no-obsidian) OBSIDIAN_CHECK=0 ;;
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
echo "✅ 基础依赖检查通过 (bash / python3 / git)"

# Obsidian —— 永久记忆的载体（核心依赖，非可选）
# 警告：没有 Obsidian 就没有可视化/检索/反向链接的永久记忆库
# 测试/CI 可用 OBSIDIAN_CHECK=0 跳过真实检测（模拟已安装）
OBSIDIAN_CHECK="${OBSIDIAN_CHECK:-1}"
OBSIDIAN_FOUND=0
if [ "$OBSIDIAN_CHECK" = "1" ]; then
  if [ "$PLATFORM_OS" = "Darwin" ]; then
    if [ -d "/Applications/Obsidian.app" ] || ls "$HOME/Applications/Obsidian.app" >/dev/null 2>&1; then
        OBSIDIAN_FOUND=1
    fi
  else
    if command -v obsidian >/dev/null 2>&1 || [ -f "$HOME/Applications/Obsidian.AppImage" ] || [ -f "/opt/Obsidian-*.AppImage" ]; then
        OBSIDIAN_FOUND=1
    fi
  fi
else
  OBSIDIAN_FOUND=1
fi

if [ "$OBSIDIAN_FOUND" = "0" ]; then
    # 供应链安全（评价 P1-3）：默认不自动安装第三方软件——
    # 只在交互模式显式同意、或传 --install-obsidian 时才下载；
    # 固定版本 + HTTPS/TLS 限定 + 失败立即退出，杜绝"半安装"。
    OBSIDIAN_VERSION="1.13.7"  # 固定版本（v1.13.8 桌面资产未传全，勿追 latest）
    AUTO_INSTALL=0
    if [ "$INSTALL_OBSIDIAN" = "1" ]; then
        AUTO_INSTALL=1
    elif [ "$MODE" = "interactive" ]; then
        echo "⚠️  未检测到 Obsidian —— 它是永久记忆的核心载体（vault 可视化/语义检索/反向链接全靠它）。"
        echo "   推荐手动安装（最安全）：https://obsidian.md/download  (macOS 也可 brew install --cask obsidian)"
        read -r -p "是否让安装器自动下载安装 Obsidian v${OBSIDIAN_VERSION}? [y/N] " install_obs
        [[ "$install_obs" =~ ^[Yy]$ ]] && AUTO_INSTALL=1
    fi

    if [ "$AUTO_INSTALL" = "1" ]; then
        echo "📦 正在安装 Obsidian v${OBSIDIAN_VERSION}（固定版本）..."
        if [ "$PLATFORM_OS" = "Darwin" ]; then
            # macOS: 下载 DMG 并安装（严格 curl：失败立即非零退出）
            DMG=/tmp/obsidian-${OBSIDIAN_VERSION}.dmg
            rm -f "$DMG"
            curl --fail --location --proto '=https' --tlsv1.2 \
                -o "$DMG" \
                "https://github.com/obsidianmd/obsidian-releases/releases/download/v${OBSIDIAN_VERSION}/Obsidian-${OBSIDIAN_VERSION}.dmg" \
                || { echo "❌ Obsidian 下载失败，安装中止（未做任何更改）"; exit 1; }
            # 校验 dmg 格式有效性（防截断/替换文件）
            hdiutil imageinfo "$DMG" >/dev/null 2>&1 \
                || { echo "❌ 下载的 DMG 无效（校验失败），安装中止"; rm -f "$DMG"; exit 1; }
            hdiutil attach "$DMG" -nobrowse \
                && cp -R "/Volumes/Obsidian/Obsidian.app" /Applications/ \
                && hdiutil detach /Volumes/Obsidian/ -quiet \
                && rm -f "$DMG" \
                && echo "  ✅ Obsidian v${OBSIDIAN_VERSION} 已安装到 /Applications/" \
                || { echo "❌ Obsidian 安装失败"; hdiutil detach /Volumes/Obsidian/ -quiet 2>/dev/null; exit 1; }
        else
            # Linux: 固定版本 AppImage
            mkdir -p "$HOME/Applications"
            APPIMAGE="$HOME/Applications/Obsidian.AppImage"
            curl --fail --location --proto '=https' --tlsv1.2 \
                -o "$APPIMAGE" \
                "https://github.com/obsidianmd/obsidian-releases/releases/download/v${OBSIDIAN_VERSION}/Obsidian-${OBSIDIAN_VERSION}.AppImage" \
                || { echo "❌ Obsidian 下载失败，安装中止（未做任何更改）"; rm -f "$APPIMAGE"; exit 1; }
            chmod +x "$APPIMAGE" \
                && echo "  ✅ Obsidian AppImage v${OBSIDIAN_VERSION} 已安装到 $HOME/Applications/"
        fi
    elif [ "$MODE" = "interactive" ]; then
        echo "❌ 未安装 Obsidian，安装终止（永久记忆系统必须有 Obsidian 作为 vault 载体）"
        echo "   手动安装后重新运行 ./install.sh，或用 --install-obsidian 让安装器自动装"
        exit 1
    else
        echo "❌ 未检测到 Obsidian（永久记忆核心依赖）。请先安装："
        echo "   macOS:  https://obsidian.md/download  (或 brew install --cask obsidian)"
        echo "   Linux:  https://obsidian.md/download  (AppImage / flatpak / snap)"
        echo "   然后重新运行 ./install.sh（或加 --install-obsidian 自动装 / --no-obsidian 降级）"
        exit 1
    fi
else
    echo "✅ Obsidian 已安装（永久记忆 vault 载体）"
fi

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
# Codex has its own standalone installer and ~/CodexMemory home. Do not leave a
# second executable copy under Hermes' ~/.hermes runtime directory.
rm -f "$SCRIPTS_DIR/codex_memory.py" \
      "$SCRIPTS_DIR/codex_memory_maintenance.sh" \
      "$SCRIPTS_DIR/codex_run_maintenance.sh"
# 不要覆盖平台无关的 lib
chmod +x "$SCRIPTS_DIR"/*.sh "$SCRIPTS_DIR"/*.py 2>/dev/null || true

# ---- 安装 skills --------------------------------------------------------------
echo "📦 安装 skills..."
# 只安装 v2 版（user-*），旧版 hermes-* 不装
for skill_dir in "$SCRIPT_DIR"/skills/user-*/; do
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

# ---- 初始化 Obsidian vault 结构（.obsidian 配置） --------------------------------
# Obsidian 是永久记忆的载体（核心依赖），vault 必须从安装起就是合法 Obsidian vault
OBSIDIAN_DIR="$VAULT/.obsidian"
if [ ! -d "$OBSIDIAN_DIR" ]; then
    mkdir -p "$OBSIDIAN_DIR/plugins"
    # 基础配置：启用 markdown 语法 + 不自动创建未收录文件
    cat > "$OBSIDIAN_DIR/app.json" <<EOF
{
  "useMarkdownLinks": true,
  "showUnsupportedFiles": false,
  "attachmentFolderPath": "attachments"
}
EOF
    # 允许社区插件（Smart Connections 语义搜索依赖）
    # 注意：这只是"声明启用位"——插件真实安装 = .obsidian/plugins/smart-connections/ 存在，
    # 需在 Obsidian 内 Community Plugins 搜 Smart Connections 安装（见末尾检测提示）
    cat > "$OBSIDIAN_DIR/community-plugins.json" <<EOF
["smart-connections"]
EOF
    echo "  ✔ Obsidian vault 已初始化（.obsidian 配置 + Smart Connections 启用位已声明）"
else
    echo "  ✔ Obsidian vault 已存在（保留现有配置）"
fi

# Smart Connections 真实安装检测（写 community-plugins.json ≠ 插件已装）
if [ -f "$OBSIDIAN_DIR/plugins/smart-connections/manifest.json" ]; then
    echo "  ✔ Smart Connections 已安装（语义搜索可用）"
else
    echo "  ⓘ Smart Connections 未安装：语义搜索暂不可用（归档/反向链接不受影响）"
    echo "     装法：Obsidian 打开 vault → Settings → Community Plugins → 搜 Smart Connections → Install"
fi

# ---- 安装独立 Codex 记忆维护 -----------------------------------------------------
# Codex 文件安装在独立的 ~/CodexMemory（或 CODEX_MEMORY_HOME），与 Hermes vault 完全分离。
echo ""
echo "📦 安装独立 Codex 结构化记忆..."
CODEX_INSTALL_ARGS=(--yes --memory-home "${CODEX_MEMORY_HOME:-$HOME/CodexMemory}")
if [ "$SKIP_CRON" = "1" ]; then
    CODEX_INSTALL_ARGS+=(--no-cron)
fi
if [ -n "${CODEX_HOME:-}" ]; then
    CODEX_INSTALL_ARGS+=(--codex-home "$CODEX_HOME")
fi
bash "$SCRIPT_DIR/install_codex_memory.sh" "${CODEX_INSTALL_ARGS[@]}"

# ---- 写入配置文件 ---------------------------------------------------------------
echo "📦 写入配置..."
CONFIG_FILE="$HERMES_HOME/.env"
if [ -f "$CONFIG_FILE" ] && grep -q "HERMES_VAULT" "$CONFIG_FILE"; then
    # 保留用户已有
    echo "  (保留已有 HERMES_VAULT)"
else
    {
        echo "# xxzAgentMemory"
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
        platform_install_cron "com.user.skill-evolution-weekly" \
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
[ -d "$SKILLS_DIR/user-skill-evolution" ] || { echo "  ❌ user-skill-evolution skill 缺失"; FAIL=1; }
[ -d "$SKILLS_DIR/user-auto-memory-archiving" ] || { echo "  ❌ user-auto-memory-archiving skill 缺失"; FAIL=1; }
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
echo "  2. Codex 独立记忆入口: ${CODEX_MEMORY_HOME:-$HOME/CodexMemory}/run_maintenance.sh"
echo "  3. 手动跑一次周审: python3 $SCRIPTS_DIR/skill_evolution/run_weekly.py"
echo "  4. 卸载请运行 ./uninstall.sh（不要直接 rm -rf ~/.hermes）"
echo ""
if [ "$PLATFORM_OS" = "Darwin" ]; then
    echo "提示: 若想彻底卸载, 运行 $SCRIPT_DIR/uninstall.sh"
fi
