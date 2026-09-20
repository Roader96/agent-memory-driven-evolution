#!/usr/bin/env bash
# =============================================================================
# Codex structured memory · standalone installer
# -----------------------------------------------------------------------------
# Installs the Codex archiver in a Codex-owned memory home (default
# ~/CodexMemory) and schedules com.codex.memory. It does not require Hermes,
# ~/HermesMemory, Hermes state.db, an LLM service, or Obsidian at runtime.
# =============================================================================
set -euo pipefail

MODE="interactive"
MEMORY_HOME="${CODEX_MEMORY_HOME:-$HOME/CodexMemory}"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
SKIP_CRON=0
LABEL="com.codex.memory"
LEGACY_LABEL="com.codex.hermes-memory"

usage() {
    cat <<'USAGE'
Install standalone structured Codex memory.

Usage:
  ./install_codex_memory.sh [options]

Options:
  --yes               Non-interactive install
  --memory-home PATH  Codex memory root (default: $CODEX_MEMORY_HOME or ~/CodexMemory)
  --codex-home PATH   Codex session home (default: $CODEX_HOME or ~/.codex)
  --no-cron           Do not install/update launchd or cron scheduling
  --help              Show this help

Legacy option:
  --vault PATH        Install under PATH/codex instead of the direct memory home
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) MODE="silent" ;;
        --memory-home)
            [ $# -ge 2 ] || { echo "❌ --memory-home requires a path" >&2; exit 2; }
            MEMORY_HOME="$2"; shift ;;
        --vault)
            [ $# -ge 2 ] || { echo "❌ --vault requires a path" >&2; exit 2; }
            MEMORY_HOME="$2/codex"; shift ;;
        --codex-home)
            [ $# -ge 2 ] || { echo "❌ --codex-home requires a path" >&2; exit 2; }
            CODEX_ROOT="$2"; shift ;;
        --no-cron) SKIP_CRON=1 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "❌ 未知参数: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_OS="$(uname -s)"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
if [ ! -x "$PYTHON_BIN" ]; then PYTHON_BIN="$(command -v python3)"; fi

BIN_DIR="$MEMORY_HOME/bin"
LOG_DIR="$MEMORY_HOME/logs"
LOCK_DIR="$MEMORY_HOME/locks"
WRAPPER="$MEMORY_HOME/run_maintenance.sh"

case "$PLATFORM_OS" in
    Darwin|Linux) ;;
    *) echo "❌ 不支持的平台: $PLATFORM_OS（仅支持 macOS / Linux）" >&2; exit 1 ;;
esac

for dep in bash "$PYTHON_BIN"; do
    if ! command -v "$dep" >/dev/null 2>&1; then
        echo "❌ 缺少依赖: $dep" >&2
        exit 1
    fi
done

echo "📦 将安装独立 Codex 结构化记忆："
echo "   Codex 记忆目录: $MEMORY_HOME"
echo "   Codex 会话目录: $CODEX_ROOT"
if [ "$SKIP_CRON" = "0" ]; then
    echo "   定时任务:       ${LABEL}（每天 23:55）"
else
    echo "   定时任务:       跳过"
fi
echo ""

if [ "$MODE" = "interactive" ]; then
    read -r -p "继续安装? [Y/n] " confirm
    if [[ -n "$confirm" && ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "❌ 已取消"
        exit 0
    fi
fi

echo "📦 安装脚本..."
mkdir -p "$BIN_DIR" "$LOG_DIR" "$LOCK_DIR" "$MEMORY_HOME/daily"
install -m 755 "$SCRIPT_DIR/scripts/codex_memory.py" "$BIN_DIR/codex_memory.py"
install -m 755 "$SCRIPT_DIR/scripts/codex_memory_maintenance.sh" "$BIN_DIR/codex_memory_maintenance.sh"
install -m 755 "$SCRIPT_DIR/scripts/codex_run_maintenance.sh" "$WRAPPER"

remove_macos_job() {
    local label="$1"
    local plist="$HOME/Library/LaunchAgents/$label.plist"
    if [ -f "$plist" ]; then
        launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
        launchctl unload "$plist" >/dev/null 2>&1 || true
    fi
}

install_macos_cron() {
    local plist_dir="$HOME/Library/LaunchAgents"
    local plist="$plist_dir/$LABEL.plist"
    local legacy_plist="$plist_dir/$LEGACY_LABEL.plist"
    mkdir -p "$plist_dir"

    # Remove old Hermes-named jobs only when their plist belongs to this HOME.
    remove_macos_job "$LEGACY_LABEL"
    rm -f "$legacy_plist"
    remove_macos_job "$LABEL"

    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$WRAPPER</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>23</integer>
    <key>Minute</key>
    <integer>55</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/launchd.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd.stderr.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>PATH</key>
    <string>/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>TZ</key>
    <string>Asia/Shanghai</string>
    <key>CODEX_HOME</key>
    <string>$CODEX_ROOT</string>
    <key>CODEX_MEMORY_HOME</key>
    <string>$MEMORY_HOME</string>
  </dict>
</dict>
</plist>
PLIST
    chmod 600 "$plist"

    if ! launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null; then
        launchctl unload "$plist" >/dev/null 2>&1 || true
        launchctl load -w "$plist"
    fi
    launchctl enable "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
    launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
}

# v0 时代 Codex 记忆寄生在 HermesMemory/codex 根下；独立布局后这些根文件已无人
# 读取/写入（新链路只用 bin/、.index/、sessions/ 等）。重装时迁入备份目录，
# 零删除（零丢失原则）；全新安装或重复运行均为 no-op。
relocate_legacy_files() {
  # 仅当新独立布局确实存在时才清理，避免误删旧布局安装
  [ -f "$BIN_DIR/codex_memory.py" ] || return 0
  local stamp bk moved=0
  stamp="$(date '+%Y%m%d-%H%M%S')"
  bk="$MEMORY_HOME/backups/legacy-cleanup-$stamp"
  for f in archive_sessions.py launchd.stderr.log launchd.stdout.log HOT-MEMORY.md USAGE.md; do
    if [ -e "$MEMORY_HOME/$f" ]; then
      mkdir -p "$bk"
      mv "$MEMORY_HOME/$f" "$bk/$f"
      moved=1
    fi
  done
  if [ "$moved" = "1" ]; then
    echo "  ✔ 旧布局残留文件已迁入备份: ${bk#$HOME/}"
  fi
}

install_linux_cron() {
    local tmp
    tmp="$(mktemp)"
    if crontab -l >/dev/null 2>&1; then
        crontab -l
    else
        true
    fi | grep -v -E "(# ${LABEL}$|# ${LEGACY_LABEL}$|${MEMORY_HOME}/run_maintenance\.sh)" > "$tmp" || true
    printf "55 23 * * * CODEX_HOME='%s' CODEX_MEMORY_HOME='%s' /bin/bash '%s' # %s\n" \
        "$CODEX_ROOT" "$MEMORY_HOME" "$WRAPPER" "$LABEL" >> "$tmp"
    crontab "$tmp"
    rm -f "$tmp"
}

if [ "$SKIP_CRON" = "0" ]; then
    echo "🕐 安装/迁移定时任务..."
    if [ "$PLATFORM_OS" = "Darwin" ]; then
        install_macos_cron
    else
        install_linux_cron
    fi
    echo "  ✔ $LABEL"
else
    echo "⏭️  跳过定时任务（--no-cron）"
fi

echo "🔍 立即构建并验证..."
# Bootstrap indexes even on a machine that has not created ~/.codex yet;
# the wrapper itself safely skips when CODEX_HOME is absent.
"$PYTHON_BIN" "$BIN_DIR/codex_memory.py"   --memory-home "$MEMORY_HOME"   --codex-home "$CODEX_ROOT"
"$WRAPPER"

for required in \
    "$BIN_DIR/codex_memory.py" \
    "$BIN_DIR/codex_memory_maintenance.sh" \
    "$WRAPPER" \
    "$MEMORY_HOME/INDEX.md" \
    "$MEMORY_HOME/OPEN-ITEMS.md" \
    "$MEMORY_HOME/DECISIONS.md"; do
    [ -s "$required" ] || { echo "❌ 安装验证失败，缺少: $required" >&2; exit 1; }
done
[ -f "$MEMORY_HOME/.index/sessions.jsonl" ] || { echo "❌ 安装验证失败，缺少: $MEMORY_HOME/.index/sessions.jsonl" >&2; exit 1; }

relocate_legacy_files

if [ "$PLATFORM_OS" = "Darwin" ] && [ "$SKIP_CRON" = "0" ]; then
    echo "🕐 launchd 状态："
    for _ in $(seq 1 20); do
        if launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -q "last exit code = 0"; then
            break
        fi
        sleep 1
    done
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null \
        | grep -E "state =|last exit code|path =" || true
fi

echo ""
echo "✅ 独立 Codex 记忆维护已安装：$MEMORY_HOME"
echo "   手动运行：$WRAPPER"
echo "   Hermes、~/.hermes 和 ~/HermesMemory 都不是这套链路的运行依赖。"
