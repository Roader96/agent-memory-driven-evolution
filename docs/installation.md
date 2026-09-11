# 📦 安装指南

## 系统要求

- **OS**：macOS 26+ / Linux（GNU coreutils：Ubuntu / Debian / Arch / Fedora 等主流发行版）
- **Python**：3.9+（系统自带或 apt/brew 安装）
- **Bash**：4.0+（macOS 自带 bash 3.2 也能跑，推荐升级到 4+）
- **Git**：用于克隆仓库
- **Obsidian**：1.12+（可选，用于可视化 vault；Smart Connections 插件提供语义搜索）
- **磁盘**：< 100MB（不含个人 vault 内容）

> **Windows**：暂不支持宿主运行（脚本依赖 bash + Python 生态）。可选方案：
> - WSL2 (Windows Subsystem for Linux) —— 按 Linux 方式安装，兼容性最好
> - 在 Docker 容器内运行

## 1. 克隆项目

```bash
git clone https://github.com/Roader96/agent-memory-driven-evolution.git
cd agent-memory-driven-evolution
```

## 2. 一键安装（推荐）

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
- 复制 scripts + skills 到 `~/.hermes/`
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

## 3. 卸载

```bash
# 交互式卸载（确认后执行）
./uninstall.sh

# 保留记忆 vault，只卸载系统组件
./uninstall.sh --keep-vault

# 静默卸载
./uninstall.sh --yes
```

卸载器会：
- 移除定时任务（launchd plist / crontab 条目）
- 自动备份 `scripts/`、`skills/`、`logs/` 到 `~/.hermes-backup-<timestamp>`
- 删除系统组件（默认保留 vault，除非你显式确认删除）

> 卸载器参数：
> ```
> ./uninstall.sh --help
> Usage:
>   ./uninstall.sh [options]
>   --yes          Non-interactive uninstall
>   --keep-vault   Uninstall scripts/skills/cron, but KEEP your memory vault
>   --help         Show this help
> ```

## 4. 安装 Obsidian（可选，推荐）

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

## 5. 安装 Smart Connections 插件（语义搜索）

```bash
PLUGIN_DIR="$HOME/HermesMemory/.obsidian/plugins/smart-connections"
mkdir -p "$PLUGIN_DIR"
cd "$PLUGIN_DIR"
# 在 Obsidian 里打开 vault 后，到「设置 → 第三方插件」安装 Smart Connections
# 或在 Community plugins 搜索 "Smart Connections" 一键安装
```

## 6. 运行自进化系统（可选）

```bash
# 手动跑一次周审（首次建议手动验证）
python3 ~/.hermes/scripts/skill_evolution/run_weekly.py

# 验证安装 + 自进化管线（44 断言）
python3 ~/.hermes/scripts/skill_evolution/verify_evolution_pipeline.py

# 运行安装器集成测试（13 断言，隔离环境）
bash tests/test_install.sh
```

## 常见问题

### Q1: Linux 上能跑吗？
能。v2.0.0 起提供完整 Linux 支持：`install.sh` 检测到 Linux 后自动用 crontab 替代 launchd，`date`/`stat`/`sed` 差异由 `lib/platform.sh` 统一处理。

### Q2: 可以自定义安装目录吗？
可以设 `HERMES_HOME` 环境变量（默认 `~/.hermes`），或 `--vault` 指定记忆库位置。

### Q3: 卸载会删我的记忆吗？
默认**不会**。vault 独立于系统组件，卸载系统组件时默认保留。只有明确传 `--yes` 并在交互确认中选删除，才会删除。

### Q4: 升级时安装器会覆盖我的修改吗？
安装器对 skills 采用"覆盖前备份"策略：如果同名 skill 已存在，先备份为 `*.bak-<timestamp>` 再写入新版本。