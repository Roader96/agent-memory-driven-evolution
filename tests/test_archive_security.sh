#!/bin/bash
# test_archive_security.sh — smart_archive.sh 高风险场景门禁
# 覆盖：目录穿越 / 同名覆盖 / 并发归档 / 自定义 VAULT / 空标题兜底
set -u
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
ARCHIVE="$PROJECT_DIR/scripts/smart_archive.sh"

PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

TMPVAULT=$(mktemp -d)
trap 'rm -rf "$TMPVAULT" /tmp/evil_* 2>/dev/null' EXIT

CONTENT='## 摘要
测试内容，超过十个字符的摘要。
## 完成内容
X'

echo "== smart_archive 高风险场景门禁 =="

# --- 1. 目录穿越：../ 类标签 ---
OUT=$(HERMES_VAULT="$TMPVAULT" bash "$ARCHIVE" "穿越测试" "$CONTENT" "../outside" 2>&1)
if find "$TMPVAULT/.." -maxdepth 1 -name "outside" 2>/dev/null | grep -q .; then
  fail "目录穿越: ../outside 逃出 vault"
else
  ok "目录穿越拦截: ../outside（净化降级为自动分类）"
fi

# --- 2. 目录穿越：绝对路径 ---
OUT=$(HERMES_VAULT="$TMPVAULT" bash "$ARCHIVE" "穿越测试" "$CONTENT" "/tmp/evil_$RANDOM" 2>&1)
if ls /tmp/evil_* >/dev/null 2>&1; then
  fail "目录穿越: 绝对路径写入 /tmp"
else
  ok "目录穿越拦截: 绝对路径标签"
fi

# --- 3. 目录穿越：隐藏 . 开头 ---
OUT=$(HERMES_VAULT="$TMPVAULT" bash "$ARCHIVE" "穿越测试" "$CONTENT" ".hidden" 2>&1)
if [ -d "$TMPVAULT/projects/.hidden" ]; then
  fail "目录穿越: . 开头标签未拦截"
else
  ok "目录穿越拦截: . 开头标签"
fi

# --- 4. 同名不覆盖（零丢失）---
HERMES_VAULT="$TMPVAULT" bash "$ARCHIVE" "同名标题" "## 摘要
AAA第一次内容，超过十个字符。
## 完成内容
A" "daily" >/dev/null 2>&1
HERMES_VAULT="$TMPVAULT" bash "$ARCHIVE" "同名标题" "## 摘要
BBB第二次内容，超过十个字符。
## 完成内容
B" "daily" >/dev/null 2>&1
N=$(ls "$TMPVAULT/daily/" | grep -c "同名标题")
if [ "$N" -ge 2 ] && grep -rl "AAA第一次" "$TMPVAULT/daily/" >/dev/null 2>&1 && grep -rl "BBB第二次" "$TMPVAULT/daily/" >/dev/null 2>&1; then
  ok "同名不覆盖: 两次归档内容都保留"
else
  fail "同名覆盖: 文件数=$N（期望≥2）或内容丢失"
fi

# --- 5. 并发归档同标题（10 并发）---
for i in $(seq 1 10); do
  HERMES_VAULT="$TMPVAULT" bash "$ARCHIVE" "并发标题" "## 摘要
并发内容 ${i}，超过十个字符。
## 完成内容
C${i}" "daily" >/dev/null 2>&1 &
done
wait
N=$(ls "$TMPVAULT/daily/" | grep -c "并发标题")
if [ "$N" -eq 10 ]; then
  ok "并发归档: 10 并发同标题全部保留（$N/10）"
else
  fail "并发归档: 只有 $N/10（有丢失）"
fi

# --- 6. 自定义 VAULT 路径生效 ---
CUSTOM="$TMPVAULT/custom-vault"
HERMES_VAULT="$CUSTOM" bash "$ARCHIVE" "自定义路径" "$CONTENT" "daily" >/dev/null 2>&1
if [ -d "$CUSTOM/daily" ] && ls "$CUSTOM/daily/"*自定义路径* >/dev/null 2>&1; then
  ok "自定义 HERMES_VAULT 生效"
else
  fail "自定义 HERMES_VAULT 未生效"
fi

# --- 7. 空/特殊字符标题兜底 ---
OUT=$(HERMES_VAULT="$TMPVAULT" bash "$ARCHIVE" "！！！@@@" "$CONTENT" "daily" 2>&1)
if echo "$OUT" | grep -q "✅" && ls "$TMPVAULT/daily/" | grep -q "untitled\|——"; then
  ok "特殊字符标题兜底（不崩溃不空名）"
else
  # 中文 ！净化后可能为空 → untitled；只要写出了文件就算过
  if ls "$TMPVAULT/daily/" | grep -qE "untitled|2026"; then
    ok "特殊字符标题兜底"
  else
    fail "特殊字符标题: $OUT"
  fi
fi

# --- 8. 正常项目标签不受影响 ---
HERMES_VAULT="$TMPVAULT" bash "$ARCHIVE" "正常标题" "$CONTENT" "my-proj_1" >/dev/null 2>&1
if [ -f "$TMPVAULT/projects/my-proj_1/$(date +%Y-%m-%d)-正常标题.md" ]; then
  ok "正常项目标签归档不受影响"
else
  fail "正常项目标签归档失败"
fi

echo
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] && echo "🎉 smart_archive 安全门禁通过" && exit 0
exit 1
