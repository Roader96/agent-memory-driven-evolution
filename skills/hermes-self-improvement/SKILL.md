---
name: hermes-self-improvement
description: Hermes 自我提升机制 v1（原生，不用 OpenClaw）。复用 Hermes 自身工具：memory 工具 + smart_archive.sh + auto_log_error.py。自动记录：哥纠正、知识过期、API失败、发现更好方案。每日 23:50 cron 扫 vault 找高频项，提炼为 skill 或合并到热记忆。
---

# Hermes 自我提升 v1（原生）

## 核心原则
**冷启不犯同样错** — 把"我犯过的错"和"学到的更好做法"沉淀成可执行资产（skill/memory 摘要）。

## 与 OpenClaw 无关
**纯 Hermes 原生能力**，不依赖任何外部平台。

## 4 类学习来源（自动检测）

| 触发信号 | 类型 | 写到哪里 | 用什么工具 |
|----------|------|---------|-----------|
| 哥纠正（"不是/不要/其实应该"）| `correction` | vault/incidents/ | `smart_archive.sh` |
| 我发现知识过期 | `knowledge_gap` | vault/incidents/ | `smart_archive.sh` |
| 工具/API 失败 | `tool_failure` | vault/.checkpoints/errors.json | `auto_log_error.py` |
| 发现更好做法 | `best_practice` | vault/preferences/ | `smart_archive.sh` |

## 标准化记录格式

```markdown
# [类别] 简述

## 上下文
- 发生了什么
- 之前做法
- 正确做法

## 行动
具体修复/改进

## 元信息
- 来源：conversation / error / user_feedback
- 优先级：low / medium / high / critical
- 状态：pending / resolved / promoted
```

## 工作流

```
事件发生 → 1. 检测触发 → 2. 用 Hermes 工具写
   ↓
3. vault_postprocess.py 自动：反向链接 + 时间线 + INDEX/README/ERRORS
   ↓
4. 每日 23:50 cron 跑 scan_learnings.py：扫高频 + 重复主题
   ↓
5. 生成 LEARNINGS-REVIEW.md
   ↓
6. Hermes 审阅：高频错误 → skill；重复主题 → 故障排查
```

## 提升路径

```
单条 learning → 出现 2+ 次 → 升级为 skill → 跨场景 → SOUL/记忆热区
```

## 提炼为 skill 的标准

- 出现 2+ 次（recurring）
- 已解决并验证（verified）
- 调试才能发现（non-obvious）
- 跨项目可用（broadly applicable）

## 错误记录使用

```python
# Python 脚本里
import sys
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from auto_log_error import log_error, log_exception

log_error("类别", "简短消息", "详细堆栈/上下文")

try:
    risky_op()
except Exception:
    log_exception("类别", "前缀: ")
```

```bash
# CLI
~/.hermes/scripts/auto_log_error.py "类别" "消息" "详情"
```

## 错误类别建议

| 类别 | 用于 |
|------|------|
| `smart_archive` | 归档脚本异常 |
| `vault_postprocess` | 后处理异常 |
| `hook` | hook 异常 |
| `cron` | 定时任务异常 |
| `tool_failure` | 工具调用失败 |
