# 📦 安装指南

## 系统要求

- **OS**：macOS 26+ / Linux（GNU coreutils：Ubuntu / Debian / Arch / Fedora 等主流发行版）
- **Python**：3.9+（系统自带或 apt/brew 安装）
- **Bash**：4.0+（macOS 自带 bash 3.2 也能跑，推荐升级到 4+）
- **Git**：用于克隆仓库
- **Obsidian**：1.12+ **（必需）** — 永久记忆 vault 的载体。没有 Obsidian 就没有可视化、语义检索、反向链接的永久记忆库。安装器会自动检测，缺失时引导安装。
- **磁盘**：< 100MB（不含个人 vault 内容）

> **Windows**：暂不支持宿主运行（脚本依赖 bash + Python 生态）。可选方案：
> - WSL2 (Windows Subsystem for Linux) —— 按 Linux 方式安装，兼容性最好
> - 在 Docker 容器内运行

## 1. 克隆项目

```bash
git clone https://github.com/Roader96/xxzAgentMemory.git
cd xxzAgentMemory
```

## 2. 只安装 Codex 独立结构化记忆（可选）

如果你不需要 Hermes Agent 的每日总结、飞书和技能周审，只希望 Codex 自动把 `~/.codex/` 会话整理成 Markdown 卡片，可使用独立安装器：

```bash
./install_codex_memory.sh --yes
```

它会把运行脚本安装到 `~/CodexMemory/bin/`，把入口安装为 `~/CodexMemory/run_maintenance.sh`，并在 macOS 上注册独立 LaunchAgent `com.codex.memory`（每天 23:55）。该链路不读取 Hermes `state.db`，也不依赖 `~/.hermes`、`~/HermesMemory`、Hermes LLM 配置或 Obsidian。

自定义路径：

```bash
./install_codex_memory.sh --yes \
  --memory-home "$HOME/CodexMemory" \
  --codex-home "$HOME/.codex"
```

## 3. 一键安装 Hermes + Codex（推荐）

```bash
# 交互式安装（会确认安装路径）
./install.sh

# 静默安装（CI / 脚本友好）
./install.sh --yes

# 自定义 vault 路径
./install.sh --vault ~/MyMemory
```

安装器会自动完成：
- 检测平台（macOS / Linux）并检查依赖（bash / python3 / git）
- 复制 Hermes scripts + skills 到 `~/.hermes/`
- 把 Codex 归档器独立安装到 `~/CodexMemory/bin/`，并注册 Codex 自己的维护任务
- 创建记忆 vault（默认 `~/HermesMemory`，可 `--vault` 自定义）
- 安装定时任务：
  - macOS：launchd（`~/Library/LaunchAgents/com.user.skill-evolution-weekly.plist`，周日 21:30）
  - Linux：crontab（自动追加 `30 21 * * 0` 条目）
- 验证安装完整性（检查关键文件 + vault）

> 安装器参数：
> ```
> ./install.sh --help
> Usage:
>   ./install.sh [options]
>   --yes          Non-interactive install (no confirmation prompts)
>   --vault PATH   Set the memory vault location (default: ~/HermesMemory)
>   --no-cron      Skip installing scheduled tasks (launchd/crontab)
>   --help         Show this help
> ```

## 4. 卸载

```bash
# 交互式卸载（确认后执行）
./uninstall.sh

# 保留记忆 vault，只卸载系统组件
./uninstall.sh --keep-vault

# 静默卸载
./uninstall.sh --yes
```

卸载器会：
- 移除 Hermes 自己的定时任务（launchd plist / crontab 条目）
- 自动备份 `scripts/`、`skills/`、`logs/` 到 `~/.hermes-backup-<timestamp>`
- 删除 Hermes 系统组件；使用 `--keep-vault` 时保留 `~/HermesMemory`
- 不触碰 `~/CodexMemory` 和 `com.codex.memory`；Codex 与 Hermes 的数据、脚本、调度彼此分离

> 卸载器参数：
> ```
> ./uninstall.sh --help
> Usage:
>   ./uninstall.sh [options]
>   --yes          Non-interactive uninstall
>   --keep-vault   Uninstall scripts/skills/cron, but KEEP your memory vault
>   --vault PATH   Memory vault location (default: $HERMES_VAULT or ~/HermesMemory)
>   --help         Show this help
> ```

## 5. 安装 Obsidian（必需，可降级）

> **Obsidian 是永久记忆系统的核心载体**：vault 的可视化、语义检索（Smart Connections）、反向链接全部依赖它。没有 Obsidian，记忆库只是散落的 markdown 文件，无法检索、无法维护。
>
> 安装器（`./install.sh`）会自动检测 Obsidian，缺失时会引导安装。也可以手动安装：
>
> **降级选项**：实在不想装 Obsidian，可用 `./install.sh --no-obsidian` 降级安装——核心归档/技能进化照常工作，但失去可视化/语义检索/反向链接。不推荐；随时可补装 Obsidian 后打开 vault 即恢复全功能。

```bash
# macOS - 下载 DMG
curl -L -o /tmp/obsidian.dmg \
  "https://github.com/obsidianmd/obsidian-releases/releases/latest/download/Obsidian.dmg"
hdiutil attach /tmp/obsidian.dmg
cp -R /Volumes/Obsidian/Obsidian.app /Applications/
hdiutil detach /Volumes/Obsidian/

# Linux - AppImage
curl -L -o /tmp/obsidian.AppImage \
  "https://github.com/obsidianmd/obsidian-releases/releases/latest/download/Obsidian-1.12.0.AppImage"
chmod +x /tmp/obsidian.AppImage
# 将 vault 指向 ~/HermesMemory 即可
```

## 6. 安装 Smart Connections 插件（语义搜索）

```bash
PLUGIN_DIR="$HOME/HermesMemory/.obsidian/plugins/smart-connections"
mkdir -p "$PLUGIN_DIR"
cd "$PLUGIN_DIR"
# 在 Obsidian 里打开 vault 后，到「设置 → 第三方插件」安装 Smart Connections
# 或在 Community plugins 搜索 "Smart Connections" 一键安装
```

## 7. 运行自进化系统（可选）

```bash
# 手动跑一次周审（首次建议手动验证）
python3 ~/.hermes/scripts/skill_evolution/run_weekly.py

# 验证安装 + 自进化管线（36 断言）
python3 ~/.hermes/scripts/skill_evolution/verify_evolution_pipeline.py

# 运行安装器集成测试（17 断言，隔离环境）
bash tests/test_install.sh

# 完整发布门禁（3 轮隔离实测 + 适配层 + 引用完整性 + 31 单测 + 归档安全）
bash tests/gate_release.sh
```

## 常见问题

### Q1: Linux 上能跑吗？
能。v2.0.0 起提供完整 Linux 支持：`install.sh` 检测到 Linux 后自动用 crontab 替代 launchd，`date`/`stat`/`sed` 差异由 `lib/platform.sh` 统一处理。

### Q2: 可以自定义安装目录吗？
可以设 `HERMES_HOME` 环境变量（默认 `~/.hermes`），或 `--vault` 指定记忆库位置。

### Q3: 卸载 Hermes 会让 Codex 记忆维护挂掉吗？
不会。Codex 派生记忆默认位于 `~/CodexMemory/`，由独立的 `com.codex.memory` 调度维护；Hermes 卸载器不会删除或停用它。即使删除 `~/.hermes` 和 `~/HermesMemory`，Codex 维护仍可运行。只有手动删除 `~/CodexMemory` 才会删除 Codex 派生卡片；原始会话 JSONL 仍在 `~/.codex/`，可重新运行 `install_codex_memory.sh` 重建。

### Q4: 升级时安装器会覆盖我的修改吗？
安装器对 skills 采用"覆盖前备份"策略：如果同名 skill 已存在，先备份为 `*.bak-<timestamp>` 再写入新版本。
