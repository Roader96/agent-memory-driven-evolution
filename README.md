# 🧠 Hermes Mind

> **AI 助手的持久化记忆系统 + 技能自进化系统** · 零丢失 · 智能分层 · 语义搜索 · 自我进化

<!-- v2.0.0 release --><div id="latest-updates"></div>

## 📢 最新更新（2026-09-11）

- 🚀 **v2.0.0 发布**：新增【技能自进化系统】skill-evolution（Ratchet + mem0 + agent-memory-loop）
- 🧠 记忆系统升级到 v3：热记忆看门狗静默模式、冷库联动、归档标准 v2
- 📈 每日成长检查：自省段 + 纠正信号挖掘 + 偏好归纳（主航道）

<sub>v2.0.0 · 2026-09-11 · GitHub CDN 缓存绕过：本次 README 顶部已更新</sub>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-26%2B-blue)](https://www.apple.com/macos)
[![Obsidian](https://img.shields.io/badge/Obsidian-1.12%2B-7c3aed)](https://obsidian.md)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776ab)](https://python.org)

[English](#-english) | [中文](#-中文)

---

## 📖 中文

**Hermes Mind** 是给 AI 助手用的**持久化记忆 + 自我进化**系统。解决"会话结束 = 上下文丢失"和"AI 不会从经验中成长"两大难题。

### 🎯 核心能力

| 能力 | 说明 |
|------|------|
| **零丢失** | 所有对话上下文自动存档 |
| **双层架构** | 热记忆（注入）+ 冷记忆（vault）|
| **智能分类** | 自动识别新话题、建项目子目录 |
| **实时归档** | 每 5 轮 / 30 分钟 / 阈值告警自动触发 |
| **语义搜索** | Smart Connections 插件，本地 ONNX 模型，零 API key |
| **反向链接** | Obsidian 风格的 wikilinks 自动注入 |
| **技能自进化** | 每周自动审计技能库：退役/修复/提案，只提案不擅自改（Ratchet 论文方法）|
| **偏好挖掘** | 从纠正信号中学用户习惯，提炼成偏好候选，人工审批后生效 |
| **每日成长检查** | 自省段 + 纠正信号扫描 + 复发检测 |

### 📦 包含（v2.0.0）

```
hermes-mind/
├── scripts/                       # 归档 + 自进化脚本
│   ├── smart_archive.sh           # 智能归档（核心）
│   ├── vault_postprocess.py       # 后处理（5 件事）
│   ├── auto_archive_hook.sh       # 实时归档钩子
│   ├── update_hot_used.sh         # 热记忆计数
│   ├── recall.sh                  # 关键词召回
│   ├── auto_log_error.py          # 全局错误记录
│   ├── scan_learnings.py          # 每日扫高频
│   ├── daily_summary.sh           # 每日总结
│   └── skill_evolution/           # ★ 新增：技能自进化系统
│       ├── run_weekly.py          # 编排器（launchd 周日 21:30）
│       ├── metrics.py             # 技能用量统计
│       ├── canonicalize.py        # 错误模式归一化
│       ├── outcome_scorer.py      # 会话收尾打分
│       ├── curator.py             # 规则提案（退役/修复）
│       ├── librarian.py           # LLM 周审（提案入队）
│       ├── preference_signals.py  # 偏好信号挖掘
│       ├── preference_miner.py    # 偏好候选归纳
│       ├── approve.py             # 提案审批 CLI
│       ├── approve_pref.py        # 偏好审批 CLI
│       ├── cap_enforcer.py        # 技能数硬 cap
│       ├── followup.py            # 提案效果追踪
│       └── verify_evolution_pipeline.py  # 验证器
├── skills/                        # 3 个核心 skill
│   ├── roader-auto-memory-archiving/   # v3 记忆归档
│   ├── roader-skill-evolution/         # ★ 自进化
│   └── (hermes-self-improvement 已并入 v3)
├── docs/                          # 完整文档
│   ├── overview.html              # PPT 风格 16 slides
│   ├── installation.md
│   ├── usage.md
│   ├── architecture.md
│   └── troubleshooting.md
├── examples/
│   └── vault-sample/              # 示例 vault
├── README.md
├── LICENSE
├── CHANGELOG.md
└── .gitignore
```

### 🚀 3 步上手

#### 1. 克隆

```bash
git clone https://github.com/Roader96/Hermes-Mind.git
cd Hermes-Mind
cp -R skills/* ~/.hermes/skills/
cp scripts/* ~/.hermes/scripts/
chmod +x ~/.hermes/scripts/*
```

#### 2. 装 Obsidian + Smart Connections

（同 v1，见 docs/installation.md）

#### 3. 初始化自进化系统（可选）

```bash
# 手动跑一次周审（首次建议手动验证）
python3 ~/.hermes/scripts/skill_evolution/run_weekly.py

# 或装 launchd 定时（每周日 21:30）
cp ~/Desktop/Project/Hermes-Mind-v2/scripts/skill_evolution/com.roader.skill-evolution-weekly.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.roader.skill-evolution-weekly.plist
```

### 🏗 架构（记忆系统 v3）

| 层 | 位置 | 说明 |
|----|------|------|
| 🔥 热记忆 hot | `~/.hermes/memories/MEMORY.md` | < 1500 字符，每轮注入 |
| 🧊 冷记忆 cold | `~/HermesMemory/` | Obsidian vault，无上限 |
| ⚡ 实时归档 | 自动 | 5 轮 / 30 分钟 / 阈值触发 |
| 🌱 自进化 | `skill_evolution/` | 每周日审计技能库 |

### 📄 文档

| 文档 | 说明 |
|------|------|
| [安装](docs/installation.md) | 系统要求 + 3 步安装 |
| [使用](docs/usage.md) | 核心工作流 + 日常命令 |
| [架构](docs/architecture.md) | 设计目标 + 三层架构 |
| [故障排查](docs/troubleshooting.md) | 常见问题快速定位 |

---

## 🌐 English

**Hermes Mind** is a persistent memory + self-evolving system for AI assistants, solving two problems:
1. **"Session ends = context lost"** — everything is archived automatically
2. **"AI doesn't learn from experience"** — a weekly skill-evolution loop audits and proposes improvements

### Core capabilities

- Zero-loss archiving (hot memory / cold vault)
- Smart auto-classification (new topics → new project dirs)
- Semantic search via Smart Connections (local ONNX, zero API keys)
- Backlinks + project timelines (Obsidian-native)
- ★ **Skill self-evolution** (weekly audit: retire / fix / propose — proposal-only, never auto-modifies)
- ★ **Preference mining** (learns user's corrections → preference candidates → human approval)
- ★ **Daily growth check** (self-reflection + recurrence detection)

### Quick start

```bash
git clone https://github.com/Roader96/Hermes-Mind.git
cd Hermes-Mind
cp -R skills/* ~/.hermes/skills/
cp scripts/* ~/.hermes/scripts/
chmod +x ~/.hermes/scripts/*
```

See [docs/installation.md](docs/installation.md) for details.

---

## 📜 License

MIT — see [LICENSE](LICENSE)