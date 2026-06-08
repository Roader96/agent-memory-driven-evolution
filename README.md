# 🧠 Hermes Mind

> **AI 助手的持久化记忆系统** · 零丢失 · 智能分层 · 语义搜索

<!-- 2026-06-08 typo fix in 4 source files --><div id="latest-updates"></div>

## 📢 最新更新（2026-06-08）

- ✅ typo 修复：所有 `实时档` → `实时归档`（标准术语）
- ✅ Release notes + About 草稿已加
- ✅ 35 文件 ready

---

<sub>v1.0.1 · 2026-06-08 · 0 cache · 重新刷新生效</sub>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-26%2B-blue)](https://www.apple.com/macos)
[![Obsidian](https://img.shields.io/badge/Obsidian-1.12%2B-7c3aed)](https://obsidian.md)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776ab)](https://python.org)

[English](#-english) | [中文](#-中文)

---

## 📖 中文

**Hermes Mind** 是给 AI 助手用的**持久化记忆系统**。解决"会话结束 = 上下文丢失"这个老大难。

### 🎯 核心能力

| 能力 | 说明 |
|------|------|
| **零丢失** | 所有对话上下文自动存档 |
| **双层架构** | 热记忆（注入）+ 冷记忆（vault）|
| **智能分类** | 自动识别新话题、建项目子目录 |
| **实时归档** | 每 5 轮 / 30 分钟 / 阈值告警自动触发 |
| **语义搜索** | Smart Connections 插件，本地 ONNX 模型，零 API key |
| **反向链接** | Obsidian 风格的 wikilinks 自动注入 |
| **项目时间线** | 每个项目按时间排序 |
| **错误统计** | 自动记录 + 自动汇总 |
| **每日总结** | 23:50 cron 推飞书 DM |

### 📦 包含

```
hermes-mind/
├── scripts/                       # 10 个可执行脚本
│   ├── smart_archive.sh           # 智能归档（核心）
│   ├── vault_postprocess.py       # 后处理（5 件事）
│   ├── auto_archive_hook.sh       # 实时归档钩子
│   ├── update_hot_used.sh         # 热记忆计数
│   ├── recall.sh                  # 关键词召回
│   ├── auto_log_error.py          # 全局错误记录
│   ├── scan_learnings.py          # 每日扫高频
│   ├── daily_summary.sh           # 每日总结
│   ├── save_to_memory.sh          # 旧版兼容
│   └── auto_daily_snapshot.sh     # 旧版兼容
├── skills/                        # 3 个核心 skill
│   ├── hermes-auto-memory-archiving/
│   ├── hermes-self-improvement/
│   └── hermes-tool-restrictions/
├── docs/                          # 完整文档
│   ├── overview.html              # PPT 风格 16 slides
│   ├── installation.md
│   ├── usage.md
│   ├── architecture.md
│   └── troubleshooting.md
├── examples/
│   └── vault-sample/              # 示例 vault（5 文件）
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

#### 2. 装 Obsidian

```bash
# 下载
curl -L -o /tmp/obsidian.dmg \
  "https://github.com/obsidianmd/obsidian-releases/releases/latest/download/Obsidian.dmg"
hdiutil attach /tmp/obsidian.dmg
cp -R /Volumes/Obsidian/Obsidian.app /Applications/
```

#### 3. 装 Smart Connections 插件（语义搜索）

```bash
mkdir -p ~/Documents/HermesMemory/.obsidian/plugins/smart-connections
cd ~/Documents/HermesMemory/.obsidian/plugins/smart-connections
curl -L -o main.js "https://github.com/brianpetro/obsidian-smart-connections/releases/latest/download/main.js"
curl -L -o manifest.json ".../manifest.json"
curl -L -o styles.css ".../styles.css"
echo '["smart-connections"]' > ../community-plugins.json
```

### 🛠 配置

设置 vault 路径（可选，默认 `~/Documents/HermesMemory`）：

```bash
export HERMES_VAULT="$HOME/Documents/HermesMemory"
# 加到 ~/.zshrc 永久生效
```

### 📊 架构图

```
┌──────────────┐  每 5 轮 / 30 分钟 / 阈值告警
│  会话进行中  │ ──────────────────────────────┐
└──────────────┘                                ▼
       ↓                                ┌──────────────┐
┌──────────────┐                         │ auto_archive │
│ 热记忆 (MEMORY.md) │ ←──system prompt──│    _hook.sh  │
│ < 1500 字符  │                         └──────────────┘
└──────────────┘                                ↓
                                       ┌──────────────┐
                                       │smart_archive │
                                       │     .sh      │
                                       └──────────────┘
                                                ↓
                                       ┌──────────────┐
                                       │   vault/     │
                                       │  (Obsidian)  │
                                       └──────────────┘
                                                ↓
                                  ┌─────────────────────────┐
                                  │ vault_postprocess.py    │
                                  │ 1. 反向链接              │
                                  │ 2. 项目时间线            │
                                  │ 3. INDEX.md             │
                                  │ 4. README.md            │
                                  │ 5. ERRORS.md            │
                                  └─────────────────────────┘
```

### 📚 完整文档

- [安装指南](docs/installation.md)
- [使用手册](docs/usage.md)
- [架构设计](docs/architecture.md)
- [故障排查](docs/troubleshooting.md)
- [PPT 概览](docs/overview.html)（16 slides）

### 🤝 贡献

欢迎 PR！建议流程：
1. Fork → 新分支
2. 写代码 + 跑 `vault_postprocess.py` 测试
3. 提交 PR 时附 `ERRORS.md` 现状

### 📜 License

MIT © [Roader](https://github.com/Roader96)

---

## 🌐 English

**Hermes Mind** is a **persistent memory system for AI assistants**. It solves the classic "session ends = context lost" problem.

### Why Hermes Mind?

- **Zero loss** — every conversation archived
- **Two-tier** — hot (injected) + cold (Obsidian vault)
- **Smart classification** — auto-create project subdirs
- **Real-time archiving** — every 5 turns / 30 min / threshold
- **Semantic search** — Smart Connections plugin, local ONNX, zero API key
- **Backlinks** — Obsidian-style wikilinks auto-injected
- **Project timelines** — auto-generated per project
- **Error stats** — auto-record + auto-summarize

### Quick Start

```bash
git clone https://github.com/Roader96/Hermes-Mind.git
cd Hermes-Mind
cp -R skills/* ~/.hermes/skills/
cp scripts/* ~/.hermes/scripts/
chmod +x ~/.hermes/scripts/*

# Install Obsidian (macOS)
curl -L -o /tmp/obsidian.dmg "https://github.com/obsidianmd/obsidian-releases/releases/latest/download/Obsidian.dmg"
hdiutil attach /tmp/obsidian.dmg && cp -R /Volumes/Obsidian/Obsidian.app /Applications/

# Set up vault
mkdir -p ~/Documents/HermesMemory
# Open Obsidian → Open folder as vault → select ~/Documents/HermesMemory
```

See [docs/installation.md](docs/installation.md) for full setup.

### License

MIT © [Roader](https://github.com/Roader96)
