# 运行健康与历史保留

定时任务退出码为 0 只说明编排完成，不能证明 LLM 审查或历史覆盖完整。

## Codex 归档

`codex_memory.py` 将新会话与 `.index/sessions.jsonl` 中的历史记录合并。
原始 JSONL 被客户端移走、清理或只剩会话尾部时，保留已有完整摘要和卡片。
索引发生变化前保留 `.index/sessions.jsonl.bak`；损坏的旧索引会阻止重建，避免静默覆盖。
这是永久归档，不随源文件删除自动遗忘；需要删除记忆时应显式处理归档和索引。

`~/CodexMemory/.index/health.json` 记录：

- `indexed_sessions`：可检索的会话总数。
- `source_sessions`：本次从原始目录读到的会话数。
- `retained_missing_source`：源文件已不可见、由历史归档保留的条目数。
- `retained_partial_source`：源文件不完整或更旧，继续保留完整历史摘要的条目数。

缺少源文件不等于归档失败；历史条目仍可召回。保留摘要不能替代丢失的原始逐条证据。
部分会话源不足时采用保守策略，直到完整源恢复前不会用短摘要覆盖长摘要。

```bash
cat ~/CodexMemory/.index/health.json
python3 ~/CodexMemory/bin/codex_memory.py --recall '项目关键词'
```

## 技能周审

证据在完整 JSON 内按字段压缩，保留所有必查编号。提示词要求逐项说明处理意见，
允许“已有提案覆盖”或“证据不足暂缓”，不要求为每个错误创建新技能。
漏覆盖时最多追加一次内容修复；持续失败则保留规则提案，记录准确降级原因。
Hermes 批量审查关闭工具并限制为一轮，避免审查变成漫长的工具执行。
使用新版 Hermes 支持的 `source=tool`，原组件来源保留在提示词标记和适配器日志中。
`tool` 集成会话与历史内部 source 一起排除在用户日报、偏好信号和任务成功率之外。

健康记录位于 `<vault>/.checkpoints/evolution-health.json`，包含时间、状态、原因、
调用次数和必查编号。早间监视器检查降级及超过 9 天未更新的记录。
没有新健康记录时，会检查已有最新周报。仅部署了 Codex 的安装不会因未装周审误报。
旧自动更新状态仅在显式设置 `CHECK_AUTO_UPDATE=1` 时检查。

直接运行 `librarian.py` 会生成审查报告并将有效提案入队，不执行技能修改，也不发送周报。
`run_weekly.py` 仍沿用现有审批和通知流程。生产脚本升级前应备份，按文件更新，
避免覆盖本机已有的偏好自动生效等定制策略。

## 回测口径

累计错误计数增加只能证明复发，无法证明错误率恶化或某个技能导致退化。
此类结果列为 `inconclusive` 并进入复盘清单。历史原始回测记录保持不变，
汇总按新口径解释，不再重复报告未经支持的趋势结论。
技能加载遥测缺失或累计数下降同样不证明改善；观察次数持平为 `no_change`。

## 验证

```bash
python3 -m unittest discover -s tests -v
bash tests/gate_release.sh
WATCHDOG_SILENT=1 bash scripts/watchdog_monitor.sh
```

测试覆盖源文件消失、部分会话恢复、索引损坏、历史召回、完整证据预算、
覆盖修复重试、真实降级原因、监视器内容检查和累计计数的诚实解释。
