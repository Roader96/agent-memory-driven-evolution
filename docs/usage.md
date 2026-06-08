# 🛠 使用手册

## 核心工作流

```
AI 对话进行
   ↓ 关键信息
调用 smart_archive.sh
   ↓
写入 vault
   ↓
vault_postprocess.py 自动跑（5 件事）
   ↓
Obsidian 立即可看
```

## 1. 归档（核心操作）

### 基础用法

```bash
# 归档到 daily/
~/.hermes/scripts/smart_archive.sh "今日天气不错" "深圳 28 度，有阵雨"

# 归档到项目（自动建 projects/3D打印/）
~/.hermes/scripts/smart_archive.sh "3D 打印材料对比" "PLA 易打，PETG 强度高" "3D打印"

# 归档偏好（永久保留）
~/.hermes/scripts/smart_archive.sh "哥喜欢" "用 markdown 而非富文本" "preferences"

# 归档踩坑
~/.hermes/scripts/smart_archive.sh "3D 首层没粘住" "调高热床温度到 60" "incidents"
```

### 标签规则

| 标签 | 归到 | 用途 |
|------|------|------|
| `""`（空）| `daily/` | 普通对话 |
| `preferences` | `preferences/` | 永久偏好 |
| `incidents` | `incidents/` | 踩坑+修复 |
| `3D打印` | `projects/3D打印/` | 项目名 |
| `NAS` | `projects/NAS/` | 项目名 |

**绝对保留字**：`daily` / `preferences` / `incidents` —— 传这三个标签**不会**被项目归并劫持。

## 2. 实时归档钩子

每轮对话结束调一次：

```bash
~/.hermes/scripts/auto_archive_hook.sh check
```

返回：

| 返回 | 含义 | 动作 |
|------|------|------|
| `✅ 正常` | 啥也不用做 | 继续 |
| `🔔 snapshot_5turn` | 5 轮到了 | 写小结 |
| `🔔 snapshot_30min` | 30 分钟到了 | 写完整快照 |
| `⚠️ migrate_hot` | 热记忆 >1500 | 迁移低频 |
| `🚨 urgent_migrate` | 热记忆 >1800 | 紧急迁移 |

## 3. 后处理

```bash
# 手动跑（一般不用，smart_archive 会自动调）
python3 ~/.hermes/scripts/vault_postprocess.py
```

干 5 件事：
1. 注入反向链接
2. 生成项目时间线
3. 维护 INDEX.md
4. 维护 README.md
5. 维护 ERRORS.md

## 4. 错误记录

### Python 脚本里

```python
import sys
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from auto_log_error import log_error, log_exception

# 手动记
log_error("类别", "消息", "详情")

# 自动捕获异常
try:
    risky_op()
except Exception:
    log_exception("类别", "前缀: ")
```

### CLI

```bash
~/.hermes/scripts/auto_log_error.py "类别" "消息" "详情"
echo "详情" | ~/.hermes/scripts/auto_log_error.py "类别" "消息"
```

## 5. 每日总结（cron 23:50）

自动跑，会：
1. 写当日 daily 总结
2. 跑后处理
3. 跑 learnings 扫描
4. 推飞书 DM（如果配了）

手动跑（测试用）：

```bash
~/.hermes/scripts/daily_summary.sh
```

## 6. Learnings 评审

```bash
python3 ~/.hermes/scripts/scan_learnings.py
```

读 Hermes 自带 `~/.hermes/logs/errors.log` + 冷库 errors.json，生成 `LEARNINGS-REVIEW.md`，**含高频提炼候选**。

## 7. Obsidian 端操作

### 快捷键

| 操作 | 快捷键 |
|------|--------|
| 全局搜索 | `Cmd + Shift + F` |
| 快速切换 | `Cmd + O` |
| 反向链接面板 | `Cmd + 3` |
| 大纲视图 | `Cmd + 4` |
| 跟随链接 | `Cmd + 点击` |

### 语义搜索（Smart Connections）

1. 看右侧 Smart Connections 面板
2. 或按 `Cmd + P` 输 "Smart Connections: Lookup"
3. 输入问题（"上次 NAS 装机用什么主板"）
4. AI 找相关笔记

## 8. 召回历史

```bash
# 关键词搜索冷库
~/.hermes/scripts/recall.sh "NAS SHR"
```

## 9. 完整示例：新建一个项目

```bash
# 1. 第一次提到 "新玩具 3D 打印"
~/.hermes/scripts/smart_archive.sh "我的新玩具 3D 打印" "买了 Bambu Lab A1 mini" "3D打印"
# → 自动建 projects/3D打印/

# 2. 后续聊同项目
~/.hermes/scripts/smart_archive.sh "3D 打印材料对比" "PLA/PETG/ABS" "3D打印"
# → 自动归到 projects/3D打印/，不重建

# 3. 踩坑
~/.hermes/scripts/smart_archive.sh "3D 首层没粘住" "调高热床 60°C" "incidents"

# 4. 之后打开 Obsidian
#    projects/3D打印/TIMELINE.md 自动按时间排序
```

## 10. 配置示例

`~/.zshrc` 加：

```bash
export HERMES_VAULT="$HOME/Documents/HermesMemory"
alias hm-archive='~/.hermes/scripts/smart_archive.sh'
alias hm-hook='~/.hermes/scripts/auto_archive_hook.sh check'
alias hm-postprocess='python3 ~/.hermes/scripts/vault_postprocess.py'
```

之后：

```bash
hm-archive "标题" "内容" "标签"
hm-hook
hm-postprocess
```

## 下一步

- 看 [架构设计](architecture.md) 了解内部原理
- 看 [故障排查](troubleshooting.md) 解决常见问题
