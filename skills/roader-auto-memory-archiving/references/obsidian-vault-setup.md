# Obsidian Vault 装好后 "啥也看不到" 排查

## 症状

- Obsidian 已安装并启动
- 进程在跑（ps aux 看到 4 个）
- 但界面里文件树是空的 / 只有 Obsidian 默认占位
- 用户反馈 "我进去为什么啥也看不到"

## 根因（必中）

**Obsidian 默认打开的是 `~/Documents/Obsidian Vault`（系统自建空 vault），不是新建的 vault**。

Obsidian 不像 VSCode 那样 "打开文件夹就完事"，它有**自己的 vault 注册表**（`obsidian.json`），必须在里面登记路径才会显示为可选 vault。

## 排查步骤

```bash
# 1) 看当前注册的 vault
cat ~/Library/Application\ Support/obsidian/obsidian.json
# 输出通常只有：
# {"vaults":{"41f83abc268a7c15":{"path":"/Users/<username>/Documents/Obsidian Vault",...}}}

# 2) 看 vault 目录里到底有没有文件
ls -la ~/HermesMemory/
# 如果文件都在 → 是 Obsidian 没认这个 vault，不是 vault 本身空
```

## 修复（4 步）

### Step 1: 退出 Obsidian
```bash
osascript -e 'quit app "Obsidian"' 2>&1
# 或鼠标右键 dock 图标 Quit
```

### Step 2: 注册新 vault 到 obsidian.json
```json
{
  "vaults": {
    "<existing-id>": { "path": "/Users/<username>/Documents/Obsidian Vault", "ts": 123, "open": true },
    "hermesmemory":   { "path": "/Users/<username>/HermesMemory",   "ts": 123, "open": false }
  }
}
```
注意：不要删原有的 vault 条目，**追加**即可。`open: false` 即可，Obsidian 启动后会让用户选。

### Step 3: 重启 Obsidian
```bash
open -a Obsidian
```

### Step 4: 用 URI 协议触发打开指定 vault
```bash
open "obsidian://open?vault=hermesmemory&path=README.md"
# 或带 vault 名
open "obsidian://open?path=/Users/<username>/HermesMemory"
```

## 验证清单

- [ ] Obsidian 启动后弹出 "Open vault" 对话框
- [ ] 列表里能看到 `HermesMemory`
- [ ] 选中后左侧文件树显示 README/INDEX/ERRORS.md
- [ ] 进 `daily/` 看到今天归档的 md 文件

## 备选：用户手动操作

如果用户想自己点：
1. 左侧栏 "Open another vault" 按钮
2. 选 "Open folder as vault"
3. 选 `~/HermesMemory/`

## 不要做的

- ❌ 不要用 `open "obsidian://open?path=..."` 单独打开文件 — 它会**临时**用默认 vault 显示，不会切换
- ❌ 不要删 .obsidian 目录 — 里面是配置（app.json / community-plugins.json / plugins/）
- ❌ 不要相信首次启动 "啥都不显示" 是 bug — 99% 是没注册 vault

## 相关文件

- `~/Library/Application Support/obsidian/obsidian.json` — vault 注册表
- `~/HermesMemory/.obsidian/app.json` — vault 自己的配置
- `~/HermesMemory/.obsidian/community-plugins.json` — 启用的社区插件
