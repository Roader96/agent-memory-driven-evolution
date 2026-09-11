# 🏗️ 架构设计

## 设计目标

> **所有上下文零丢失 + 不塞爆 system prompt + 无需提醒 + 可视化冷库**

## 三层架构

### 🔥 热记忆（Hot）
- **位置**：`~/.hermes/memories/MEMORY.md`
- **注入**：每轮 system prompt
- **限制**：2,200 字符硬上限
- **告警线**：1,500 (68%)
- **紧急线**：1,800 (82%)
- **作用**：AI 短期记忆，决定当下对话

### ⚡ 实时归档（Hook）
- **位置**：`~/.checkpoints/`
- **触发**：每 5 轮 / 30 分钟 / 阈值
- **动作**：决定要不要写冷库
- **状态机**：
  - `✅ 正常` - 不动
  - `🔔 snapshot_5turn` - 小快照
  - `🔔 snapshot_30min` - 中快照
  - `⚠️ migrate_hot` - 迁移低频
  - `🚨 urgent_migrate` - 紧急

### 🧊 冷记忆（Cold）
- **位置**：`$HERMES_VAULT`（默认 `~/Documents/HermesMemory`）
- **格式**：Obsidian 风格 Markdown
- **特性**：
  - 反向链接（`[[wikilinks]]`）
  - 项目时间线
  - 语义搜索（Smart Connections）
- **作用**：长期存储，无上限

## 数据流

```
┌─────────────────────────────────────────────┐
│           对话进行（每轮）                   │
└─────────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  关键信息 → smart_archive.sh 归档            │
│  "Website材料对比" "PLA/PETG/ABS" "Website"  │
└─────────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  vault/2026-06-08-3D-打印材料对比.md        │
│  落盘到 $HERMES_VAULT/projects/Website/      │
└─────────────────────────────────────────────┘
                  ↓ 自动
┌─────────────────────────────────────────────┐
│  vault_postprocess.py（5 件事）             │
│  1. 反向链接注入                              │
│  2. 项目时间线生成                            │
│  3. INDEX.md 维护                             │
│  4. README.md 维护                            │
│  5. ERRORS.md 维护                           │
└─────────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  Obsidian 立即可见                            │
│  Smart Connections 自动索引                   │
└─────────────────────────────────────────────┘
```

## 智能分类（resolve_category）

```bash
case "$tag" in
  "preferences"|"incidents"|"daily")
    echo "$tag"  # 绝对保留
    ;;
  "")
    # 启发式：检查文本是否含已有项目名
    # 启发式：含"我习惯/我从不" → preferences
    # 启发式：含"出错了/踩坑" → incidents
    echo "daily"
    ;;
  *)
    echo "projects/$tag"  # 项目名
    ;;
esac
```

**关键点**：`daily/preferences/incidents` 是**绝对保留字**，不会被项目归并劫持。

## 触发频率设计

### 为什么每 5 轮 + 30 分钟？

| 方案 | 丢的最多 | 优缺点 |
|------|---------|--------|
| 每天 1 次 | 23h59m | ❌ 太粗，丢太多 |
| 每小时 1 次 | 1h | ⚠️ 还行但不够 |
| **每 5 轮 + 30 分钟** | **5-10 分钟** | ✅ **零丢失 + 不打扰** |
| 每轮 1 次 | 0 | ❌ 太频繁，写盘慢 |

**理由**：
- 5 轮 ≈ 5-10 分钟对话
- 30 分钟兜底长思考
- 双保险 = 至少 10 分钟才丢最多 1 次内容

### 为什么阈值 1500/1800？

- 2200 是硬上限
- 1500 = 68%，**告警线**——开始迁移
- 1800 = 82%，**紧急线**——立即迁移
- 给用户和系统**缓冲期**

## 错误统计

### 数据源优先级

1. **Hermes 自带**：`~/.hermes/logs/errors.log`（最大，WARNING 级）
2. **冷库补充**：`$VAULT/.checkpoints/errors.json`（auto_log_error.py 写的）
3. **incidents/ 主题**：`$VAULT/incidents/*.md`（聚合类似主题）

### 提炼路径

```
单条 learning (incidents/ 或 preferences/)
   ↓ 出现 2+ 次
加到 SKILL.md 故障排查
   ↓ 高频 ≥3 次
提炼为新 skill
   ↓ 跨场景
SOUL.md / 记忆热区
```

## 与 Hermes 的集成

### 不造轮子

Hermes 已经有：
- `memory` 工具（写热记忆）
- 自带 `errors.log`（错误日志）
- skill 系统（装 SKILL.md）

Hermes Mind **只**：
- 把 memory 的内容**延展**到冷库
- 多读一份 errors.json
- 装 3 个 SKILL.md 让其他 agent 也能维护

### 跨 agent 维护

任何 agent 读 `~/.hermes/skills/hermes-auto-memory-archiving/SKILL.md`：
- 立刻知道 vault 在哪
- 立刻知道阈值
- 立刻知道常见坑
- 立刻能继续维护

## 关键文件

| 文件 | 作用 |
|------|------|
| `smart_archive.sh` | 归档入口 |
| `vault_postprocess.py` | 后处理核心 |
| `auto_archive_hook.sh` | 频率控制 |
| `auto_log_error.py` | 错误入口 |
| `scan_learnings.py` | 每日扫高频 |
| `daily_summary.sh` | 每日 cron |
| `SKILL.md` × 3 | 工作流文档 |

## 性能

- 22 个文件 vault：**毫秒级**处理
- 100 个文件 vault：< 1 秒
- 1000 个文件 vault：< 5 秒
- 1 万个文件 vault：< 30 秒

瓶颈是 Obsidian 自身（打开大 vault 会卡），不是脚本。

## 安全

- `.gitignore` 排除个人 vault
- 路径用 `HERMES_VAULT` 环境变量（不硬编码）
- 错误日志只存本地
- 无网络请求（除 Obsidian 插件下载）

## 未来方向

- [ ] 多设备同步（Remotely Save 插件）
- [ ] 向量库替代（mempalacejs 路线）
- [ ] 跨 agent 协同（共享 vault）
- [ ] AI 自动写 README 总结
- [ ] 移动端查看
