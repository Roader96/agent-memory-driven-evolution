# 强制归档三件套（2026-08-15）— 零自觉，机制保证

> 背景：哥连骂两轮「你哪有自觉性 自觉就=说空话」「也是靠自觉？」。归档不能靠 agent 记性，必须由脚本/plugin/cron 强制触发。三件套 = 写入门禁 + 会话结束自动归档 + 历史回填。

## 🚫 禁「自觉」叙事（最高硬规则）

- agent 没有自觉性，「靠我自觉执行」「我会主动归档」= 说空话。
- 方案里不许出现「我主动」「我会记得」「靠自觉」类表述。
- 一切流程靠强制机制：脚本硬检查 / cron 看门狗 / plugin hook / 门禁拒写。

## ① smart_archive.sh 摘要门禁（2026-08-15 已上线）

`~/.hermes/scripts/smart_archive.sh` 在写入前强制检查（不通过 exit 1 拒写）：

```bash
# ============ 强制检查：必须有摘要 ============
if ! echo "$CONTENT" | grep -q "^## 摘要"; then
  echo "❌ 拒绝归档：内容必须有「## 摘要」段落"
  exit 1
fi
# 摘要 ≥10 字符（去空白后），否则拒写
SUMMARY=$(echo "$CONTENT" | sed -n '/^## 摘要/,/^##/p' | sed '1d;$d' | tr -d '[:space:]')
if [ ${#SUMMARY} -lt 10 ]; then
  echo "❌ 拒绝归档：摘要太短（至少10个字符）"
  exit 1
fi
```

写入模板也改了：不再自动加「## 内容 / ## 关键要点」空模板（空壳来源），直接落 `$CONTENT`。

**验证**：无摘要 → exit 1 拒写；有摘要 → 正常写入 + 后处理。

## ② auto-archive plugin（2026-08-15 已上线，不改 core）

位置：`~/.hermes/plugins/auto-archive/`（**user plugins 目录**，`hermes update` 不会覆盖；放 bundled `~/.hermes/hermes-agent/plugins/` 会被 git pull 覆盖！）

- `plugin.yaml`：声明 `provides_hooks: [post_tool_call, on_session_end]` + `hooks:` 同列表（doctor 会 WARN 如果缺 provides_hooks）
- `__init__.py`：
  - `post_tool_call`：检测 `write_file` / `patch` / `terminal`（含 `> `、`>>`、`tee`、`heredoc`、`cat <<`、`cp`、`mv`、`python -c` 等创建信号）产生的新路径，过滤 `/tmp/`、`~/.hermes/`、`~/Library/`、`.tmp` 等临时/系统路径，按 session_id 记录 `{paths, first_seen, tool_calls}`
  - `on_session_end`：Hermes 在**会话真正结束**（expiry/teardown/reset）时触发一次，**不是每轮**（每轮是 `on_turn_complete` 之类）；drain 该 session 的 trace，有交付物就调 `smart_archive.sh`（自动过摘要门禁）归档到 `projects/auto-archive/`

**启用**：`hermes plugins enable auto-archive` → `hermes plugins doctor auto-archive` 全绿（2 hooks registered）。
**验证**：`python3 -c` 直接调 `_on_post_tool_call` + `_on_session_end`（sys.path 加 plugins 目录，用 importlib 加载），确认 /tmp 被滤、桌面项目文件被记录、drain 后清空、归档真的落盘。

**会话结束定义**（哥问的关键）：`on_session_end` 是会话边界（超时/关闭/reset）触发一次；跨天不结束的会话由 daily cron 23:50 兜底。长会话里干完的活，结束或当晚必归档。

## ③ 历史回填方法（6-8 月缺失归档补回）

1. `hermes sessions list --limit 200 | grep 月份 | grep -v cron` 筛非 cron 会话
2. `session_search(query="完成 OR 产出 OR 修复 OR 解决 OR 部署 OR 搭建", sort=oldest)` 多关键词组合扫（NAS/3D打印/exam-system/亿纬锂能/优化/bug/报告 等换词再搜）
3. 命中后看 `bookend_start`（前因）+ `messages`（过程）+ `bookend_end`（结论），提炼「摘要 + 完成内容 + 产出物」
4. `smart_archive.sh "标题" "$CONTENT" "项目标签"` 归档（现在会被摘要门禁检查）
5. 重新生成该日期 daily：`rm -f ~/HermesMemory/daily/${date}-每日总结.md; DATE_OVERRIDE=$date TIME_OVERRIDE=23:50 python3 ~/.hermes/scripts/daily_summary_enhanced.py`

## ④ daily_summary_enhanced.py（替代空壳统计）

`~/.hermes/scripts/daily_summary.sh` 已 patch 调 `daily_summary_enhanced.py`：读归档正文、优先提取「## 摘要」段落、支持 `DATE_OVERRIDE`/`TIME_OVERRIDE` 环境变量回填历史日期、输出 `$VAULT/daily/${DATE}-每日总结.md`。解决 pitfall #9（只数数不读内容）。

## 归档标准 v2 摘要

只记实质成果（完成了什么/产出了什么/踩了什么坑/修复了什么/做了什么决策），不记流水账（读了什么/确认了什么/验证了什么）。完整版见 `references/archive-standard-v2.md`。

## 本次回填成果（示例，供以后参考）

8月：AI特攻队课题7海报、token看板门禁+大改版+修复、DeepSeek余额监控、A股监控赛博朋克卡片+飞书直发链路、第一性原理HTML(初版+实战演练)、AI转型系统CICD分享、优秀AI组织研究、发票批量核对、Hermes配置查证、GLM对比报告；7月：卸载openclaw/OpenHuman、A股HOLIDAY_DAYS修复、灯塔行动会议纪要PPT；6月：记忆系统v3完工、亿纬锂能深度分析、股票报告模板修复、Memory体检。Vault 202→214 文件，重生成 18 天 daily。
