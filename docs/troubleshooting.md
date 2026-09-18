# 🐞 故障排查

> **路径说明**：本文命令示例均假设默认安装路径 `~/.hermes`（vault `~/HermesMemory`）。若安装时自定义了 `HERMES_HOME` / `--vault`，请相应替换。

## 1. smart_archive 不写文件

**现象**：命令执行了但 vault 里没新文件

**原因**：
- 标签为空 + 启发式也没匹中
- vault 路径不存在
- 权限问题

**修复**：

```bash
# 检查路径
echo "$HERMES_VAULT"
ls -d ~/Documents/HermesMemory

# 检查权限
touch ~/Documents/HermesMemory/test.txt && echo "✅ 可写" || echo "❌ 无权"

# 显式传标签
~/.hermes/scripts/smart_archive.sh "标题" "内容" "daily"
```

## 2. 反向链接没出现

**现象**：vault 里文件没有 `## 相关链接` 段

**修复**：

```bash
# 手动跑后处理
python3 ~/.hermes/scripts/vault_postprocess.py

# 看输出
ls ~/Documents/HermesMemory/INDEX.md  # 应该被更新
```

## 3. 热记忆计数不准

**现象**：HERMES_HOT_USED 跟实际 MEMORY.md 字符数对不上

**修复**：

```bash
# 重新计算
chars=$(wc -m < ~/.hermes/memories/MEMORY.md)
~/.hermes/scripts/update_hot_used.sh $chars
```

## 4. Obsidian 看不到 vault

**现象**：打开 Obsidian 是空白的

**修复**：

```bash
# 1. 检查 vault 注册
cat ~/Library/Application\ Support/obsidian/obsidian.json

# 2. 写 vault 配置
mkdir -p ~/Documents/HermesMemory/.obsidian
cat > ~/Documents/HermesMemory/.obsidian/app.json << 'EOF'
{
  "alwaysUpdateLinks": true,
  "newLinkFormat": "shortest",
  "livePreview": true
}
EOF

# 3. 重启 Obsidian
osascript -e 'quit app "Obsidian"'
sleep 2
open -a Obsidian
```

## 5. Smart Connections 不工作

**现象**：插件装了但搜不到东西

**原因**：
- Restricted Mode 没关
- 模型没下完

**修复**：

```bash
# 1. 检查配置
cat ~/Documents/HermesMemory/.obsidian/community-plugins.json
# 应该输出: ["smart-connections"]

# 2. 删了重装
rm ~/Documents/HermesMemory/.obsidian/community-plugins.json
echo '["smart-connections"]' > ~/Documents/HermesMemory/.obsidian/community-plugins.json

# 3. 重启 Obsidian，看右侧 Smart Connections 面板是否在加载模型
# 首次启动要等 1-2 分钟
```

## 6. daily 快照被误归到 projects/

**现象**：传 `daily` 标签但文件跑到了 `projects/某个项目/`

**原因**：标题/内容含已有项目名

**修复**：
- v2 已修：`daily/preferences/incidents` 绝对保留
- 升级到 v1.0+ 即可

## 7. ERRORS.md 是空的

**现象**：明明有错误但 ERRORS.md 写 "无错误记录"

**修复**：

```bash
# 检查 errors.json 是否存在
ls -la ~/Documents/HermesMemory/.checkpoints/errors.json

# 手动注入测试
~/.hermes/scripts/auto_log_error.py "test" "测试错误" "详情"

# 跑后处理
python3 ~/.hermes/scripts/vault_postprocess.py
```

## 8. 后台 review 拒绝工具

**报错**：`Background review denied non-whitelisted tool: patch`

**修复**：在主对话（前台）里用这些工具。后台/cron 任务只用 memory + skill 工具。

详见 [user-skill-evolution skill](https://github.com/Roader96/agent-memory-driven-evolution/tree/main/skills/user-skill-evolution)。

## 9. terminal 退出码 1 但实际正常

**现象**：`exit_code: 1, error: null`

**原因**：脚本正常退出，但工具把它当错。

**修复**：
- 看 `output` 字段
- `grep` 无匹配 = 退出 1（正常）
- `test` 条件不满足 = 退出 1（正常）
- 不要被 exit_code=1 吓到

## 10. vault_postprocess 报错

**现象**：跑后处理失败

**调试**：

```bash
# 看完整 stacktrace
python3 ~/.hermes/scripts/vault_postprocess.py 2>&1 | head -50

# 检查 vault 目录权限
ls -la ~/Documents/HermesMemory/

# 检查磁盘空间
df -h ~/Documents/HermesMemory/
```

## 11. smart_archive "假成功"

**现象**：命令返回成功但实际没写

**原因**：bash 命令返回 0 不一定意味着文件写了

**修复**：

```bash
# 检查文件
ls -lt ~/Documents/HermesMemory/daily/ | head -3
ls -lt ~/Documents/HermesMemory/projects/*/ 2>/dev/null | head -5
```

## 12. 升级后旧版 vault 格式不对

**现象**：从 v1 升到 v3，文件没反向链接

**修复**：

```bash
# 跑一次后处理即可
python3 ~/.hermes/scripts/vault_postprocess.py
# 所有 .md 都会被注入 ## 相关链接 段
```

## 13. cron 没跑

**现象**：23:50 没收到飞书消息

**调试**：

```bash
# 1. 查 cron 状态
crontab -l

# 2. 手动跑测试
~/.hermes/scripts/daily_summary.sh

# 3. 看 cron 日志
tail -50 /var/log/cron.log  # macOS 不一定有
```

## 14. macOS 路径里有中文/特殊字符

**现象**：`~/Documents/我的笔记/` 中文目录归档失败

**修复**：

```bash
# 用绝对路径 + 显式编码
export LANG=en_US.UTF-8
export HERMES_VAULT="$HOME/Documents/我的笔记"
```

## 15. Python 版本不兼容

**现象**：`SyntaxError` 或 `ModuleNotFoundError`

**要求**：Python 3.9+（macOS 26 自带 3.13）

**修复**：

```bash
python3 --version  # 应该是 3.9+
which python3      # 应该是 /usr/bin/python3 或 homebrew
```

## 获取更多帮助

- 看 [LEARNINGS-REVIEW.md](https://github.com/Roader96/agent-memory-driven-evolution) 自动错误分析
- 提交 [Issue](https://github.com/Roader96/agent-memory-driven-evolution/issues)
- 读 [skill](../skills/user-auto-memory-archiving/SKILL.md) 工作流
