#!/bin/bash
# =============================================================================
# xxzAgentMemory · 平台兼容层
# -----------------------------------------------------------------------------
# 统一 macOS (BSD) 与 Linux (GNU) 的常用命令差异。
# 用法：source 本文件后调用 platform_* 函数，而不是直接裸用 date/stat。
#
# 参考：GNU coreutils 与 BSD 工具版本差异的通用处理模式。
# =============================================================================

PLATFORM_OS="$(uname -s)"
PLATFORM_DATE_FLAG="+%s"       # date 取 epoch 秒
PLATFORM_GNU_DATE=""

# ---- 检测 GNU date / BSD date ------------------------------------------------
if date --version >/dev/null 2>&1; then
    PLATFORM_GNU_DATE=1
fi

# ---- 平台工具：文件大小（兼容 stat -f%z / stat -c%s）-------------------------
# 用法：platform_file_size <path>
platform_file_size() {
    local path="$1"
    if [ "$PLATFORM_OS" = "Darwin" ]; then
        stat -f%z "$path" 2>/dev/null || echo "0"
    else
        stat -c%s "$path" 2>/dev/null || echo "0"
    fi
}

# ---- 平台工具：unix 时间戳转可读日期 ---------------------------------------
# 用法：platform_date_readable <epoch> [format]
platform_date_readable() {
    local epoch="$1"
    local fmt="${2:-%Y-%m-%d %H:%M:%S}"
    if [ "$PLATFORM_OS" = "Darwin" ]; then
        date -r "$epoch" "$fmt" 2>/dev/null || echo "?"
    else
        date -d "@$epoch" "$fmt" 2>/dev/null || echo "?"
    fi
}

# ---- 平台工具：从文件 mtime 取 epoch ---------------------------------------
# 用法：platform_file_mtime <path>
platform_file_mtime() {
    local path="$1"
    if [ "$PLATFORM_OS" = "Darwin" ]; then
        stat -f%m "$path" 2>/dev/null || echo "0"
    else
        stat -c%Y "$path" 2>/dev/null || echo "0"
    fi
}

# ---- 平台判断 -----------------------------------------------------------------
platform_is_macos() { [ "$PLATFORM_OS" = "Darwin" ]; }
platform_is_linux() { [ "$PLATFORM_OS" = "Linux" ]; }

# ---- 安装目录（不同平台使用不同约定） ---------------------------------------
# macOS:  ~/.hermes （与 Hermes 主目录一致）
# Linux:  ~/.hermes  （保持统一定位，符合 XDG 的精神但用 ~/.hermes 便于跨平台）
platform_hermes_home() {
    echo "${HERMES_HOME:-$HOME/.hermes}"
}

# ---- 定时任务安装 -------------------------------------------------------------
# macOS:  launchctl + plist；返回值 0=成功
# Linux:  crontab；函数返回 0=成功
# 用法：platform_install_cron <label> <command_line> <schedule_cron_expr>
#       schedule_cron_expr 例子："30 21 * * 0"（每周日 21:30）
platform_install_cron() {
    local label="$1"
    local cmd="$2"
    local cron_expr="$3"
    local hermes_home

    hermes_home="$(platform_hermes_home)"

    if platform_is_macos; then
        # macOS: 生成 plist 到 ~/Library/LaunchAgents
        local plist_dir="$HOME/Library/LaunchAgents"
        local plist_path="$plist_dir/$label.plist"
        mkdir -p "$plist_dir"
        platform_gen_plist "$label" "$cmd" "$plist_path" >/dev/null
        launchctl unload "$plist_path" >/dev/null 2>&1
        launchctl load -w "$plist_path" >/dev/null 2>&1
        return $?
    elif platform_is_linux; then
        # Linux: 追加 crontab
        local crontab_backup
        crontab_backup="$(mktemp)"
        crontab -l >/dev/null 2>&1 && crontab -l > "$crontab_backup" || true
        # 移除旧的同 label 条目
        grep -v " # $label$" "$crontab_backup" > "${crontab_backup}.new" || true
        echo "$cron_expr $cmd # $label" >> "${crontab_backup}.new"
        crontab "${crontab_backup}.new"
        rm -f "$crontab_backup" "${crontab_backup}.new"
        return $?
    fi
    return 1
}

# ---- 生成 macOS plist（模板化安装路径） ---------------------------------------
# 用法：platform_gen_plist <label> <command> <output_path>
platform_gen_plist() {
    local label="$1"
    local cmd="$2"
    local out_path="$3"
    local home="$HOME"
    local log_dir="$home/.hermes/logs"
    mkdir -p "$log_dir"
    cat > "$out_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>${cmd}</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>21</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${log_dir}/skill_evolution.log</string>
    <key>StandardErrorPath</key>
    <string>${log_dir}/skill_evolution.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${home}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF
}

# ---- 卸载定时任务 -------------------------------------------------------------
# 用法：platform_uninstall_cron <label>
platform_uninstall_cron() {
    local label="$1"
    if platform_is_macos; then
        local plist_path="$HOME/Library/LaunchAgents/$label.plist"
        if [ -f "$plist_path" ]; then
            launchctl unload "$plist_path" >/dev/null 2>&1
            rm -f "$plist_path"
            return 0
        fi
    elif platform_is_linux; then
        local crontab_backup
        crontab_backup="$(mktemp)"
        if crontab -l >/dev/null 2>&1; then
            crontab -l | grep -v " # ${label}$" > "$crontab_backup" || true
            crontab "$crontab_backup" || true
        fi
        rm -f "$crontab_backup"
        return 0
    fi
    return 1
}