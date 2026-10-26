# Codex 记忆与进化 v2

## 数据安全与身份

账本 schema v2 使用不可变 `uid`，显示编号按已有最大编号递增，在单个独占锁内分配。
迁移会备份旧账本，保留每条提案，并记录 `legacy_id` 和迁移审计。
回测和历史变更根据旧编号、目标及类型匹配；回测还要求对应已完成提案。
无法唯一解析的引用保留原结果，标为 `unresolved/inconclusive`，不进入自动归因。

审批必须匹配唯一编号、目标、UID 和当前阶段。过期勾选留在 `APPROVALS.review.md`，
不会自动执行；有效勾选在重渲染时保留。损坏账本不会变成空账本；并发新增使用事务，
旧版 load/save 调用的过期写入被 revision 检查拒绝。

旧运行环境中的审批意图可以保留在 `status_history`，通过 `reconcile.py` 暂存为 deferred。
这表示需要当前证据复核，不表示技能已修复、被退役或原审批记录被删除。

## 证据口径

- 原始事件为权威来源；LEARNINGS-REVIEW 是派生索引，不再重复计为发生次数。
- 版本横幅和通用“摘要”栏目不形成错误簇；incident 使用实际标题或文件名。
- 周审读取近 30 天有日期的证据，不把无日期记录当成新故障。
- 技能归档状态、全历史需求和近 30 天真实加载失败分开记录。
- 已归档技能不会仅因历史加载被自动建议恢复；没有近期真实失败，不提坏引用。
- Codex 技能目录单独建立基线。无法从本机证据精确证明的使用量是 unknown，不是 0。
- 累计错误增长只证明复发，不能证明失败率恶化或某个技能导致退化。

## GPT 直接审核

先在当前 GPT 会话中完成审核，再通过 Codex 应用安排每周复查。
GPT 直接读取代码、日志和冻结证据包，不需要另一个模型提供方的 API。
旧 LLM 周审可以显式保留用于其他安装；`backend=codex_direct` 时旧编排入口会跳过。

```bash
python3 ~/CodexMemory/bin/codex_evolution.py prepare \
  --legacy-state ~/.hermes/skill_evolution/state.json
```

GPT 读取输出的快照并完成 A1/A2/S1/S2/E1/G1/R1/M1/T1 全部检查。
结果 JSON 必须包含 `reviewer: gpt_session`、该快照 `packet_id`，以及每项 `id/status/detail`。
status 允许 pass/finding/insufficient_data/not_applicable，解释需有实质内容。

```bash
python3 ~/CodexMemory/bin/codex_evolution.py complete \
  --packet /absolute/path/to/evidence.json --result /absolute/path/to/result.json
```

准备证据不等于完成审核。快照篡改、覆盖遗漏和重复检查都会被拒绝。
完整报告与 review-health.json 留在本机，不把私人记忆提交到公开仓库。

每个安装应使用 Codex 应用的自动化工具创建自己的周审；仓库不分发个人调度记录。
本地审核需要电脑开机、应用运行。安装 30 分钟归档本身不代表已创建 GPT 周审。

## 召回与离线语义检索

独立安装器会维护全局 AGENTS.md 中明确标记的召回区块，保留用户其他指令。
后续会话在继续历史工作前先召回，并检查匹配卡片的日期和真实证据。
独立归档默认每 30 分钟执行；macOS 额外保留 23:55 日终兜底。
会话结束时主动归档可进一步缩短延迟，不宣称运行时强制拦截了每五轮对话。

基础归档和关键词召回只需 Python 标准库。离线语义检索是显式可选组件：

```bash
bash scripts/install_codex_semantic.sh
~/CodexMemory/.runtime/bin/python ~/CodexMemory/bin/codex_semantic.py search '过去如何处理类似问题'
```

使用 [multilingual-e5-small 的 ONNX 权重](https://huggingface.co/Xenova/multilingual-e5-small)，
固定 revision、CPU 推理、掩码均值池化与归一化，并用词项和中文二元组辅助重排。
首次安装下载约 134 MB 模型文件及隔离运行库。检索时 local_files_only，不上传文本。
缓存按模型版本和文档内容哈希增量更新；semantic-health.json 记录实际索引结果。
不能推断每个语义结果都正确，应结合关键词、项目和原卡片确认。

## 告警与恢复

监控读取实际选中的审核后端、归档时效、提案身份和语义索引状态。
重复告警按内容指纹去重。只有发送成功才记录已送达；失败保留重试资格。
恢复会清除活动指纹，之后相同问题复发可再次通知。

迁移前同时备份账本、审批文件、安装脚本、全局召回指令和调度文件。
恢复时先停对应任务，恢复整组文件并重载原调度，不能只恢复单个旧 state.json。
模型和运行库是可重建资源；私人记忆和身份迁移记录才是备份重点。

## 验证

```bash
python3 -m unittest discover -s tests -v
bash tests/gate_release.sh
python3 scripts/skill_evolution/verify_evolution_pipeline.py
```

新增回归覆盖真实故障状态：重复编号、编号缺口、并发写入、错误目标、旧勾选、
模糊历史关联、错误证据重复计数、告警失败重试和 GPT 审核覆盖不足。
离线模型需要单独执行真实编码和检索验证，基础 CI 不下载模型。
