---
name: hermes-auto-memory-archiving
description: Hermes 冷/热记忆双层自动归档 v3 (含 Obsidian vault 后处理)。新增：1) 智能识别新话题自动建目录 2) 混合触发频率（每5轮/30分钟/热记忆阈值）3) 实时归档钩子 4) vault_postprocess 自动注入反向链接+项目时间线+INDEX 5) Smart Connections 语义搜索。热记忆超 1500 字符立即告警并迁移。
---

# Hermes 自动记忆归档 v3

## 核心原则
**所有上下文零丢失 + 不塞爆 system prompt + 无需哥提醒 + 可视化冷库 + 最小改动**

## 三层防护

### 🔥 热记忆（hot）
- 位置：`~/.hermes/memories/MEMORY.md`
- 限制：**< 1500 字符**（68%），硬上限 2200
- 注入：每轮自动
- 维护：`update_hot_used.sh <字符数>`

### 🧊 冷记忆（cold）
- 位置：`~/Documents/HermesMemory/`（Obsidian vault）
- 限制：无上限
- 召回：`recall.sh` / Obsidian 搜 / Smart Connections 语义搜
- 后处理：归档后自动跑 `vault_postprocess.py`（反向链接+时间线+INDEX）

### ⚡ 实时归档（hot→cold）
- 触发点：
  - **每 5 轮** → 无条件小快照
  - **每 30 分钟** → 强制中快照
  - **热记忆 > 1500 字符** → 迁移低频项
  - **热记忆 > 1800 字符** → 紧急迁移
  - **新话题首次出现** → 智能建项目子目录

## 智能分类（smart_archive.sh v2）

调用时**传项目标签**（推荐）：
```bash
smart_archive.sh "标题" "内容" "3D打印"   # → projects/3D打印/
smart_archive.sh "标题" "内容" "preferences"  # → preferences/
smart_archive.sh "标题" "内容" "incidents"    # → incidents/
smart_archive.sh "标题" "内容" ""              # → 兜底 daily + 启发
```

**归档后自动跑** `vault_postprocess.py`（无需手动触发）。

## Vault 后处理（vault_postprocess.py）

每次新增归档文件后自动跑，干 **5 件事**：

### 1. 反向链接注入
- 扫所有 .md 提取标题
- 给每个文件底部追加 `## 相关链接` 段
- 内容：[[INDEX]] + 同目录所有兄弟文件
- 在 Obsidian 里 `Cmd+点击` 跳转

### 2. 项目时间线生成
- 遍历 `projects/*/`
- 生成 `TIMELINE.md`（按文件名日期排序）
- 自动列出所有归档条目
- 集成到 INDEX.md

### 3. INDEX.md 维护
- 自动重写
- 包含完整目录树 + 项目列表 + 统计
- 包含快捷键表 + 已装插件列表
- 包含自动化脚本说明

### 4. README.md 维护
- vault 的"门面"文件
- 包含 6 项统计（总归档/项目/偏好/踩坑/每日/最近更新）
- 最近 5 条归档（带跳转链接）
- 完整目录结构图
- 使用说明 + 自动化说明

### 5. 错误统计（ERRORS.md + errors.json）
- 每次后处理自动读 `.checkpoints/errors.json` 生成报告
- 按类别分布表（百分比）
- 错误时间线（最近 10 条）
- 高频错误 Top 5
- 调试建议映射
- **如何记录错误**：
  ```python
  from vault_postprocess import log_error
  log_error("类别", "消息", "详情")
  ```

**手动跑**：`python3 ~/.hermes/scripts/vault_postprocess.py`

## 实时归档钩子

每次对话后我会执行：
```bash
auto_archive_hook.sh check
```

返回：
- `✅ 正常` — 啥也不用做
- `🔔 snapshot_5turn` — 写一次会话小结
- `🔔 snapshot_30min` — 写一次完整快照
- `⚠️ migrate_hot` — 热记忆告警，迁移低频项
- `🚨 urgent_migrate` — 紧急迁移

## 目录结构

```
~/Documents/HermesMemory/
├── README.md / INDEX.md / app.json
├── daily/                ← 每日会话摘要
├── preferences/          ← 偏好（永久）
├── incidents/            ← 踩坑+修复
├── projects/
│   ├── 3D打印/
│   │   ├── TIMELINE.md   ← 自动生成
│   │   ├── 2026-06-08-我的新玩具-3D-打印小恐龙.md
│   │   └── 2026-06-08-3D-打印材料对比.md
│   └── NAS/
│       ├── TIMELINE.md
│       └── ...
├── .obsidian/
│   ├── app.json / community-plugins.json
│   └── plugins/
│       └── smart-connections/   ← 语义搜索插件
└── .checkpoints/         ← hook 状态
```

## 召回流程

1. 收到问题
2. 看热记忆（已有上下文）
3. 涉及历史细节 → `session_search` / `recall.sh`
4. 涉及项目档案 → 查 `projects/<X>/TIMELINE.md`
5. 语义搜 → Obsidian Smart Connections（右侧面板）
6. 找不到 → 老实说不知道

## 频率对比

| 旧版 v1 | v2 | **v3** |
|---------|----|----|
| 每天 1 次快照 | 每 5 轮 + 每 30 分钟 | **+ 后处理自动** |
| 4 个固定分类 | 自动识别新项目 | **+ 反向链接+时间线** |
| 手动找历史 | recall.sh 关键词 | **+ Smart Connections 语义搜** |
| 热记忆满了才丢 | 1500 字符预警告 | 不变 |

## 工具脚本清单

| 脚本 | 用途 | 调用时机 |
|------|------|----------|
| `smart_archive.sh` | 智能归档（自动触发后处理） | 我主动调 |
| `vault_postprocess.py` | 反向链接+时间线+INDEX+README+ERRORS | smart_archive 自动调 |
| `auto_archive_hook.sh` | 实时归档钩子 | 每轮结束 |
| `update_hot_used.sh` | 热记忆计数维护 | 写完热记忆后 |
| `recall.sh` | 关键词召回冷记忆 | 我需要找历史时 |
| `auto_log_error.py` | 全局错误自动记录 | 任何 python 脚本 / agent |
| `daily_summary.sh` | 每日 23:50 总结 | cron 自动 |
| `save_to_memory.sh` | 旧版（兼容保留） | 不再主动用 |
| `auto_daily_snapshot.sh` | 旧版（兼容保留） | 被 hook 取代 |

## Obsidian 必备配置

- **Vault 位置**：`~/Documents/HermesMemory/`
- **社区插件**：`smart-connections`（v4.5.3+）
- **零 API key**：Smart Connections 用本地 ONNX 嵌入模型
- **首次启用**：会自动下载 ~30MB 模型到 `.obsidian/plugins/smart-connections/`

## 验证 checklist

- [ ] `recall.sh "关键词"` 有结果
- [ ] `auto_archive_hook.sh status` 显示正确用量
- [ ] 5 轮后自动 snapshot
- [ ] 热记忆超 1500 立即告警
- [ ] 新话题首次提到自动建 projects/XXX/ 目录
- [ ] 新归档后底部有 `## 相关链接` 段
- [ ] 每个 project/XXX/ 下有 `TIMELINE.md`
- [ ] INDEX.md 始终含完整目录树
- [ ] Obsidian Smart Connections 面板能搜到相关笔记

## 故障排查

| 现象 | 原因 | 修复 |
|------|------|------|
| smart_archive 不写文件 | 标签为空 + 启发也没匹中 | 显式传标签 |
| 反向链接没出现 | 没跑 vault_postprocess | 手动 `python3 ~/.hermes/scripts/vault_postprocess.py` |
| 热记忆计数不准 | 没调 update_hot_used | 写完热记忆后调一次 |
| Obsidian 看不到 vault | app.json 缺失 | 已有此文件，无需处理 |
| Smart Connections 装上不工作 | Restricted Mode 没关 | 删 community-plugins.json 重启 |
| **daily 快照被误归到 projects/某项目/** | 标题/内容含已有项目名（NAS/3D打印等），项目归并匹中 | 传更精确的标签（preferences/incidents/daily 强优先于项目名），或在 smart_archive.sh 里加"daily/preferences/incidents 标签绝对优先"逻辑 |

## 重要：不要过度工程 ⚠️

**哥硬规则**：**要 X 只做 X**——收到优化/调整指令时，**先问"最小改动是什么"**，然后只做那个。

### ❌ 反模式（不要做）
- 哥说"多读一份 X" → 我去重写整个 skill + 加新 skill + 改数据流
- 哥说"加 Y" → 我额外加 Z（没要的）
- 哥没让提炼 → 我主动提炼新 skill
- 哥没让改报告 → 我顺便改报告格式
- 哥说"优化 A" → 我顺带把 B/C/D 也优化了

### ✅ 正模式
- 哥说"多读一份 X" → 就改 1 行加个 read 调用
- 哥说"加 Y" → 只加 Y
- 不确定时 → **先问**哥要不要扩 scope
- 看到可提炼的 → **先报告**，**不要主动**改 skill

### 如何判断
- 改动 >3 个文件 → ❌ 可能过度
- 改动 ≥1 个未请求的 skill → ❌ 几乎肯定过度
- 哥明确说了"X 就行" → ✅ 按 X 做，不多不少

### 已犯的错（沉淀在 incidents/）
- `反思-最小改动原则.md` — 哥纠错 3 次后写的
- `自我提升v1原生版.md` — 误把 OpenClaw 框架当 Hermes 原生
- `优化自我提升.md` — 多读一份就够，我重写 skill + 提炼新 skill

## 重要：诚实原则

**找不到历史 = 说不知道，不要编**。宁可召回失败承认"我查不到这个"，也不要编造内容。系统有兜底（grep/obsidian 搜），但兜底也找不到就是真没有。

## 错误记录使用指南

### Python 脚本里记录
```python
import sys
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from auto_log_error import log_error, log_exception

# 方式 1: 手动记
log_error("类别", "简短消息", "详细堆栈/上下文")

# 方式 2: 自动捕获当前异常
try:
    risky_operation()
except Exception:
    log_exception("类别", "前缀: ")
```

### CLI 记录
```bash
~/.hermes/scripts/auto_log_error.py "类别" "消息" "详情"
echo "详情" | ~/.hermes/scripts/auto_log_error.py "类别" "消息"
```

### 自动汇总
- 下次 `vault_postprocess.py` 跑时自动生成 `ERRORS.md` 报告
- 不用手动触发

### 错误类别建议
| 类别 | 用于 |
|------|------|
| `smart_archive` | 归档脚本异常 |
| `vault_postprocess` | 后处理异常 |
| `hook` | hook 异常 |
| `cron` | 定时任务异常 |
| `tool_failure` | 工具调用失败 |
| `test` | 测试用 |
