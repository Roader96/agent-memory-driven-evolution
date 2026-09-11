# 🧠 agent-memory-driven-evolution

> **以永久记忆推动 Agent 自进化** · 零丢失 · 智能分层 · 语义搜索 · 自我进化
>
> 记忆不是终点，是进化的燃料。

<!-- v2.1.0 release --><div id="latest-updates"></div>

## 📢 最新更新（2026-09-11）

- 🏷️ 正式更名 **`agent-memory-driven-evolution`** —— 以永久记忆推动 Agent 自进化
- 🚀 **v2.1.0 发布**：双进化方向齐活（技能自进化 + 记忆自进化）
- 🌱 新增【技能自进化系统】skill_evolution（Ratchet + mem0 + agent-memory-loop）
- 🧠 记忆系统升级 v3：看门狗静默 / 冷库联动 / 归档标准 v2 / 偏好挖掘主航道

<sub>v2.1.0 · 2026-09-11</sub>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-26%2B-blue)](https://www.apple.com/macos)
[![Linux](https://img.shields.io/badge/Linux-Ubuntu%2FDebian%2FArch-orange)](https://www.linux.org)
[![Obsidian](https://img.shields.io/badge/Obsidian-1.12%2B-7c3aed)](https://obsidian.md)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776ab)](https://python.org)

[English](#-english) | [中文](#-中文)

---

## 📖 中文

### 💡 核心理念

**Agent 不会凭空进化，它靠记忆进化。**

每次会话产生的经验，都被永久记忆系统**零丢失沉淀**；沉淀下来的记忆，再通过**两个进化方向**反哺 Agent 本身——让 Agent 越用越懂你、越用越强。

> 记忆（燃料）→ 沉淀/提炼（记忆自进化）→ 驱动技能生长（技能自进化）→ 更强的 Agent → 产生更多高质量记忆 → 🌀 正向循环

### 🔄 两个进化方向（别漏）

| | 方向一：🧠 记忆自进化 | 方向二：🌱 技能自进化 |
|---|---|---|
| **做什么** | 把对话经验沉淀成**结构化记忆**，提炼你的偏好 | 让**技能库自己生长**：退役烂技能、修复坏技能、提案新技能 |
| **关键模块** | `auto_archive_hook` 实时归档 · `smart_archive` 智能分层 · `canonicalize` 错误归一 · `preference_miner` 偏好挖掘（主航道） | `metrics` 用量统计 · `curator` 规则提案 · `librarian` LLM 周审 · `cap_enforcer` 数量收敛 · `followup` 效果回测 |
| **产出** | 热/冷双层记忆、偏好候选、可搜索知识库 | 每周周报 + 提案队列（只提案，人工审批） |
| **节奏** | 每 5 轮 / 30 分钟 / 每日 | 每周日 21:30（launchd） |
| **效果** | 永不遗忘 + 越来越懂你 | 技能越用越精，不犯重复错 |

**闭环关系**：记忆自进化【沉淀经验】→ 喂给技能自进化【提炼规则】→ 技能进化反哺记忆【更好的交互 → 更高质量的经验】。两条腿走路，缺一不可。

### 🎯 核心能力

| 能力 | 说明 |
|------|------|
| **零丢失** | 所有对话上下文自动存档，会话结束 ≠ 记忆结束 |
| **双层架构** | 热记忆（每轮注入）+ 冷记忆（Obsidian vault 无上限）|
| **智能分类** | 自动识别新话题、建项目子目录 |
| **实时归档** | 每 5 轮 / 30 分钟 / 阈值告警自动触发 |
| **语义搜索** | Obsidian Smart Connections 插件，本地 ONNX 模型，零 API key（Obsidian 必需）|
| **反向链接** | Obsidian 风格 wikilinks 自动注入 |
| **技能自进化** | 每周审计技能库：退役/修复/提案，只提案不擅自改（Ratchet）|
| **偏好挖掘** | 从纠正信号学用户习惯 → 偏好候选 → 人工审批后生效 |
| **每日成长检查** | 自省段 + 纠正信号扫描 + 复发检测 |

### 🤖 Agent 兼容性（当前实现：Hermes）

本系统**官方实现基于 [Hermes agent](https://hermes-agent.nousresearch.com)**（会话库 `state.db` + LLM 调用 + 会话归档）。

**其他 agent（Claude Code / Codex / Cursor / 自定义）无需改代码**即可使用——通过内置**适配层**（`scripts/adapters/agent_adapter.py`）自动降级：

| 能力 | Hermes（官方实现） | 其他 agent（自动降级） |
|------|------|------|
| 环境检测 | 检测到 `state.db` → Hermes 模式 | 无 → 通用模式 |
| 技能统计 | 从会话库精确统计 | 目录扫描（结构完整，统计为 0） |
| LLM 调用 | `hermes chat` | 执行 `AGENT_LLM` 命令（stdin/stdout） |
| 会话归档 | `hermes sessions archive` | 文件移动（幂等） |

```bash
# 其他 agent 接入（3 步）
export AGENT_LLM="your-llm-cli"     # ① 你的 LLM 命令
export HERMES_HOME=~/.your-agent    # ② 你的数据目录（可选）
./install.sh                         # ③ 正常安装
```

📖 详见 [docs/AGENT_ADAPTATION.md](docs/AGENT_ADAPTATION.md)

### 📦 包含（v2.1.0）

```
agent-memory-driven-evolution/
├── install.sh                    # ★ 一键安装器（macOS / Linux）
├── uninstall.sh                  # ★ 卸载器（备份 + 可保留 vault）
├── scripts/                      # 归档 + 自进化脚本
│   ├── lib/platform.sh           # ★ 平台兼容层（date/stat/sed/launchd↔cron）
│   ├── smart_archive.sh          # 智能归档（核心）
│   ├── vault_postprocess.py      # 后处理（5 件事）
│   ├── auto_archive_hook.sh      # 实时归档钩子（方向一）
│   ├── update_hot_used.sh        # 热记忆计数
│   ├── recall.sh                 # 关键词召回
│   ├── auto_log_error.py         # 全局错误记录
│   ├── scan_learnings.py         # 每日扫高频
│   ├── daily_summary.sh          # 每日总结
│   └── skill_evolution/          # ★ 方向二：技能自进化系统
│       ├── run_weekly.py         # 编排器
│       ├── metrics.py            # 技能用量统计
│       ├── canonicalize.py       # 错误模式归一化
│       ├── outcome_scorer.py     # 会话收尾打分
│       ├── curator.py            # 规则提案（退役/修复）
│       ├── librarian.py          # LLM 周审（提案入队）
│       ├── preference_signals.py # 偏好信号挖掘（方向一→二 的桥）
│       ├── preference_miner.py   # 偏好候选归纳
│       ├── approve.py            # 提案审批 CLI
│       ├── approve_pref.py       # 偏好审批 CLI
│       ├── cap_enforcer.py       # 技能数硬 cap
│       ├── followup.py           # 提案效果追踪
│       └── verify_evolution_pipeline.py  # 验证器
├── tests/
│   └── test_install.sh           # ★ 安装/卸载集成测试（13 断言）
├── skills/                       # 2 个核心 skill
│   ├── user-auto-memory-archiving/   # 方向一：记忆/归档自进化
│   └── user-skill-evolution/         # 方向二：技能自进化
├── docs/                         # 完整文档
│   ├── overview.html             # PPT 风格 16 slides
│   ├── installation.md
│   ├── usage.md
│   ├── architecture.md
│   └── troubleshooting.md
├── examples/
│   └── vault-sample/             # 示例 vault
├── README.md
├── LICENSE
├── CHANGELOG.md
└── .gitignore
```

### 🚀 3 步上手

#### 1. 克隆

```bash
git clone https://github.com/Roader96/agent-memory-driven-evolution.git
cd agent-memory-driven-evolution
```

#### 2. 一键安装（macOS / Linux）

```bash
./install.sh               # 交互式安装
./install.sh --yes         # 静默安装（CI 友好）
./install.sh --vault ~/MyMemory   # 自定义 vault 路径
```

> ⚠️ **Obsidian 是必需依赖**（不是可选）：它是永久记忆 vault 的载体——可视化、语义检索、反向链接全靠它。
> 安装器会**自动检测 Obsidian**，缺失时引导安装（macOS DMG / Linux AppImage），并**初始化 vault 的 Obsidian 配置**（`.obsidian/` + Smart Connections 插件位）。

安装器会自动：
- 检测平台（macOS / Linux）+ 检查依赖（bash / python3 / git / **Obsidian**）
- 复制脚本 + skills 到 `~/.hermes/`
- 创建 vault（`~/HermesMemory`，可自定义）+ 初始化 Obsidian vault 结构
- 安装定时任务（macOS: launchd → Linux: crontab）
- 验证安装完整性

#### 卸载

```bash
./uninstall.sh             # 交互式卸载
./uninstall.sh --keep-vault # 保留记忆 vault，只删系统组件
./uninstall.sh --yes        # 静默卸载
```

> 卸载会把 scripts/skills/logs 备份到 `~/.hermes-backup-<timestamp>`，不会误删你的记忆 vault（除非显式确认）。

#### 3. 初始化自进化系统（可选）

```bash
# 手动跑一次周审（首次建议手动验证）
python3 ~/.hermes/scripts/skill_evolution/run_weekly.py

# 安装器已自动装好定时任务（macOS: launchd / Linux: crontab，每周日 21:30）
# 验证: python3 ~/.hermes/scripts/skill_evolution/verify_evolution_pipeline.py
```

### 🏗 架构（记忆系统 v3）

| 层 | 位置 | 说明 |
|----|------|------|
| 🔥 热记忆 hot | `~/.hermes/memories/MEMORY.md` | < 1500 字符，每轮注入 |
| 🧊 冷记忆 cold | `~/HermesMemory/` | Obsidian vault，无上限 |
| ⚡ 实时归档 | 自动 | 5 轮 / 30 分钟 / 阈值触发（方向一）|
| 🌱 技能自进化 | `skill_evolution/` | 每周日审计技能库（方向二）|

### 📄 文档

| 文档 | 说明 |
|------|------|
| [安装](docs/installation.md) | 系统要求 + 3 步安装 |
| [使用](docs/usage.md) | 核心工作流 + 日常命令 |
| [架构](docs/architecture.md) | 设计目标 + 三层架构 |
| [故障排查](docs/troubleshooting.md) | 常见问题快速定位 |

---

## 🌐 English

### 💡 Core Idea

**An agent doesn't evolve in a vacuum — it evolves from memory.**

Every conversation is **zero-loss archived** into a persistent memory system. Those memories then feed back into the agent through **two evolution loops** — making the agent understand you better and perform better over time.

> Memory (fuel) → Archive & distill (memory evolution) → Drive skill growth (skill evolution) → A stronger agent → Higher-quality memories → 🌀 Virtuous cycle

### 🔄 The Two Evolution Loops

| | Loop 1: 🧠 Memory Evolution | Loop 2: 🌱 Skill Evolution |
|---|---|---|
| **Goal** | Distill conversations into **structured memory** & mine your preferences | Let the **skill library grow itself**: retire broken skills, fix stale ones, propose new ones |
| **Modules** | `auto_archive_hook` · `smart_archive` · `canonicalize` · `preference_miner` | `metrics` · `curator` · `librarian` · `cap_enforcer` · `followup` |
| **Output** | Hot/cold memory, preference candidates, searchable KB | Weekly report + proposal queue (human-approved) |
| **Cadence** | Every 5 turns / 30 min / daily | Weekly (Sunday 21:30, launchd) |
| **Effect** | Never forgets + understands you better | Skills sharpen, no repeated mistakes |

**Loop relationship**: Memory Evolution **archives experience** → feeds Skill Evolution **to distill rules** → better skills produce **higher-quality interactions** → better memory. Both loops must run — neither works alone.

### Core capabilities

- Zero-loss archiving (hot memory / cold vault)
- Smart auto-classification (new topics → new project dirs)
- Semantic search via Smart Connections (local ONNX, zero API keys)
- Backlinks + project timelines (Obsidian-native)
- ★ **Skill self-evolution** (weekly audit: retire / fix / propose — proposal-only, never auto-modifies)
- ★ **Preference mining** (learns your corrections → preference candidates → human approval)
- ★ **Daily growth check** (self-reflection + recurrence detection)

### Quick start

```bash
git clone https://github.com/Roader96/agent-memory-driven-evolution.git
cd agent-memory-driven-evolution
cp -R skills/* ~/.hermes/skills/
cp scripts/* ~/.hermes/scripts/
chmod +x ~/.hermes/scripts/*
```

See [docs/installation.md](docs/installation.md) for details.

---

## 📜 License

MIT — see [LICENSE](LICENSE)