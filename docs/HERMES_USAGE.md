# Hermes 使用说明

本文档说明如何在 Hermes 中安装、验证和日常使用本项目。

## 1. 安装

```bash
git clone https://github.com/Roader96/agent-memory-driven-evolution.git
cd agent-memory-driven-evolution
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

## 6. 故障排查

- 周审显示降级：先检查 `python3 scripts/skill_evolution/metrics.py` 和 Hermes `state.db` 是否可读。
- 自定义路径不生效：在同一 shell 中同时设置 `HERMES_HOME` 和 `HERMES_VAULT`。
- 不要直接编辑 `state.json`；优先使用 `approve.py`、`approve_pref.py` 和验证脚本。
- 删除前先运行 `uninstall.sh --keep-vault`，确认 Vault 备份存在。
