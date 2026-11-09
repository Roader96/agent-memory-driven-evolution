# 用记忆改善下一次同类任务

目标是减少重复错误、用户纠正和返工，并更准确地满足当前任务的验收要求。会话、记忆或 skill 数量增加不代表能力提高。

## 已接入的工作流

独立安装器保留原会话归档，新增标准库实现的 `bin/codex_experience.py`，以及全局 `AGENTS.md` 中可重复更新的工作指引：

1. 实质任务开工前，按任务类型、项目和当前约束取得简短经验提示。
2. 阅读适用条件和来源，只采用适用于当前任务的经验。
3. 结束后记录实际采用的记忆、可观察行动、结果与用户纠正。
4. 将明确纠正和有证据的有效做法保存为任务级经验；不要求生成 skill。

这是给 Agent 的工作指引，不是运行时强制拦截的 hook。简单问答无需机械地执行全套流程。原有每 30 分钟归档和 GPT 直接审核保持原有职责，后台维护只读取经验统计，不调用模型、不自动把归档文字提升为有效经验。

## 保存一条经验

以下是合成示例。将来源路径和引文替换为实际证据，再保存为本机 UTF-8 JSON 文件。路径使用绝对路径；相对路径按命令的当前目录解释。文件存在且包含引文，只能证明来源可查，不能替代对其内容和结果的核实。

```json
{
  "memory_id": "mem-mail-navigation",
  "task_family": "email-newsletter",
  "scope": "example-project",
  "conditions": ["制作发往指定邮件客户端的 HTML 特刊"],
  "recommended_action": "先在目标客户端验证导航行为，再制作完整正文；交付前保留兼容性验证结果。",
  "avoid": "仅根据浏览器预览推断邮件客户端中的链接可用。",
  "evidence_level": "user_explicit",
  "status": "active",
  "evidence_refs": [
    {
      "path": "/absolute/path/to/local/source.md",
      "quote": "下次先在目标邮件客户端验证导航。"
    }
  ]
}
```

```bash
python3 ~/CodexMemory/bin/codex_experience.py remember \
  --memory-home ~/CodexMemory --input /absolute/path/to/experience.json
```

`memory_id` 可以省略，由内容生成稳定身份。同一来源不会因重复提交而提高置信度。`user_explicit` 和 `verified_outcome` 代表写入者已核实的证据类别；未知内容使用 `unverified`，只能保存为 `candidate`，不会进入有效经验简报。

修改已有经验时带回实际 `memory_id` 和 `expected_revision`；原版本保留。新经验取代旧经验时使用 `supersedes: {"memory_id": "旧ID", "revision": 1}`，且保持同一项目范围和任务类型。过期 revision 会被拒绝，避免并发覆盖。稳定偏好不会因长期未被读取而自动失效，旧记忆也不能覆盖用户当前明确要求。

## 开工前取得提示和回执

每个任务使用新的唯一 ID；同一任务内再次查询可沿用 ID，但反馈最好显式指定本次回执。

```bash
python3 ~/CodexMemory/bin/codex_experience.py brief \
  --memory-home ~/CodexMemory \
  --query '邮件特刊 HTML 导航与客户端兼容性' \
  --family email-newsletter --project example-project \
  --task-id task-unique-id --max-chars 2400 --limit 5
```

命令默认输出紧凑 JSON：`text` 是受字符预算约束的简报，`receipt_id` 标识本次召回，`retrieved_ids` 和 `revisions` 标识当时实际展示的经验；完整快照留在数据库，需要检查时可使用 `--full`。无匹配结果也保存回执；它不表示任务已经采用了任何记忆。

简报会复核来源可读性；来源已缺失或引文已变更的经验不应当作当前有效做法，并通过警告显式呈现。按经验版本展示的既往使用观察可辅助判断适用性，不能自动当作因果收益评分。

项目经验仅匹配同一项目；`scope=global` 用于证据支持的跨项目经验。指定 `--family` 后按同一任务类型筛选。先选择当前任务相关的经验，再检查其条件；没有相关经验时允许不注入。需要更多背景时，可继续使用关键词召回与可选离线语义检索。

任务类型名称优先沿用已知分类；不确定时省略 `--family`，按当前目标与项目查询，避免临时发明的分类标签排除有用经验。

## 结束后记录实际使用

```json
{
  "task_id": "task-unique-id",
  "receipt_id": "rec-从本次输出复制真实ID",
  "applied_memory_ids": ["mem-mail-navigation"],
  "observed_actions": ["先验证目标客户端的导航，再生成正文。"],
  "user_corrections": [],
  "outcome_status": "unknown",
  "evidence_refs": []
}
```

```bash
python3 ~/CodexMemory/bin/codex_experience.py feedback \
  --memory-home ~/CodexMemory --input /absolute/path/to/feedback.json
python3 ~/CodexMemory/bin/codex_experience.py stats --memory-home ~/CodexMemory
```

`applied_memory_ids` 必须来自该回执的召回集合，实际采用时必须说明行动。结果允许 `verified_success`、`user_accepted`、`failed`、`unknown`；前三种需要真实来源和引文。非空 `user_corrections` 也必须有对应原文引文，即使任务结果为 unknown，避免助手推测被保存成用户纠正。缺少验收证据、没有收到用户反对、工具返回退出码 0，都不能直接证明用户任务成功。完全相同的反馈重试不会重复累计；不同观察保留历史，不覆盖旧结论。

`stats` 只报告检索、实际采用和有证据的结果，缺库时不创建数据库。历史结果类别可能重叠；`accepted_tasks` 是 `ever_accepted_tasks` 的兼容别名，表示曾收到通过报告。当前观察应读取 `latest_outcome_task_counts` 和 `latest_accepted_tasks`：任务后来发现失败，不会仍被算成当前通过。未知和无反馈不算成功，也不应直接用这些计数宣传成功率或因果收益；比较效果仍需在同类新任务上固定模型、工具、预算与评分条件。

## 本地数据与恢复

- 会话卡和现有索引继续作为证据层。
- 经验、版本、召回回执和反馈保存在本机 `.index/experiences.sqlite3`，文件权限为 600。它们可能包含私人信息，不能提交到公共 GitHub。
- 安装器复制代码并更新托管指引，保留指引以外的用户内容；重复安装不重置经验数据库。
- 升级前备份已安装脚本、全局 `AGENTS.md` 和经验数据库。活动 SQLite 数据应通过 `sqlite3.Connection.backup()` 生成一致快照，避免只复制正在写入的主文件。
- 回退时恢复对应脚本和托管指引；恢复数据库前停止当前经验写入，先另存升级后的完整数据库。回退不应通过删除历史版本“清理”记忆。
- 基础归档、经验写入和简报只依赖 Python 标准库；离线 ONNX 模型仍是独立可选组件。

验收应包含新安装、重复安装保留手工指引和经验、无相关经验时空召回、候选隔离、错误来源拒绝、旧 revision 拒绝、回执与实际采用分离，以及 `unknown` 不计为成功。工程门禁通过只证明这些机制工作，不代表真实任务收益已经测得。
