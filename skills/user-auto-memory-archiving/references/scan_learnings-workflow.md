# scan_learnings.py 工作流（来自 hermes-self-improvement v1）

> **核心原则**：冷启不犯同样错 + 最小改动——只记录 + 报告，**不主动提炼**。

## ⚠️ 重要：不要主动提炼 skill

**用户硬规则**："要 X 只做 X"——scan_learnings 只负责**报告高频项**，**不要自动创建/提炼/修改 skill**。

正确的循环是：
```
错误发生
   ↓
扫描发现高频
   ↓
报告给用户（LEARNINGS-REVIEW.md + 飞书）
   ↓
**用户决定要不要提炼**（"要"才动）
   ↓
用户说"提炼为 skill" → 才动 skill
```

**❌ 反模式**：scan_learnings 跑出 20 个候选 → 我自动提炼 1 个新 skill（**用户没让**）。

## 与 OpenClaw 无关

**纯 Hermes 原生能力**：
- ❌ 不用 OpenClaw
- ❌ 不用 ClawdHub
- ❌ 不用 .learnings/ 散文件
- ✅ 用 `memory` 工具
- ✅ 用 `smart_archive.sh`
- ✅ 用 `auto_log_error.py`

## 4 类学习来源（只记录，不提炼）

| 触发 | 类型 | 写到哪里 |
|------|------|---------|
| 用户纠正我（"不是/不要/其实应该"）| `correction` | `HermesMemory/incidents/` |
| 我发现知识过期 | `knowledge_gap` | `HermesMemory/incidents/` |
| 工具/API 失败 | `tool_failure` | `HermesMemory/.checkpoints/errors.json` |
| 发现更好做法 | `best_practice` | `HermesMemory/preferences/` |

## 工作流（最小）

```
事件发生
   ↓
1. 写入（用 Hermes 自己的工具）
   ↓
2. 每日 23:50 cron 跑 scan_learnings.py
   - 读 ~/.hermes/logs/errors.log（Hermes 主源）
   - 读 HermesMemory/.checkpoints/errors.json（冷库补充）
   - 扫 incidents/ 重复主题
   ↓
3. 生成 LEARNINGS-REVIEW.md（报告，不动 skill）
   ↓
4. 推飞书给用户（23:50 每日总结）
   ↓
5. **等用户决定**要不要提炼 → 用户说"提炼"才动 skill
```

## 使用示例

### 场景 1: 用户纠正我
用户说："不是这样，应该是 X"
```bash
~/.hermes/scripts/smart_archive.sh "学习-用户纠正XXX" \
  "我之前答错，正确是X。触发：用户说'不是这样'" \
  "incidents"
```

### 场景 2: 工具失败
```bash
~/.hermes/scripts/auto_log_error.py "tool_failure" "API xxx 失败" "stacktrace"
```

### 场景 3: 发现更好做法
```bash
~/.hermes/scripts/smart_archive.sh "最佳实践-YYY" \
  "原本用X，现在用Y更好。理由：Z" \
  "preferences"
```

## scan_learnings.py 行为规范

**做**：
- 读 `~/.hermes/logs/errors.log` 解析
- 读 `HermesMemory/.checkpoints/errors.json`
- 扫 `incidents/` 找重复主题
- 写 `LEARNINGS-REVIEW.md`
- 推飞书（通过 daily_summary cron）

**不做**：
- ❌ 自动创建新 skill
- ❌ 自动 patch 已有 skill
- ❌ 自动提升 incidents → skill
- ❌ 主动建议用户做某个提炼（除非用户明确问"有什么要改的"）

## 工具脚本

| 脚本 | 用途 |
|------|------|
| `scan_learnings.py` | 多源错误扫描 + 报告 |
| `daily_summary.sh` | 23:50 跑 scan + 推飞书 |
| `LEARNINGS-REVIEW.md` | 报告输出位置 |

## 验证 checklist

- [ ] 用户纠正后 `HermesMemory/incidents/` 有新条目
- [ ] 工具失败后 `errors.json` 有记录
- [ ] 每日 23:50 cron 跑 scan_learnings.py
- [ ] `LEARNINGS-REVIEW.md` 每日生成
- [ ] **scan_learnings 跑完不动任何 skill**（**核心**）
- [ ] 用户说"提炼" → 才动 skill

## 已犯的错（沉淀在 incidents/）

- `反思-最小改动原则.md` — 用户纠错 3 次后写的
- `自我提升v1原生版.md` — 误把 OpenClaw 框架当 Hermes 原生
- `优化自我提升.md` — 多读一份就够，我重写 skill + 提炼新 skill
- `反思-文案语病-档档.md` — 我自己造词"档档"，改回"归档"
- `会话总结-优化自我提升.md`（过度工程：主动提炼 hermes-tool-restrictions）
