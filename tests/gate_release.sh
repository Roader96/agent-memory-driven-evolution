#!/bin/bash
# =============================================================================
# agent-memory-driven-evolution · 发布门禁（Release Gate）
# -----------------------------------------------------------------------------
# 严格门禁：三次隔离实测 + 静态安全检查，全部通过才允许发布。
#
# 规则（硬性）：
#   1. 三轮完整 install → verify → uninstall 实测（每轮全新临时 HOME）
#   2. 每轮 13 断言，三轮共 39 断言，全部通过
#   3. 静态安全检查：无个人路径硬编码 / 无旧仓库名残留 / 无 API 密钥
#   4. 任何一轮失败 → 输出 FAIL，exit 1，禁止发布
#
# 用法：
#   tests/gate_release.sh             # 跑门禁（约 1-2 分钟）
#   tests/gate_release.sh --fast      # 只跑一轮（调试用，不算门禁通过）
#
# 门禁通过后会在 tests/.release-gate-passed 写入时间戳，
# 发布流程必须验证该文件存在 + git log 一致，否则拒绝发布。
# =============================================================================

set -euo pipefail

GATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$GATE_DIR")"
GATE_LOG_DIR="$GATE_DIR/gate-logs"
mkdir -p "$GATE_LOG_DIR"
GATE_PASSED_FILE="$GATE_DIR/.release-gate-passed"
GATE_RESULT_FILE="$GATE_DIR/.release-gate-result"

ROUNDS=3
if [ "${1:-}" = "--fast" ]; then
    ROUNDS=1
    echo "⚠️  --fast 模式：只跑 1 轮，仅供调试，不算门禁通过"
fi

PASS=0
FAIL=0
declare -a ROUND_RESULTS

# ---------- 单轮实测 ----------
run_round() {
    local round="$1"
    local log="$GATE_LOG_DIR/round-${round}.log"
    echo ""
    echo "────── 第 ${round}/${ROUNDS} 轮实测 ──────"
    if bash "$GATE_DIR/test_install.sh" > "$log" 2>&1; then
        ROUND_RESULTS[$round]="✅ PASS"
        PASS=$((PASS + 1))
        echo "  ✅ 第 ${round} 轮通过（$(grep -o '结果: [0-9]* 通过 / [0-9]* 失败' "$log" | head -1 || echo '全断言过')）"
    else
        ROUND_RESULTS[$round]="❌ FAIL"
        FAIL=$((FAIL + 1))
        echo "  ❌ 第 ${round} 轮失败！日志: ${log#$PROJECT_DIR/}"
        echo "     --- 失败详情 ---"
        tail -20 "$log" | sed 's/^/     /'
        echo "     ---------------"
    fi
}

# ---------- 静态安全检查 ----------
static_checks() {
    echo ""
    echo "────── 静态安全检查 ──────"
    local ok=1
    local hits

    # 1. 个人路径硬编码（允许 docs 里 <username> 示例 / plist 模板 __HOME__）
    #    排除 tests/ 自身（门禁脚本内含扫描模式字符串，会自指误报）
    hits=$(grep -rn "xiaoxu" "$PROJECT_DIR" \
        --include="*.sh" --include="*.py" --include="*.plist" --include="*.template" \
        --include="*.json" --include="*.yaml" --include="*.yml" 2>/dev/null \
        | grep -v "/.git/" | grep -v "/tests/" || true)
    if [ -n "$hits" ]; then
        echo "  ❌ 发现个人路径 xiaoxu 残留:"
        echo "$hits" | sed 's/^/     /'
        ok=0
    else
        echo "  ✅ 无个人路径硬编码"
    fi

    # 2. 旧仓库名残留（README 里"更名"历史说明允许保留）
    #    排除 tests/ 自身（门禁脚本内含扫描模式字符串，会自指误报）
    hits=$(grep -rn "agent-max-memory\|Roader96/Hermes-Mind" "$PROJECT_DIR" \
        --include="*.sh" --include="*.py" --include="*.plist" --include="*.template" \
        --include="*.json" --include="*.yaml" --include="*.yml" 2>/dev/null \
        | grep -v "/.git/" | grep -v "/tests/" || true)
    if [ -n "$hits" ]; then
        echo "  ❌ 发现旧仓库名残留:"
        echo "$hits" | sed 's/^/     /'
        ok=0
    else
        echo "  ✅ 无旧仓库名残留"
    fi

    # 2.5 个人痕迹扫描（开源发布：不得出现个人称呼/个人项目名/用户名）
    #    排除 tests/ 自身（门禁脚本内含扫描模式字符串，会自指误报）
    hits=$(grep -rn "哥\b\|Roader\b\|NAS\b\|3D打印\|亿纬\|Bambu\|群晖\|铁威马\|小红书" "$PROJECT_DIR" \
        --include="*.md" --include="*.sh" --include="*.py" --include="*.html" \
        --include="*.template" --include="*.json" 2>/dev/null \
        | grep -v "/.git/" | grep -v "/tests/" \
        | grep -v "github.com/Roader96" \
        | grep -v 'SELF_PREFIX\|startswith(("roader' \
        | grep -v '"roader", "Roader"' || true)
    if [ -n "$hits" ]; then
        echo "  ❌ 发现个人痕迹残留:"
        echo "$hits" | sed 's/^/     /'
        ok=0
    else
        echo "  ✅ 无个人痕迹（哥/Roader/个人项目名）"
    fi

    # 3. API 密钥 / token（扫描常见模式，不打印命中内容只报文件）
    hits=$(grep -rn "ghp_[A-Za-z0-9]\|sk-[A-Za-z0-9]\|api_key\s*=\s*['\"][^'\"]\{16,\}\|token\s*=\s*['\"][^'\"]\{16,\}\|FEISHU_WEBHOOK\|feishu.*webhook.*https" \
        "$PROJECT_DIR/scripts" 2>/dev/null | grep -v "/.git/" || true)
    if [ -n "$hits" ]; then
        echo "  ❌ 发现疑似密钥/令牌（仅列文件名）:"
        echo "$hits" | cut -d: -f1 | sort -u | sed 's/^/     /'
        ok=0
    else
        echo "  ✅ 无密钥/令牌泄漏"
    fi

    # 4. 语法检查（bash + python 全量）
    local syn_ok=1
    while IFS= read -r f; do
        if [[ "$f" == *.sh ]] && ! bash -n "$f" >/dev/null 2>&1; then
            echo "  ❌ bash 语法错误: $f"; syn_ok=0
        fi
        if [[ "$f" == *.py ]]; then
            if ! python3 -m py_compile "$f" >/dev/null 2>&1; then
                echo "  ❌ python 语法错误: $f"; syn_ok=0
            fi
        fi
    done < <(find "$PROJECT_DIR/scripts" "$PROJECT_DIR/install.sh" "$PROJECT_DIR/uninstall.sh" -type f \( -name "*.sh" -o -name "*.py" \) 2>/dev/null)
    if [ "$syn_ok" = "1" ]; then
        echo "  ✅ 全部脚本语法正确"
    else
        echo "  ❌ 存在语法错误"; ok=0
    fi

    # 5. git 工作区干净（发布前必须已提交）
    if [ -d "$PROJECT_DIR/.git" ]; then
        local dirty
        dirty=$(cd "$PROJECT_DIR" && git status --porcelain | grep -v "^??" | head -5 || true)
        if [ -n "$dirty" ]; then
            echo "  ⚠️  工作区有未提交的修改（发布前需先提交）:"
            echo "$dirty" | sed 's/^/     /'
            # 未提交修改不阻断门禁本身，但记录警告
        else
            echo "  ✅ 工作区已提交（除新文件外）"
        fi
    fi

    [ "$ok" = "1" ] && echo "  ✅ 静态检查全部通过" || echo "  ❌ 静态检查未通过"
    return $([ "$ok" = "1" ] && echo 0 || echo 1)
}

# ---------- 主流程 ----------
echo "═══════════════════════════════════════════"
echo "🚨 发布门禁 · 三次实测 + 静态安全检查"
echo "项目: $(basename "$PROJECT_DIR")"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════"

[ "$ROUNDS" = "3" ] && rm -f "$GATE_PASSED_FILE" "$GATE_RESULT_FILE"

for i in $(seq 1 "$ROUNDS"); do
    run_round "$i"
done

STATIC_OK=0
static_checks && STATIC_OK=1

# ---------- 适配层门禁（跨 agent） ----------
echo ""
echo "────── Agent 适配层门禁（跨 agent 兼容）──────"
ADAPTER_OK=0
if bash "$GATE_DIR/test_adapter.sh" > "$GATE_LOG_DIR/adapter.log" 2>&1; then
    ADAPTER_OK=1
    echo "  ✅ 适配层门禁通过（$(grep -o '结果: [0-9]* 通过 / [0-9]* 失败' "$GATE_LOG_DIR/adapter.log" | head -1 || echo '全部断言过')）"
else
    echo "  ❌ 适配层门禁失败！日志: ${GATE_LOG_DIR#$PROJECT_DIR/}/adapter.log"
    tail -15 "$GATE_LOG_DIR/adapter.log" | sed 's/^/     /'
fi

# ---------- 引用完整性门禁（缺失脚本防开箱即坏） ----------
echo ""
echo "────── 引用完整性门禁（缺失脚本检测）──────"
REFS_OK=0
if bash "$GATE_DIR/test_references.sh" > "$GATE_LOG_DIR/references.log" 2>&1; then
    REFS_OK=1
    echo "  ✅ 引用完整性通过（$(grep -o '结果: [0-9]* 通过 / [0-9]* 失败' "$GATE_LOG_DIR/references.log" | head -1 || echo '全部断言过')）"
else
    echo "  ❌ 引用完整性失败！日志: ${GATE_LOG_DIR#$PROJECT_DIR/}/references.log"
    tail -15 "$GATE_LOG_DIR/references.log" | sed 's/^/     /'
fi

# ---------- 核心逻辑单测 ----------
echo ""
echo "────── 核心逻辑单测（纯函数）──────"
UNIT_OK=0
if python3 "$GATE_DIR/test_core_logic.py" > "$GATE_LOG_DIR/unit.log" 2>&1; then
    UNIT_OK=1
    echo "  ✅ 单测通过（$(grep -c 'ok$' "$GATE_LOG_DIR/unit.log" 2>/dev/null || echo '?') 个断言）"
else
    echo "  ❌ 单测失败！日志: ${GATE_LOG_DIR#$PROJECT_DIR/}/unit.log"
    tail -15 "$GATE_LOG_DIR/unit.log" | sed 's/^/     /'
fi

# ---------- 汇总 ----------
echo ""
echo "═══════════════════════════════════════════"
echo "门禁汇总:"
for i in $(seq 1 "$ROUNDS"); do
    echo "  第 ${i} 轮: ${ROUND_RESULTS[$i]:-未跑}"
done
echo "  静态检查: $([ "$STATIC_OK" = "1" ] && echo '✅ PASS' || echo '❌ FAIL')"
echo "  适配层:   $([ "$ADAPTER_OK" = "1" ] && echo '✅ PASS' || echo '❌ FAIL')"
echo "  引用完整: $([ "$REFS_OK" = "1" ] && echo '✅ PASS' || echo '❌ FAIL')"
echo "  核心单测: $([ "$UNIT_OK" = "1" ] && echo '✅ PASS' || echo '❌ FAIL')"
echo "═══════════════════════════════════════════"

if [ "$ROUNDS" = "3" ] && [ "$FAIL" = "0" ] && [ "$STATIC_OK" = "1" ] && [ "$ADAPTER_OK" = "1" ] && [ "$REFS_OK" = "1" ] && [ "$UNIT_OK" = "1" ]; then
    echo "「${PASS}」→ 写入门禁通过标记"
    date '+%Y-%m-%d %H:%M:%S%z' > "$GATE_PASSED_FILE"
    echo "PASS: $PASS/3 rounds + static + adapter + refs + unit, $(date '+%Y-%m-%d %H:%M:%S')" > "$GATE_RESULT_FILE"
    echo ""
    echo "🎉 门禁通过！可以发布 ✅"
    exit 0
else
    echo "FAIL: rounds=$FAIL/$ROUNDS static=$STATIC_OK adapter=$ADAPTER_OK refs=$REFS_OK unit=$UNIT_OK" > "$GATE_RESULT_FILE"
    echo ""
    echo "🚫 门禁未通过！禁止发布 ❌"
    echo "   失败: rounds=$FAIL/$ROUNDS, static=$([ "$STATIC_OK" = "1" ] && echo '过' || echo '挂'), adapter=$([ "$ADAPTER_OK" = "1" ] && echo '过' || echo '挂'), refs=$([ "$REFS_OK" = "1" ] && echo '过' || echo '挂'), unit=$([ "$UNIT_OK" = "1" ] && echo '过' || echo '挂')"
    echo "   详细日志: $GATE_LOG_DIR/"
    exit 1
fi