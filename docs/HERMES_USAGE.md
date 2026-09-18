# Hermes 使用说明

本文档说明如何在 Hermes 中安装、验证和日常使用本项目。

## 1. 安装

```bash
git clone https://github.com/Roader96/xxzAgentMemory.git
cd xxzAgentMemory
./install.sh --yes --no-cron
```

如果需要每周自动运行，再执行一次不带 `--no-cron` 的安装。自定义路径时：

```bash
HERMES_HOME="$HOME/.hermes" \
HERMES_VAULT="$HOME/HermesMemory" \
./install.sh --yes
```

Obsidian 插件配置会被初始化；Smart Connections 仍需在 Obsidian 中实际安装并启用。

## 2. 安装后验证

在项目目录执行：

```bash
tests/gate_multilayer.sh
```

该门禁包含静态安全、核心单测、隔离安装/归档测试和 Hermes `state.db` 只读探针。四层全部通过后，才建议启用定时任务。

## 3. 归档记忆

```bash
HERMES_VAULT="$HOME/HermesMemory" \
  ~/.hermes/scripts/smart_archive.sh \
  "本次任务标题" \
  $'## 摘要\n这里写至少十个字符的任务摘要。\n## 完成内容\n这里写完成内容。\n## 产出物\n这里写文件路径。' \
  daily
```

归档脚本会阻止目录穿越、避免同名覆盖，并使用原子写入。非法项目标签应修正后重试，不要依赖自动分类猜测。

## 4. 手动运行周审

```bash
python3 ~/.hermes/scripts/skill_evolution/run_weekly.py
```

默认只生成技能进化提案（cap dry-run），不会自动禁用技能。查看候选：

```bash
python3 ~/.hermes/scripts/skill_evolution/approve.py list
python3 ~/.hermes/scripts/skill_evolution/cap_enforcer.py
```

确认后才执行：

```bash
python3 ~/.hermes/scripts/skill_evolution/approve.py approve P001
```

如确实需要自动 cap，必须显式设置：

```bash
AUTO_APPLY_CAP=1 python3 ~/.hermes/scripts/skill_evolution/run_weekly.py
```

## 5. Hermes 适配

Hermes 模式使用 `state.db` 统计会话和技能；其他 Agent 使用 Generic 降级模式。Generic 模式没有真实使用量时不会自动禁用技能。

可用环境变量：

```bash
export HERMES_HOME="$HOME/.hermes"
export HERMES_VAULT="$HOME/HermesMemory"
export AGENT_TYPE=auto
```

## 6. Codex 结构化记忆（独立于 Hermes Agent 和 HermesMemory）

Codex 会话使用独立的 `~/CodexMemory/` 命名空间，不写入 `~/HermesMemory/codex/`。归档器同时读取 Codex 的活动会话和已归档会话，按 `session_id` 去重，并为每个会话生成任务、决策、产出、验证证据、待办/风险和用户纠正卡片。

运行时只依赖 Python 标准库和 `~/.codex/` 下的 JSONL 会话；不依赖 Hermes Agent、Hermes `state.db`、Hermes LLM 配置、`~/.hermes`、`~/HermesMemory` 或 Obsidian。Obsidian 只用于人工浏览 Markdown 记忆。

只安装/修复 Codex 这套独立维护：

```bash
./install_codex_memory.sh --yes
# 自定义路径：
./install_codex_memory.sh --yes \
  --memory-home "$HOME/CodexMemory" \
  --codex-home "$HOME/.codex"
```

安装后的独立布局：

```text
~/CodexMemory/
├── bin/codex_memory.py
├── bin/codex_memory_maintenance.sh
├── run_maintenance.sh
├── logs/
├── locks/
└── sessions/
```

安装后手动重建全部 Codex 会话：

```bash
CODEX_HOME="$HOME/.codex" \
CODEX_MEMORY_HOME="$HOME/CodexMemory" \
  python3 "$HOME/CodexMemory/bin/codex_memory.py"
```

关键词召回已生成的会话卡：

```bash
CODEX_MEMORY_HOME="$HOME/CodexMemory" \
python3 "$HOME/CodexMemory/bin/codex_memory.py" \
  --recall "运行态仿真"
```

手动运行维护入口：

```bash
"$HOME/CodexMemory/run_maintenance.sh"
```

macOS 定时任务使用独立 label `com.codex.memory`（每天 23:55）。安装器会自动卸载旧的 `com.codex.hermes-memory`，避免重复任务。Hermes 每日看门狗不再调用 Codex 维护；两者没有共享调度、日志或锁。删除 `~/.hermes` 或 `~/HermesMemory` 后，Codex 自己的 LaunchAgent 和 `~/CodexMemory/bin` 仍可运行。

产物位于 `~/CodexMemory/`：`.index/sessions.jsonl` 是机器可检索索引，`sessions/<日期>/<会话>/memory.md` 是单会话卡片，`OPEN-ITEMS.md`、`DECISIONS.md` 和 `projects/` 是导航索引。助手的过程性“我先/下一步”消息不会进入产出区；仅有 `task_complete` 生命周期事件也不算独立验证，没有工具验证的内容会明确标为助手声称，不冒充已验证事实。

运行 `./uninstall.sh --keep-vault` 卸载 Hermes 时，卸载器不会删除、迁移或停用 `~/CodexMemory` 与 `com.codex.memory`。如果手动删除 `~/CodexMemory`，Codex 派生卡片和索引会删除；原始 Codex JSONL 仍在 `~/.codex/`，之后可用独立安装器重建。

## 7. 故障排查

- 周审显示降级：先检查 `python3 scripts/skill_evolution/metrics.py` 和 Hermes `state.db` 是否可读。
- 自定义路径不生效：在同一 shell 中同时设置 `HERMES_HOME` 和 `HERMES_VAULT`。
- 不要直接编辑 `state.json`；优先使用 `approve.py`、`approve_pref.py` 和验证脚本。
- 删除前先运行 `uninstall.sh --keep-vault`，确认 Vault 备份存在。
