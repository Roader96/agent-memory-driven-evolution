# 📦 安装指南

## 系统要求

- **OS**：macOS 26+ （Linux/Windows 部分支持，需手动改路径）
- **Python**：3.9+
- **Bash**：4.0+（macOS 自带）
- **Obsidian**：1.12+（可选，用于可视化 vault）
- **磁盘**：< 100MB（不含个人 vault 内容）

## 1. 克隆项目

```bash
git clone https://github.com/Roader96/Hermes-Mind.git
cd Hermes-Mind
```

## 2. 安装脚本

```bash
# 复制 10 个脚本
mkdir -p ~/.hermes/scripts
cp scripts/* ~/.hermes/scripts/
chmod +x ~/.hermes/scripts/*

# 复制 3 个 skill
cp -R skills/* ~/.hermes/skills/
```

## 3. 装 Obsidian（可选）

```bash
# macOS - 下载 DMG
curl -L -o /tmp/obsidian.dmg \
  "https://github.com/obsidianmd/obsidian-releases/releases/latest/download/Obsidian.dmg"

hdiutil attach /tmp/obsidian.dmg
cp -R /Volumes/Obsidian/Obsidian.app /Applications/
hdiutil detach /Volumes/Obsidian/

# Linux 用 AppImage（不展开）
```

## 4. 装 Smart Connections 插件（语义搜索）

```bash
PLUGIN_DIR="$HOME/Documents/HermesMemory/.obsidian/plugins/smart-connections"
mkdir -p "$PLUGIN_DIR"
cd "$PLUGIN_DIR"

curl -L -o main.js "https://github.com/brianpetro/obsidian-smart-connections/releases/latest/download/main.js"
curl -L -o manifest.json "https://github.com/brianpetro/obsidian-smart-connections/releases/latest/download/manifest.json"
curl -L -o styles.css "https://github.com/brianpetro/obsidian-smart-connections/releases/latest/download/styles.css"

# 启用
echo '["smart-connections"]' > "$HOME/Documents/HermesMemory/.obsidian/community-plugins.json"
```

## 5. 配置 vault 路径（可选）

默认 vault 在 `~/Documents/HermesMemory`。改路径：

```bash
# 临时
export HERMES_VAULT="$HOME/我的记忆"

# 永久（加到 ~/.zshrc 或 ~/.bashrc）
echo 'export HERMES_VAULT="$HOME/我的记忆"' >> ~/.zshrc
source ~/.zshrc
```

## 6. 在 Obsidian 打开 vault

1. 启动 Obsidian
2. 选 "**Open folder as vault**"
3. 选 `~/Documents/HermesMemory`（或你的 `HERMES_VAULT`）
4. 信任作者
5. Smart Connections 首次启动会自动下载 ~30MB ONNX 模型

## 7. 验证安装

```bash
# 测试脚本
~/.hermes/scripts/smart_archive.sh "测试归档" "这是测试" "incidents"
ls ~/Documents/HermesMemory/incidents/

# 跑后处理
python3 ~/.hermes/scripts/vault_postprocess.py

# 看 README.md 是否生成
cat ~/Documents/HermesMemory/README.md
```

## 卸载

```bash
rm -rf ~/.hermes/scripts/smart_archive.sh \
       ~/.hermes/scripts/vault_postprocess.py \
       ~/.hermes/scripts/auto_archive_hook.sh \
       ~/.hermes/scripts/update_hot_used.sh \
       ~/.hermes/scripts/recall.sh \
       ~/.hermes/scripts/auto_log_error.py \
       ~/.hermes/scripts/scan_learnings.py \
       ~/.hermes/scripts/daily_summary.sh \
       ~/.hermes/scripts/save_to_memory.sh \
       ~/.hermes/scripts/auto_daily_snapshot.sh
rm -rf ~/.hermes/skills/hermes-auto-memory-archiving \
       ~/.hermes/skills/hermes-self-improvement \
       ~/.hermes/skills/hermes-tool-restrictions
# Obsidian 和 vault 内容自行删除
```

## 升级

```bash
cd Hermes-Mind
git pull
cp scripts/* ~/.hermes/scripts/
cp -R skills/* ~/.hermes/skills/
```

## 下一步

- 看 [使用手册](usage.md) 了解日常用法
- 看 [架构设计](architecture.md) 了解原理
- 看 [故障排查](troubleshooting.md) 解决问题
