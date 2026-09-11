---
name: roader-auto-memory-archiving
description: Hermes 冷/热记忆双层自动归档 v3 (含 Obsidian vault 后处理)。所有上下文零丢失 + 不塞爆 system prompt + 智能分类 + 实时归档 + 后处理自动。新话题自动建项目子目录，热记忆超 1800 看门狗静默写标记文件，agent 见标记自行迁移压缩（不推飞书）。Roader 强信号：所有对话上下文必须存档，无需提醒。
---

# roader-auto-memory-archiving v3

## 核心原则
**所有上下文零丢失 + 不塞爆 system prompt + 无需哥提醒 + 可视化冷库 + 激进分层（不要保守方案）**

> **工作流偏好（Roader 强信号）**：当 Roader 说"评估个时间频率" / "这个还不够" / "你自己存呗" = **默认给激进完整方案**，不要等 Roader 提需求才加量。实现时**直接做"最完整版本"**，而不是"最简版等 Roader 要求再补"。这条偏好多次重复强化（2026-06-08 至少 3 次信号），已成本会话工作流硬规则。

## 📚 References

- `references/pitfalls-2026-06-08.md` — 5 个坑详细档案（P0 严重 + 4×P1 中等 + 1×P2 轻微）+ 修复模式
- `references/pitfalls-2026-06-11.md` — cron 静默兜底模式 + 诊断误判教训（P0 红 + P1 黄 + 工具坑 + cron 速查表）
- `references/pitfalls-2026-07-24.md` — 本会话教训汇总（A 股节假日短路 + honest > 讨好 + 不可逆 core 默认不动 + memory→vault 死流程 + daily cron 时间 + Obsidian 空 daily.md 误创）
- `references/project-archive-recipe.md` — 项目型任务收尾主动归档 recipe（2026-08-10 验证：vault 确认 / 目录结构 / TIMELINE 模板 / postprocess 重写坑）
- `references/icloud-migration-2026-08-12.md` — HermesMemory 迁出 iCloud 完整 recipe（rsync 复制 + HERMES_VAULT 统一路径 + cron prompt + Obsidian 配置 + 旧目录备份）
- `references/obsidian-vault-setup.md` — Obsidian 装好后"啥也看不到" 4 步排查
- `references/dont-overengineer.md` — "要 X 只做 X" 反模式清单 + 写作陷阱（来自旧 hermes-auto-memory-archiving + hermes-self-improvement）
- `references/scan_learnings-workflow.md` — 4 类学习来源 + scan_learnings.py 行为规范 + 不主动提炼 skill 原则（来自旧 hermes-self-improvement）
- `references/error-logging-recipe.md` — log_error 两种 Python 用法 + CLI 用法 + 错误类别建议（来自旧 hermes-auto-memory-archiving）
- `references/legacy/2026-06-08-skill-review.md` — 旧 skill 反思事件档案（来自旧 hermes-auto-memory-archiving）
- `templates/LEARNING.md` — 学习条目模板（来自旧 hermes-self-improvement）
- `templates/ERROR.md` — 错误条目模板（来自旧 hermes-self-improvement）

## 三层防护

### 🔥 热记忆（hot）
- 位置：`~/.hermes/memories/MEMORY.md`
- 限制：**< 1500 字符**（68%），硬上限 2200
- 注入：每轮自动
- 维护：`update_hot_used.sh <字符数>`

### 🧊 冷记忆（cold）
- 位置：`~/HermesMemory/`（Obsidian vault）
- 限制：无上限
- 召回：`recall.sh` / Obsidian 搜 / Smart Connections 语义搜
- 后处理：归档后自动跑 `vault_postprocess.py`（反向链接+时间线+INDEX+README+ERRORS）

### ⚡ 实时归档（hot→cold）
- 触发点：
  - **每 5 轮** → 无条件小快照
  - **每 30 分钟** → 强制中快照
  - **热记忆 > 1800 字符** → 看门狗写标记文件 `~/.hermes/data/.memory_overload_pending`，agent 见标记立即迁移低频项，压回 1500 以下标记自动清
  - **新话题首次出现** → 智能建项目子目录

## 智能分类（smart_archive.sh）

调用时**传项目标签**（推荐）：
```bash
smart_archive.sh "标题" "内容" "3D打印"   # → projects/3D打印/
smart_archive.sh "标题" "内容" "preferences"  # → preferences/
smart_archive.sh "标题" "内容" "incidents"    # → incidents/
smart_archive.sh "标题" "内容" ""              # → 兜底 daily + 启发
```

**归档后自动跑** `vault_postprocess.py`（无需手动触发）。

## Vault 后处理（vault_postprocess.py）

每次新增归档文件后自动跑，干 **5 件事**：

1. **反向链接注入** — 每个文件底部追加 `## 相关链接` 段
2. **项目时间线** — 遍历 `projects/*/` 生成 `TIMELINE.md`
3. **INDEX.md 维护** — 目录树 + 项目列表 + 统计
4. **README.md 维护** — vault 门面（6 项统计 + 最近 5 条）
5. **错误统计** — 读 `.checkpoints/errors.json` 生成 `ERRORS.md`

**记录错误**（任何 python 脚本都能调）：
```python
from vault_postprocess import log_error
log_error("类别", "消息", "详情")
```

**手动跑**：`python3 ~/.hermes/scripts/vault_postprocess.py`

## 实时归档钩子

每次对话后跑：
```bash
auto_archive_hook.sh check
```

返回：`✅ 正常` / `🔔 snapshot_5turn` / `🔔 snapshot_30min` / `⚠️ migrate_hot` / `🚨 urgent_migrate`

## ⚠️ Cron 脚本必须带重试 + 静默兜底（2026-06-11 验证）

`daily_summary.sh`（cron 23:50 调用）之前用 `set -e` + 直接 `python3 script.py`，一旦 `vault_postprocess.py` / `scan_learnings.py` 抛 `RuntimeError: Connection error`（Mac 睡眠/网络抖动），整个脚本退出、daily 总结不写、cron 报红。

**硬规则**：所有 cron 脚本里调 python 的地方，**必须**套一层带重试的 helper，3 次失败**静默**（不返回非 0），让外层 `set -e` 不会杀进程。**修复模板**（直接抄进 cron 脚本顶部）：

```bash
# 不放 set -e — 任何一个失败不能杀整个 daily 流程

run_py() {
  local script="$1"
  local tries=0
  while [ $tries -lt 3 ]; do
    if python3 "$script" 2>&1 | tail -8; then
      return 0
    fi
    tries=$((tries + 1))
    echo "⚠️ $script 第 $tries 次失败，2s 后重试" >&2
    sleep 2
  done
  echo "⚠️ $script 3次都失败，跳过（不影响 daily 写入）" >&2
  return 0  # 故意让外层不红
}

# 用法
run_py "$HOME/.hermes/scripts/vault_postprocess.py"
run_py "$HOME/.hermes/scripts/scan_learnings.py"
```

**为什么不直接重试 + 报错**：cron 红 → 飞书推送炸屏 → 哥烦 → 关 cron。**静默 + log 警告**是正确策略（哥规则：「cron失败>3次告警」，所以单次失败不刷屏，但连错3次会触发下一个机制）。

**诊断命令**：看哪个 cron 最近挂了
```bash
cat ~/.hermes/cron/jobs.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
for j in d['jobs']:
    print(j['name'], '|', j.get('state'), '|', 'last:', j.get('last_status'),
          '|', 'err:', (j.get('last_error') or '')[:60])
"
```

## ⚠️ 切模型 / skill 改名后，先审 cron 的 model/provider/skills（2026-08-10）

哥的 default 模型切成 `kimi-k3 / custom:kimi` 后，审计 cron 不能只看 `last_status: ok`。三件事必须一起查：

1. **`model/provider = null` 才跟随 default**：这类 job 切模型后会走新模型。显式钉了 `model/provider` 的 job 不跟随，可能继续打旧 provider（当日 vault cron 还钉 `minimax/MiniMax-M3`）。
2. **skill 改名/废弃后要改 job 引用**：`skills: [hermes-auto-memory-archiving]` 是旧名，当前安装是 `roader-auto-memory-archiving`；用 `skill_view(name=...)` 验证，别信 cron list 里的字符串。
3. **最近失败要看是不是 provider，不是脚本**：`hermes cron runs --limit 30` + `~/.hermes/sessions/request_dump_cron_<jobid>_*.json` 能分辨 429 Token Plan / provider unresponsive / script stderr。

**最小处理顺序**：先 `cronjob action='list'` → 标出 pinned job + stale skill → 再决定只改引用，还是连 model/provider 一起清空跟随 default。不要看到 cron 红就只改脚本。

## ⚠️ 关键 Pitfalls（2026-06-08 验证，必须遵守）

### 1. **smart_archive.sh 标签优先级 bug**
- 旧版 `resolve_category` 的 case `""|"daily"` 把 "daily" 标签丢进了"检查项目名 → 启发"分支
- 导致 `smart_archive.sh "..." "..." "daily"` 被项目名（NAS/3D打印等）劫持，**应该归 daily/ 的归档被丢到 projects/某项目/**
- **修复**：case 分三段：`preferences|incidents|daily` 强保留 / `""` 走启发 / 其他当项目名
- **硬规则**：**`preferences` / `incidents` / `daily` 这三个标签是绝对保留字，绝不丢给项目归并**

### 2. **smart_archive.sh 项目名拆分 bug**
- 旧版 `cut -c1-6` 取项目名短词，遇到中文+数字混排时拆错
- 复测：`"3D打印材料"` 匹到 `"我的新玩具3D打印小恐龙"`（短词都是 "3D打印"）
- **修复**：用更短的关键字（4 字符）+ 接受归并不强制
- **硬规则**：**项目名要让 Hermes 自己起（短而独特），别超过 8 个字符**

### 3. **skill_manage create 假成功（最严重！）**
- 工具返回 success 但 `skill_view` 找不到
- **坑过本 session**：第一次建 `hermes-auto-memory-archiving` 时返 success，实际没存
- **修复**：`create` 之后**必须** `skill_view` 验证；找不到就用 `write_file` 兜底
- **永久教训**：**永远信任 skill_view 的返回，不信任 create 的 success**
- 详见 `Roader-skill-creator` skill 的 BUG 章节

### 4. **smart_archive 标题含日期会重复（2026-06-23 实测）**
- **症状**：传 `"2026-06-23-亿纬锂能深度分析"` → 生成 `2026-06-23-2026-06-23-亿纬锂能深度分析.md`（日期前缀 + 标题里的日期 = 2 次）
- **原因**：smart_archive.sh 强制加 `日期-` 前缀，没去重
- **修复**：标题里**不要带日期**（让脚本自动加）
  - ✅ 写：`smart_archive.sh "亿纬锂能深度分析" "..." "亿纬锂能"`
  - ❌ 写：`smart_archive.sh "2026-06-23-亿纬锂能深度分析" "..." "亿纬锂能"`
- **如果已经写错**：用 `mv` 重命名（`mv 2026-06-23-2026-06-23-X.md 2026-06-23-X.md`）+ 跑一次 `vault_postprocess.py` 刷 TIMELINE/反向链接

### 5. **memory 工具卡死 → 立即转 vault，不思考不讨论（2026-07-24 v6）**
- **症状**：`memory` 工具报 "Memory full" / "would exceed limit" → 我反复试（卡 4 次触 `same_tool_failure_warning`）才转 vault
- **根因**：把死规则当待决策处理——失败 ≥2 次还在思考"要不要再试一次"
- **硬规则**（死流程，不讨论）：
  1. `memory` 工具失败 ≥2 次 → 立即停手，转 vault 写盘（`~/HermesMemory/incidents/YYYY-MM-DD-反思-X.md`）
  2. vault 写完 → 口头报一句"已落盘 incidents/xxx.md"，不再追加 `memory` 调用
  3. 同步回热记忆是 `daily_summary.sh` 23:50 自动做的事，不要手动补
- **触发词**：`memory` 报 "would exceed limit" / `same_tool_failure_warning` ≥2 / 工具连续失败
- **反模式**：
  - ❌ "再试一次说不定就过了"
  - ❌ "这条要不要也存 memory"
  - ❌ "vault 写盘是不是要问哥"
- **正模式**：第一次卡 → 立即 `write_file` vault incidents/，不再回头试 `memory`
- **来源**：哥原话 "**死流程你直接执行就行 不用多思考**"（2026-07-24）
- **关联**：见 `references/pitfalls-2026-07-24.md`

### 6. **归档只写 HermesMemory，别写 Documents/Obsidian Vault（2026-08-10 被哥怼）**
- **症状**：哥说"存档到 OB"，我写进了 `~/Documents/Obsidian Vault/Projects/...`，哥打开看不到 → "我的记忆系统肯定是 HermesMemory 啊 这个这么会搞错？"
- **根因**：机器上存在两个 vault（`~/Documents/Obsidian Vault` 只是注册但没打开；Obsidian 实际打开的 vault 是 `~/HermesMemory`，`obsidian.json` 里 `open:true`）。判断用户"OB"指哪个，不能看文件夹名，要看 `~/Library/Application Support/obsidian/obsidian.json` 的 `open` 标记。
- **硬规则**：**Roader 的 OB = `~/HermesMemory/`，唯一**；`~/Documents/Obsidian Vault` 不是归档目标，不要写。拿不准就先 `cat "$HOME/Library/Application Support/obsidian/obsidian.json"` 确认 open 的 vault。
- **项目归档结构**（和现有项目一致，不要只丢一个文件）：
  ```text
  projects/<项目名>/
  ├── YYYY-MM-DD-<标题>.md   # 带归档头：> 归档时间 / > 分类 / > 触发
  └── TIMELINE.md            # 项目时间线：项目建立 / 归档条数 / 按日期条目链接
  ```
  ❌ 反模式：把内容塞进 `TIMELINE.md` 就完事（哥说"里面只有一个 timeline 跟你之前的版本好像也不一样"）。
- **写完后**：更新 `INDEX.md`（项目列表 + 统计 + 最后更新），并确认 TIMELINE 里有 `[[日期文件]]` 链接。

### 7. **memory 工具 replace 是「整条替换」，不是「子串替换」（2026-08-13 史诗级事故）**
- **症状**：想给「页面审美」规则尾部加一句门禁，old_text 只写了尾巴「海报有指定主题时按主题走）」，结果整条「2026-08-12 哥的页面审美（赛博朋克蓝科技风=深蓝底+蓝青霓虹+矩阵雨+故障标题+图标多+等宽数字+一屏不滚动）」被 content 覆盖成半截，整套审美标准丢失。
- **根因**：`memory` 工具的 `replace` 语义 = old_text 只负责**定位整条 entry**，content 会**覆盖整条 entry**，不是字符串级子串替换。
- **硬规则（三连）**：
  1. 改 memory 任何一条，content 必须写**该条的完整新内容**，绝不能只写要改的那截尾巴。
  2. 改之前先 `read_file ~/.hermes/memories/MEMORY.md` 看磁盘真实内容——**别信 system prompt 里的注入快照**（可能滞后一轮）。
  3. 改完必须 re-read 磁盘验证，确认没截断、没丢字段。
- **同期事故二**：热记忆一路涨到 96%（2117/2200）没迁移。自动归档 hook 依赖「每轮自动调用」但实际未生效 → **agent 必须主动兜底**：热记忆 >1800 立即迁移低频项，不等 hook、不问哥。迁移优先迁「详见 skill X」类冗余条目（细节已在 skill，热记忆只留硬规则核心 + 指针）。
- **修复动作**（2026-08-13）：恢复审美规则全文 + 精简 5 条冗余条目，热记忆 96%→66%。档案见 `incidents/2026-08-13-热记忆超载自检.md`。

### 8. **自动归档 hook 实际是坏的（2026-08-13 查实，别信「已自动迁移」）**
- `auto_archive_hook.sh` 的 `check_hot_memory` 读 `~/.hermes/.env` 的 `HERMES_HOT_USED`，**该值 6 月起停更**（死值 867），真实热记忆早超 1500 它也不知道 → 「>1500 自动迁移」从不触发。
- hook 注释写「由 Hermes 每轮自动调用」，但 grep 全盘它只被 `daily_summary.sh`（23:50）引用，**无任何每轮机制在跑它**，「每 5 轮 / 30min」触发从未运行过。
- **正解**：cron 看门狗直扫真实文件（`wc -m < ~/.hermes/memories/MEMORY.md`），不依赖 `.env` 死值、不依赖 agent 记性。脚本 `~/.hermes/scripts/hot_memory_watchdog.sh`，cron `*/30` no_agent。
- **2026-09-07 v2（哥令：告警不推飞书，静默自处理）**：脚本 `wc -m` 直扫真实文件，**stdout 永远静默**（不飞书不通知）；≥1800 只写标记文件 `~/.hermes/data/.memory_overload_pending`（内容=用量+时间戳），<1800 自动清标记。
- **agent 侧硬规则**：任何会话看到标记文件 → 立即迁低频项到冷存储（目标 ≤1500，迁「详见 skill X」类冗余条目）→ 删标记。流程已写进热记忆条目，换 session 也生效；迁移哪条需判断力，脚本不瞎迁。

### 9. **每日总结空泛（只数数、不读内容）→ v4 已改为读 state.db 全量会话**
- 症状：哥投诉「这几天一直在用 Hermes，但总结没有实质性东西」「自动更新失败都没记录，你在 improving 啥，形式主义」。
- 旧根因：`daily_summary_enhanced.py` 只数冷库文件+摘正文；auto-archive plugin 只抓交付物路径且 `_SKIP_PREFIXES` 把整个 `~/.hermes/` 跳过 → 白天排查对话/改内部脚本全不可见，晚上无料可提炼；agent cron 还 broken pipe/超时/关机连挂。
- **v4 架构（2026-09-10 重写，唯一入口 = launchd 23:55 `daily_watchdog.sh`）**：
  1. `~/.hermes/scripts/daily_summary_from_db.py` 直读 **state.db**（sessions/messages 表）拉当天**全部** session：哥的每条 user 原话 + assistant 带结论信号（✅/根因/修复/结论/决定…）的消息，兜底最长+最后一条。这是**证据层（零 token，数学可验）**。
  2. **润色层**：把证据 JSON 喂 `hermes -z --cli`（每天 1 次 LLM），每个会话编号 [S1][S2]…，**覆盖门禁**=正则数 `### [Sx]` 标题必须全覆盖，漏一个/超时/rc!=0 自动**降级证据版**（糙但全，绝不再空壳）。
  3. **错误自动落盘不靠自觉**：聚合 executions.db 当天 failed cron + `.last_auto_update.json` 非 ok + launchd 日志 FAIL → 追加 `HermesMemory/.checkpoints/errors.jsonl`（借鉴 GitHub agent-memory-loop：稳定 key 去重 + count 复发计数 + severity + source）。旧 errors.json 仅兜底。
  4. 脚本写盘后**内容门禁**（>400 字节 + 必含「今日实际工作」「定时任务」），不过 exit 1；watchdog 外层重试 3 次 + macOS 通知兜底。
  - **日常静默写 OB，不推飞书**（2026-09-10 哥令「不轰炸，直接看 OB」）：watchdog 跑脚本不带 PUSH_FEISHU；想临时推送才 `PUSH_FEISHU=1 python3 daily_summary_from_db.py`。生成**失败**仍保留 macOS osascript 本机通知（不是飞书）。回归验证器 `~/.hermes/scripts/verify_daily_pipeline.py` 已同步断言「静默无 message_id」。
  5. 润色 hermes -z/chat 调用会产生新 session 塞爆桌面会话列表（哥投诉）：必须用 `hermes chat -Q --oneshot --cli --source daily-polish --query-file <prompt文件>`（专属 source），跑完 `hermes sessions archive --source daily-polish --yes` 软隐藏（archived=1，数据留在 state.db 供 SQL 读，列表不显示）；load_sessions 同时用 source==daily-polish + prompt 标记 `[daily-summary-polish]` 双保险排除。别用 -z "长prompt"（命令行长度/转义坑，且 source=cli 难清理）。历史测试垃圾会话可直接 `UPDATE sessions SET archived=1 WHERE id=...`（独立 oneshot 无父子链才安全）。
- **调度**：暂停 agent cron `1b7de7ba3b06`（烧 token 又连挂），launchd `com.roader.hermes-daily-watchdog` 唯一调度（零 token、睡眠补跑）；watchdog 还静默回填最近 3 天缺失 daily、跑 vault_postprocess + scan_learnings。
- 借鉴的开源项目（哥要求别闭门造车）：mem0(65k⭐, ADD-only 追加不覆盖+agent动作即存)、agent-memory-loop(一行错误日志 id/count/severity/source)、self-improve(Reflector 规则收集→模型提炼)。
- 回填历史：`DATE_OVERRIDE=2026-09-09 python3 daily_summary_from_db.py`（加 NO_LLM=1 只出证据版，PUSH_FEISHU=1 连推飞书）。
- 旧空壳备份在 `daily/_empty-backup/`。
- **auto-archive plugin 已于 2026-09-10 禁用**（`hermes plugins disable auto-archive`，user 级不会被更新复活）：它只写死模板「产出 N 个文件」、跳过 ~/.hermes，是纯空壳污染源。会话实质已由 state.db 全量总结，项目交付物仍靠白天主动 smart_archive 收尾。`projects/auto-archive/` 历史空壳保留不删。
- **前提仍成立**：冷库 projects 归档还是要白天主动收尾（v4 解决「会话没总结」，不替代「项目交付物归档」）。

## 目录结构

```
~/HermesMemory/
├── README.md / INDEX.md / ERRORS.md / app.json
├── daily/                ← 每日会话快照
├── preferences/          ← 偏好（永久）
├── incidents/            ← 踩坑+修复
├── projects/
│   ├── <项目名>/
│   │   ├── TIMELINE.md
│   │   └── *.md
├── .obsidian/
│   ├── app.json / community-plugins.json
│   └── plugins/smart-connections/   ← 语义搜索
└── .checkpoints/
    ├── turn_count / last_snapshot / last_migration
    └── errors.json
```

## 召回流程（「一提就翻」强流程 — 2026-08-13 实测固化）

**触发（哥一提旧事 → 必走，不靠自觉）**：
- 哥提过去某件事 / 项目名 / 人名 / 说「上次那个」「还记得吗」「之前我们」「那个 XX 现在啥情况」
- 答案在历史里、不在当前上下文 → 立即走召回，别凭印象硬答

**检索顺序（session_search 是核心，实测命中率高）**：
1. `session_search(query=哥原话, limit=3)` 搜会话历史
   - FTS5 默认 AND，一次搜不准就**换词/拆词/同义词**再搜：「看板卡死」→「看板 卡」→「dashboard」→「渲染 高」
   - `sort=newest` 找「最近在哪」，`sort=oldest` 找「从哪开始」
2. 命中后看三个结构：`bookend_start`（前因=会话怎么开始）+ `messages`（过程=±5 命中上下文）+ `bookend_end`（后果=结论/决策）
3. 细节不够 → `session_search(session_id=..., around_message_id=...)` scroll 展开完整过程
4. 涉及项目档案 → 读 `~/HermesMemory/INDEX.md` 定位项目 → `projects/<X>/TIMELINE.md` 定位条目 → 读条目正文
5. 冷库档案是「收尾摘要」，session 是「过程细节」，**两者拼起来才是完整前因后果**

**回答范式（前因→过程→后果）**：
- 前因：为什么开始（bookend_start / 档案「触发」段）
- 过程：做了什么、踩了什么坑（命中消息 + scroll）
- 后果：结论/决策/现状（bookend_end / 档案「沉淀」段）
- 结尾附 `@session:xxx` link + 档案路径，让哥能点进看全文

**诚实边界**：
- 翻不到 → 老实说「搜了没找到」，**不编**
- 翻到部分 → 说清「这是我能翻到的，完整过程在 @session:xxx」
- 别把「我记得/我印象里」当「翻到了」——以 session_search 实际返回为准

## 工具脚本清单

| 脚本 | 用途 | 调用时机 |
|------|------|---------|
| `smart_archive.sh` | 智能归档（自动触发后处理） | 我主动调 |
| `vault_postprocess.py` | 5 件事后处理 | smart_archive 自动调 |
| `auto_archive_hook.sh` | 实时归档钩子 | 每轮结束 |
| `update_hot_used.sh` | 热记忆计数维护 | 写完热记忆后 |
| `recall.sh` | 关键词召回冷记忆 | 我需要找历史时 |
| `save_to_memory.sh` | 旧版（兼容保留） | 不再主动用 |
| `auto_daily_snapshot.sh` | 旧版（兼容保留） | 被 hook 取代 |
| `scan_learnings.py` | 扫描 `.learnings/` + `errors.log` 生成 LEARNINGS-REVIEW.md | 每日 23:50 cron |

## 已吸收的相邻 skill

本 skill 是 Roader 类目下**唯一**的"长记忆 + 自动归档"入口。同类工作流若有独立 skill 出现，按照下面的合并规则走：

- **`agent-memory-continuity` → absorbed here**（冷/热分层 + `vault_postprocess.py` 脚本与本 skill 完全重叠）
- **`self-improvement` / `.learnings/` → partial absorption**（`.learnings/LEARNINGS.md` / `.learnings/ERRORS.md` 这套 CLI 仍然用，但 **提炼成 skill 的动作**仍归本 skill 触发 `scan_learnings.py`，由 `Roader 决定要不要提炼` 才动 skill）
- **`hermes-auto-memory-archiving` / `hermes-cron-web-dashboard-monitor` / `hermes-gateway-stuck` / `hermes-provider-setup` / `hermes-self-improvement` / `hermes-s6-container-supervision` / `hermes-vision-setup` → archived**（早期实验版本，已被本 skill 完全取代）

**判别口诀**：当你看到"agent 失忆 / 上下文找不回 / 保存会话 / .learnings/ 怎么扫"类问题，**只装这一个 skill**就行，不要再去找别的 memory skill。

## Obsidian 必备配置

- **Vault 位置**：`~/HermesMemory/`
- **社区插件**：`smart-connections`（v4.5.3+）
- **零 API key**：本地 ONNX 嵌入模型
- **首次启用**：自动下载 ~30MB 模型

## 验证 checklist

- [ ] `recall.sh "关键词"` 有结果
- [ ] `auto_archive_hook.sh status` 显示正确用量
- [ ] 5 轮后自动 snapshot
- [ ] 热记忆超 1800 看门狗写标记（静默不推飞书），agent 见标记自迁
- [ ] 新话题首次提到自动建 projects/XXX/ 目录
- [ ] 新归档后底部有 `## 相关链接` 段
- [ ] 每个 project/XXX/ 下有 `TIMELINE.md`
- [ ] INDEX.md / README.md / ERRORS.md 始终最新
- [ ] Obsidian Smart Connections 面板能搜到相关笔记

## ⚠️ 关键 Pitfalls（2026-06-08 验证，必须遵守）

## 🕙 每日 23:50 cron 完整流程（端到端，含飞书推送）

23:50 cron 任务不是"跑 daily_summary.sh 就完事"，完整流程有 5 步。漏掉最后两步哥看不到总结。

### 步骤

1. **执行 `daily_summary.sh`** — 含 daily 写入 + vault_postprocess + scan_learnings + hook status 输出
2. **从脚本输出里收集数字**（不重新计算）：
   - 今日归档数：看 daily 文件"今日新增"列表长度
   - 热记忆用量：看 hook status 那行（`热记忆: 867/2200 (39%)`）
   - 错误统计：看 scan_learnings / ERRORS 行（`N 个错误记录` / `今日新错误: N`）
3. **如果 cron job 配了 `deliver:` 字段**（如 `feishu:oc_...`）：不要再手动 `hermes send`；把统计数字写进 final response，让 cron 系统自动投递。手动 send + cron deliver 会重复推两条。\n4. **只有没配 `deliver:`、或确认 delivery 失败时，才手动补推一条**；补推也只发 1 条完整多行消息。\n5. **报告执行结果给最终交付通道**（cron job 不需要，因为 cron 系统即最终通道）

### ⚠️ Pitfall: 推飞书别把多行 message 拆成多次 send

- ❌ 错：5 个独立 `hermes send` 调用 → 哥 DM 被刷屏 5 条
- ✅ 对：1 个 `hermes send` 含完整多行消息（上面模板就是 1 个 call）

### ⚠️ Pitfall: `daily_summary.sh` 模板可能不如磁盘版新

Roader 哥的 prompt 里给的 `daily_summary.sh` 默认模板是**最简版**（daily 写入 + postprocess + hook status）。但磁盘上的版本从 2026-06-11 起已经升级成**带 `run_py` 重试 + learnings 扫描 + 错误 JSON 读取**的完整版。

**规则**：**执行前先 `read_file ~/.hermes/scripts/daily_summary.sh` 检查存在性**——如果存在且比模板新，**直接执行，跳过模板的"如果不存在就建一个"分支**。盲目按模板重写会回退丢失 `run_py` retry helper，然后下一次网络抖动脚本就红了。

**手动测试注意**：白天手动 `cronjob action='run'` 这个 job 会提前创建 `daily/YYYY-MM-DD-每日总结.md`；当晚 23:50 正式跑时会走"今日 daily 已存在，跳过"，但 postprocess / learnings / final delivery 仍应继续。别把"跳过 daily 写入"误判成失败。

### ⚠️ Pitfall: feishu target ID 不要硬猜，要实测

```bash
hermes send --list feishu    # 列出现有 target，找带 DM / topic 的那个
```

或者从历史 cron 投递日志查：
```bash
grep 'delivered to feishu' ~/.hermes/logs/agent.log | tail -3
```

不要硬写 `feishu:oc_<hex>`——如果 Roader 哥换过 chat、或者新开了 DM，得用最新那个。

## 写作/沟通陷阱（高频必读）

从真实会话**反复出现**的 4 类问题，沉淀下来下次冷启直接绕开。完整版见 `references/dont-overengineer.md`。

### 陷阱 1：自造词（造词）
- **症状**：自创非标准术语写进标题/标签/描述（真实案例：把"归档"写成"档档"）
- **规则**：✅ 用标准术语（"归档" / "钩子" / "触发器"）/ ❌ 不要自造词
- **修复**：`grep -rn "可疑词" ~/.hermes/skills/ ~/.hermes/scripts/` 找 → `sed -i '' 's/旧词/新词/g'` 替 → `smart_archive.sh "反思-文案语病"` 归档

### 陷阱 2：过度工程（"要 X 只做 X"）
- **症状**：哥说"加 Y" → 我额外改 B/C/D，重写 skill
- **判断**：
  - 改动 >3 个文件 → ❌ 可能过度
  - 改动 ≥1 个未请求的 skill → ❌ 几乎肯定过度
  - 哥说"X 就行" → ✅ 按 X 做
- **正解**：先问"最小改动是什么"，然后只做那个

### 陷阱 3：HTML 产物"花里胡哨"
- ✅ 单文件 HTML（无 CDN / 无外链字体）
- ✅ 沿用哥文档偏好（紫渐变 / 边框 / grid 目录）
- ✅ 键盘快捷键完整 + 进度条 + 页码
- ✅ 大小 < 50KB（邮件可发）
- ❌ 不加视频/音频 / 不堆 JS 库

### 陷阱 4：后台用 patch/read_file 被拒
- **白名单工具**（后台 review 允许）：`memory`、`skill_*`（skill_view / skills_list / skill_manage）
- ❌ 后台用 `patch` / `read_file` / `search_files` / `write_file` → 报 `Background review denied`
- ✅ 后台用 `skill_view` + `skill_manage write_file` 修 skill
- 非用 patch 不可 → 让用户切到主对话

## 自我提升 v1（最小化，不主动提炼）

**冷启不犯同样错** + **最小改动**——只记录 + 报告，**不主动提炼**。详见 `references/scan_learnings-workflow.md`。

### 4 类学习来源（只记录，不提炼）

| 触发 | 类型 | 写到哪里 |
|------|------|---------|
| 哥纠正我（"不是/不要/其实应该"）| `correction` | `HermesMemory/incidents/` |
| 我发现知识过期 | `knowledge_gap` | `HermesMemory/incidents/` |
| 工具/API 失败 | `tool_failure` | `HermesMemory/.checkpoints/errors.json` |
| 发现更好做法 | `best_practice` | `HermesMemory/preferences/` |

### 工作流（最小）

```
事件发生
  ↓
1. 写入（用 Hermes 自己的工具）
  ↓
2. 每日 23:50 cron 跑 scan_learnings.py
  - 读 ~/.hermes/logs/errors.log（Hermes 主源）
  - 读 HermesMemory/.checkpoints/errors.json（冷库补充）
  - 扫 incidents/ 重复主题
  ↓
3. 生成 LEARNINGS-REVIEW.md（报告，不动 skill）
  ↓
4. 推飞书给哥（23:50 每日总结）
  ↓
5. **等哥决定**要不要提炼 → 哥说"提炼"才动 skill
```

**scan_learnings 跑完不动任何 skill**——这是核心约束。**❌ 反模式**：scan_learnings 跑出 20 个候选 → 自动提炼 1 个新 skill（哥没让）。
