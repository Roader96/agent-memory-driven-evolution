#!/bin/bash
# =============================================================================
# agent-memory-driven-evolution · 安装器集成测试
# -----------------------------------------------------------------------------
# 在临时 HOME 下运行 install.sh / uninstall.sh，验证安装/卸载全流程。
#
# 用法：
#   tests/test_install.sh            # 运行测试
#   tests/test_install.sh --debug    # 保留临时目录供调试
#
# 参考成熟开源项目（oh-my-zsh 等的 test suite）：隔离环境 + 断言 + 清理
# =============================================================================

set -euo pipefail

TEST_ROOT="$(mktemp -d)/hermes-test"
export HOME="$TEST_ROOT/home"
export HERMES_HOME="$HOME/.hermes"
mkdir -p "$HOME"

PASS=0
FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ✅ $1"; }
fail() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

# ---- 1. install.sh --yes 安装 --------------------------------------------------
echo ""
echo "=== 测试 1: install.sh --yes 安装 ==="
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if bash "$PROJECT_DIR/install.sh" --yes --vault "$HOME/TestVault" --no-cron 2>&1 | tail -5; then
    ok "install.sh 退出码 0"
else
    fail "install.sh 退出码非 0"
    exit 1
fi

# ---- 2. 验证文件安装 ------------------------------------------------------------
echo ""
echo "=== 测试 2: 文件安装验证 ==="
[ -x "$HERMES_HOME/scripts/smart_archive.sh" ] && ok "smart_archive.sh 已安装且可执行" || fail "smart_archive.sh 缺失"
[ -f "$HERMES_HOME/scripts/skill_evolution/run_weekly.py" ] && ok "skill_evolution/run_weekly.py 已安装" || fail "skill_evolution 缺失"
[ -d "$HERMES_HOME/skills/roader-skill-evolution" ] && ok "roader-skill-evolution skill 已安装" || fail "skill 缺失"
[ -d "$HERMES_HOME/skills/roader-auto-memory-archiving" ] && ok "roader-auto-memory-archiving skill 已安装" || fail "skill 缺失"
[ -d "$HOME/TestVault" ] && ok "vault 已创建" || fail "vault 未创建"
[ -f "$HOME/TestVault/INDEX.md" ] && ok "vault INDEX.md 已复制" || fail "INDEX.md 缺失"

# ---- 3. 平台兼容层测试 -----------------------------------------------------------
echo ""
echo "=== 测试 3: 平台兼容层 ==="
source "$HERMES_HOME/scripts/lib/platform.sh"
ONE=$(platform_file_size /etc/hosts 2>/dev/null || platform_file_size "$HERMES_HOME/scripts/smart_archive.sh")
if [ "$ONE" -gt 0 ] 2>/dev/null; then
    ok "platform_file_size 返回 $ONE"
else
    fail "platform_file_size 返回 $ONE"
fi
D=$(platform_date_readable 0 "+%Y")
if [ "$D" = "1970" ]; then
    ok "platform_date_readable 工作正常 ($D)"
else
    fail "platform_date_readable 返回 $D (期望 1970)"
fi

# ---- 4. 所有脚本语法检查 -----------------------------------------------------------
echo ""
echo "=== 测试 4: 语法检查 ==="
SYNTAX_OK=1
for f in "$PROJECT_DIR"/scripts/*.sh "$PROJECT_DIR"/scripts/lib/*.sh "$PROJECT_DIR"/install.sh "$PROJECT_DIR"/uninstall.sh; do
    if ! bash -n "$f" 2>/dev/null; then
        echo "  ❌ bash 语法错误: $f"
        SYNTAX_OK=0
    fi
done
for f in "$PROJECT_DIR"/scripts/*.py "$PROJECT_DIR"/scripts/skill_evolution/*.py; do
    if ! python3 -m py_compile "$f" 2>/dev/null; then
        echo "  ❌ python 语法错误: $f"
        SYNTAX_OK=0
    fi
done
[ "$SYNTAX_OK" = "1" ] && ok "全部脚本语法正确" || fail "存在语法错误"

# ---- 5. uninstall.sh --yes --keep-vault 卸载 --------------------------------------
echo ""
echo "=== 测试 5: uninstall.sh --yes --keep-vault ==="
# 复制 uninstall.sh 到可访问位置（home 下运行，但项目路径不同）
if bash "$PROJECT_DIR/uninstall.sh" --yes --keep-vault >/dev/null 2>&1; then
    ok "uninstall.sh 退出码 0"
else
    fail "uninstall.sh 退出码非 0 (残留)"
fi
[ ! -d "$HERMES_HOME/scripts" ] && ok "scripts 已删除" || fail "scripts 仍存在"
[ -d "$HOME/TestVault" ] && ok "vault 保留（--keep-vault）" || fail "vault 被误删 🚨"

# ---- 汇总 -----------------------------------------------------------------------
echo ""
echo "======================"
echo "结果: $PASS 通过 / $FAIL 失败"
if [ "$FAIL" != "0" ]; then
    echo "❌ 测试失败"
    exit 1
fi
echo "✅ 全部通过"

# ---- 清理 -----------------------------------------------------------------------
if [ "${1:-}" != "--debug" ]; then
    rm -rf "$(dirname "$TEST_ROOT")"
    echo "(临时目录已清理)"
else
    echo "(调试模式，保留临时目录: $TEST_ROOT)"
fi