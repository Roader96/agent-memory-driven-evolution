#!/usr/bin/env bash
# =============================================================================
# Codex structured memory · standalone installer
# -----------------------------------------------------------------------------
# Installs the Codex archiver inside <vault>/codex/bin and schedules a Codex
# LaunchAgent/cron job. This component does not require the Hermes Agent, its
# state.db, an LLM service, or Obsidian at runtime.
# =============================================================================
set -euo pipefail

MODE="interactive"
VAULT="${HERMES_VAULT:-$HOME/HermesMemory}"
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
  --yes             Non-interactive install
  --vault PATH      Memory vault that contains the codex/ namespace
                    (default: $HERMES_VAULT or ~/HermesMemory)
  --codex-home PATH Codex session home (default: $CODEX_HOME or ~/.codex)
  --no-cron         Do not install/update launchd or cron scheduling
  --help            Show this help
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) MODE="silent" ;;
        --vault)
            [ $# -ge 2 ] || { echo "❌ --vault requires a path" >&2; exit 2; }
            VAULT="$2"; shift ;;
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

CODEX_DIR="$VAULT/codex"
BIN_DIR="$CODEX_DIR/bin"
LOG_DIR="$CODEX_DIR/logs"
LOCK_DIR="$CODEX_DIR/locks"
WRAPPER="$CODEX_DIR/run_maintenance.sh"

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
echo "   Codex 数据/脚本: $CODEX_DIR"
echo "   Codex 会话目录:  $CODEX_ROOT"
if [ "$SKIP_CRON" = "0" ]; then
    echo "   定时任务:        ${LABEL}（每天 23:55）"
else
    echo "   定时任务:        跳过"
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
mkdir -p "$BIN_DIR" "$LOG_DIR" "$LOCK_DIR" "$CODEX_DIR/daily"
install -m 755 "$SCRIPT_DIR/scripts/codex_memory.py" "$BIN_DIR/codex_memory.py"
install -m 755 "$SCRIPT_DIR/scripts/codex_memory_maintenance.sh" "$BIN_DIR/codex_memory_maintenance.sh"
install -m 755 "$SCRIPT_DIR/scripts/codex_run_maintenance.sh" "$WRAPPER"

remove_macos_job() {
    local label="$1"
    local plist="$HOME/Library/LaunchAgents/$label.plist"
    launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
    launchctl unload "$plist" >/dev/null 2>&1 || true
}

install_macos_cron() {
    local plist_dir="$HOME/Library/LaunchAgents"
    local plist="$plist_dir/$LABEL.plist"
    local legacy_plist="$plist_dir/$LEGACY_LABEL.plist"
    mkdir -p "$plist_dir"

    # Remove the old Hermes-named Codex job before installing the replacement.
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

install_linux_cron() {
    local tmp
    tmp="$(mktemp)"
    if crontab -l >/dev/null 2>&1; then
        crontab -l
    else
        true
    fi | grep -v -E "(# ${LABEL}$|# ${LEGACY_LABEL}$|${CODEX_DIR}/run_maintenance\.sh)" > "$tmp" || true
    printf "55 23 * * * CODEX_HOME='%s' /bin/bash '%s' # %s\n" \
        "$CODEX_ROOT" "$WRAPPER" "$LABEL" >> "$tmp"
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
if [ -d "$CODEX_ROOT" ]; then
    "$WRAPPER"
else
    # Even in a machine without Codex sessions yet, create generated empty
    # indexes so the wrapper's postconditions and a fresh vault are valid.
    "$PYTHON_BIN" "$BIN_DIR/codex_memory.py" --vault "$VAULT" --codex-home "$CODEX_ROOT"
    "$WRAPPER"
fi

for required in \
    "$BIN_DIR/codex_memory.py" \
    "$BIN_DIR/codex_memory_maintenance.sh" \
    "$WRAPPER" \
    "$CODEX_DIR/INDEX.md" \
    "$CODEX_DIR/OPEN-ITEMS.md" \
    "$CODEX_DIR/DECISIONS.md"; do
    [ -s "$required" ] || { echo "❌ 安装验证失败，缺少: $required" >&2; exit 1; }
done
[ -f "$CODEX_DIR/.index/sessions.jsonl" ] || { echo "❌ 安装验证失败，缺少: $CODEX_DIR/.index/sessions.jsonl" >&2; exit 1; }

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
echo "✅ 独立 Codex 记忆维护已安装：$CODEX_DIR"
echo "   手动运行：$WRAPPER"
echo "   卸载 Hermes 的 ~/.hermes 不会删除或停用这套独立脚本/数据。"
