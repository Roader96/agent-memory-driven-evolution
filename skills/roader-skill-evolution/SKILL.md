---
name: roader-skill-evolution
description: 技能自进化系统。提到技能退役、坏引用、提案队列 P0xx 审批时用。
---

# 技能自进化系统（2026-09-10 建成）

借鉴 Ratchet 论文（SkillsBench：LLM 自写技能 +0.0pp vs 人工精选 +16.2pp，瓶颈在生命周期管理）+ mem0（ADD-only）+ agent-memory-loop（提案队列）。**核心铁律：系统只出提案，绝不自动改技能，哥点头才执行。**

## 架构（~/.hermes/scripts/skill_evolution/）

| 模块 | 职责 |
|---|---|
| metrics.py | 从 state.db 采每个技能：加载会话数/自身报错/维护频次/任务级弱 outcome。只测得准的信号，不伪造疗效 |
| canonicalize.py | 错误模式归一化（normalize_key/cluster/load_all_failures），同一 bug 两种描述合并计数 |
| outcome_scorer.py | 会话收尾打分 success/fail/uncertain（弱启发式，带 confidence） |
| curator.py | 规则提案：坏引用/损坏修复/退役候选（首期只观察不退役，基线须≥3天前快照） |
| librarian.py | LLM 周审（hermes chat --source skill-evolution-librarian，跑完自动 archive），复发≥3次簇强制覆盖门禁，提案解析入队 |
| state.py | ~/.hermes/skill_evolution/state.json（ADD-only：snapshots/proposals/failure_memory） |
| run_weekly.py | 编排器，launchd 周日 21:30 `com.roader.skill-evolution-weekly`（metrics→cap→curator→followup→librarian→飞书） |
| cap_enforcer.py | 硬 cap=120（哥 2026-09-10 授权）：超额自动软禁用零加载+≥90天+非自建，按体积降序；`--restore <名>` 恢复；动作落 cap_log |
| approve.py | `python3 approve.py list / approve P001 / reject P001 / undo P001`；retire 类自动写 config skills.disabled（软禁用可逆，ESSENTIAL_SKILLS 有保护） |

## 踩过的坑（别再犯）

1. **evidence 截断**：PROMPT 截 12000 字符，簇太多会把后面的切掉，模型看不见却被门禁检查 → 必降级。error_clusters 只取 top10+例证精简到 80 字，总长须 <8k。
2. **incidents 目录混杂**：「会话总结/架构图」不是失败！canonicalize 按文件名过滤（FAIL_HINT 必须命中 + SKIP_HINT 排除），否则普通归档变假痛点簇。
3. **覆盖门禁按复发阈值不按名次**：count≥3 的簇强制引用，count=2 模型取舍。强制全覆盖=逼模型为噪声提案=技能膨胀。
4. **首期基线穿透**：run_weekly 存快照后 librarian 同轮再跑 curator，「上一期快照」就是自己 → 44 个老技能被误提退役。基线必须 ≥3 天前。
5. **提案漂移**：模型每周对同一问题换着提法。evidence 必须喂 pending 列表 + prompt 禁止重复提。
6. **桌面长会话 ended_at 永为 NULL**（gateway 保活），不能用它判「进行中」；archived=1 只是 UI 隐藏不是无效历史。
7. **同会话多技能**：任务成败无法归因单技能（SkillSmith 批的孤立评估谬误），outcome 只做全局健康度。
8. **proposal 解析**：模型的 理由/证据/动作 可能挤在同一段，正则不许依赖换行。
9. hermes chat stdout 会混 `Warning: Unknown toolsets` 行，需过滤。
10. 系统 python3 = 3.9：文件头加 `from __future__ import annotations` 才能用 `dict | None`。
11. **metrics 技能名必须读 frontmatter `name` 字段，不是目录名**（hermes 就是这么解析的）：目录 `azure-flux-image-gen` 的 name 是 `flux-image-gen`、`Roader-mac-uninstall-suite` 大写 R 目录的 name 小写。且匹配要大小写不敏感。曾因此误报 3 个健康技能为坏引用（P007/P008/P053 被 reject）。
12. **broken_ref 里要区分「磁盘损坏」vs「历史尝试加载不存在的名字」**：后者无文件可修，正确动作是记 failure_memory 防再试，不是修复。optional-skills 目录的技能未安装时 skill_view 必失败，也算此类。
13. **回填历史基线会穿透首期保护**：backfill_snapshots.py 从 state.db 按周切片重建历史后，retirement 立马有基线 → 首批会大批量误提。退役必须**每周限量**（MAX_RETIRE_PER_WEEK=5，按体积降序小步收敛），因为「全历史零加载」的技能多期基线过滤在逻辑上无效（每期都零）。
14. **followup.py 效果追踪**：提案 done 自动挂 7 天回测（cluster 簇复发数 / ref_loads 加载增量），worse 的进 librarian evidence 强制复盘——执行了≠有效。
15. **outcome_scorer 用户反应信号**：assistant 收尾后的用户短消息（<60字）匹配纯反应词（谢谢/👍/不对/怎么又），优先级高于 assistant 自述（无自我表扬偏差）；librarian 自己的会话（source=skill-evolution-librarian）必须在 SKIP_SOURCES 里，否则提案文本被误评。
16. 快照同天去重（backfill/调试多次跑只留当天最后一期）。
17. **硬 cap 已落地（cap=120，2026-09-10 首执行 142→120，禁用 22 个）**：cap 与限量退役并存——cap 管总量自动砍，curator 每周 5 个做常规收敛；cap 受害者必须挂 ref_loads 回测（禁用后还被加载=误杀，7 天后查）；被 cap 禁用的 pending retire 提案自动标 done。验证器 verify_evolution_pipeline.py 44 断言（E 组管 cap、F 组管冷库）。
18. **冷库联动（哥 2026-09-10 指出盲区后加）**：metrics 新增 vault_mentions_90d——扫 ~/HermesMemory 近 90 天 md（daily/projects/preferences/incidents）里技能名出现次数。用途：① cap/curator 退役豁免——冷库有痕迹=知识被激活过（可能描述注入后无 view 照用），宁可误留不误杀，转人工复核 ② librarian 每个错误簇带 vault_solutions（冷库近 180 天关键词命中的历史方案文件），提案优先从已有经验提炼不从零造。**注意噪声**：技能名常和命令名撞（wrangler CLI 真用了≠wrangler 技能加载），所以冷库信号只作豁免/提示不作精确用量，短名（<6字符）不匹配。真实案例：wrangler 被 cap 首砍，冷库 CICD 存档里有 wrangler 部署痕迹→自动救回，cap 改砍无痕迹的 hermes-deployment 压回 120。
19. **正向成长主航道（哥 2026-09-10 定调：砍 skill 是副航道，学会哥的习惯才是主航道）**：preference_signals.py 从 state.db 挖三类信号（纠正=哥否定我产出+我当时产出配对/认可/习惯祈使）；preference_miner.py 每周归纳成偏好候选（PRELUDE/CIPHER 论文+emulo 方案，最大 6 条、可执行不许空话、带证据、去重）；approve_pref.py 审批；批准后**由 agent 用 memory/write_file 写进 ~/.hermes/memories/USER.md**（USER 是权威源，脚本无权改人格）；7 天回测纠正信号是否减少。首轮已归纳 5 条并全部批准写入（2026-09-10）。
20. **偏好归纳坑**：① PROMPT.format 里花括号 `{n}` 必炸 KeyError——占位符只给模板变量，正文转义 ② USER 磁盘文件与 memory 索引分块脱节，memory replace 的 old_text 可能匹配不上——先 read 磁盘再决定，必要时 write_file 直接改（先备份）③ 匹配纠正词条时 K 在词不在（用户消息≠纠正），只取纯反应短消息。
21. **两路并进 + 每日自省（哥 2026-09-10 定调）**：副航道（防变笨：cap=120/退役/坏引用）和主航道（变聪明：学哥习惯/纠正）必须同时跑，不能只修一个。每日 watchdog 三件事：① daily_summary 润色 prompt 强制 `## 🧠 自我审视` 段（基于 growth 素材：今天哥纠正几次/集中在什么模式/我最强 agent 差在哪/明天具体动作），证据版兜底也带自省段 ② daily_growth_check 纯规则扫描（复用 collect_day，同类纠正近3天≥2次标复发，趋势写 state preference_trend）③ watchdog 成长门禁：无自省段 exit 1 告警。
22. **自省段必须可执行不许空话**：润色 prompt 明确"不许'我会更努力'"、要求≤3 条可验证动作（如"先确认渲染通道再交付 md"）；若当天 0 纠正且 7 天降则写"今日无纠正，继续巩固"——不是天天自贬，是拿数据说话。
23. **润色 brief 截断坑**：daily_summary 10+ 会话时 brief 60k 字符被 `[:14000]` 一刀切 → 模型漏 S7-S10 → 覆盖门禁降级（不是模型笨，是喂少了）。修：conclusions 压 600→300→260、user_msgs 5→4→2，且把 brief 上限提到 30000（模型 8k token 装得下）——保证 S1-S10 全进 prompt 才不漏。

## 哥的操作

- 看周报：`~/HermesMemory/skill-evolution/YYYY-MM-DD-skill-evolution-weekly.md`
- 审批：会话里说「批准 P005」→ 我跑 approve.py；或「P006 否了」→ reject 进 failure_memory 防复活
- 手动触发：`python3 ~/.hermes/scripts/skill_evolution/run_weekly.py`

## 通知方式（2026-09-10 哥定稿）

- **周报提醒走飞书 DM**（send_feishu_dm.py），完整提案清单一条发全；系统通知已弃——macOS 横幅只显示一两行看不全，点开还跳脚本编辑器
- 0 提案 → 全静默；飞书挂 → osascript Mac 通知兜底
- 飞书排版用纯文本列表（飞书 markdown 表格/标题会丢，老坑）
