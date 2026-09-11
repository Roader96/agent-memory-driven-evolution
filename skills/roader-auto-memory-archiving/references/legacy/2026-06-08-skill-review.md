# 2026-06-08 技能库反思

## 事件
哥在一次会话里**三次纠错**"过度工程"：
1. 误把 OpenClaw self-improving 框架当 Hermes 原生
2. 主动提炼 `hermes-tool-restrictions` skill（**哥没让**）
3. 重写整个 hermes-self-improvement skill（**应只改 scan_learnings 一行**）

## 提取的教训
**"要 X 只做 X"**——哥硬规则之一，但被反复违反。

## 已做的更新

### 1. 删除未请求的 skill
- ❌ `hermes-tool-restrictions`（过度工程产物）— 已删除

### 2. patch `hermes-auto-memory-archiving` SKILL.md
- 新增"重要：不要过度工程"章节
- 列出 ❌ 反模式 + ✅ 正模式 + 判断标准
- 列已犯的错（指向 incidents/）

### 3. 重写 `hermes-self-improvement` SKILL.md（最小化）
- 顶部加"⚠️ 重要：不要主动提炼 skill"
- 工作流明确：scan_learnings 只**报告**，**不动 skill**
- 删"提炼为 skill"工作流（**这正是过度工程源头**）
- 删 LEARNINGS-REVIEW.md "建议行动"表（避免主动建议）
- 加"已犯的错"清单

### 4. 更新 memory
- 加"⚠️ 哥硬规则强化-最小改动"条目
- 删 v2 完整栈（v3 替代）
- 加 Hermes logs 数据（401条历史错误）
- 加 hermes-self-improvement v1 状态

## 怎么验证下次不再犯
- 收到"加/优化/多读"指令 → 先 grep 这次反思的字眼
- 改动 >3 个文件 → 暂停确认
- 创建新 skill → 必须哥明确说"提炼"才动
