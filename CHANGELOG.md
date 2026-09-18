# Changelog

All notable changes to xxzAgentMemory will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **归档防目录穿越**：标签白名单净化 + 最终路径 resolve 校验（逃出 vault 即拒绝）
- **同名归档不再覆盖**：自动追加时间戳 + O_EXCL 原子占位（并发归档零丢失）
- **Generic 模式数据可信门禁**：无真实使用数据时，cap 自动禁用/退役提案自动转为人工审批
- **安装器供应链收紧**：默认不再自动下载 Obsidian；`--install-obsidian` 显式开启时固定版本 + HTTPS/TLS 限定 + 下载校验 + 失败即退
- **`AGENT_LLM` 默认不过 shell**：`shlex.split` 解析，显式 `AGENT_LLM_SHELL=1` 才允许 shell 语法

### Added
- `install_codex_memory.sh`：Codex 独立结构化记忆安装器，默认运行脚本落在 `~/CodexMemory/bin/`，macOS 使用独立 `com.codex.memory` LaunchAgent
- `scripts/codex_run_maintenance.sh`：Codex 独立维护 wrapper；删除 `~/.hermes` 和 `~/HermesMemory` 后仍可运行
- `tests/test_archive_security.sh`：归档安全测试（路径穿越 / 同名覆盖 / 并发 / 自定义 vault）
- `tests/test_core_logic.py`：核心逻辑单测扩展（schema 迁移 / 伪零保护 / LLM shell 策略）
- `state.json` schema 迁移框架（版本检测 + 自动备份 + 迁移链）
- 路径配置单一来源 `skill_evolution/paths.py`（`HERMES_VAULT` / `HERMES_HOME` 统一）
- 自建技能保护前缀可配置（`SELF_SKILL_PREFIXES` 环境变量）

### Changed
- Codex 结构化记忆维护与 Hermes 彻底分离：默认数据、脚本、日志和锁均位于 `~/CodexMemory/`，不写入 `~/HermesMemory/codex/`；Hermes watchdog 和卸载器都不再调用或停用 Codex 调度
- 技能用量统计改用 `tool_call_id` 精确关联工具结果（并行调用不再归因错误）
- Smart Connections 插件真实安装检测（写配置 ≠ 已安装，未装时给手动指引）

### Removed
- `docs/overview.html`（v1 时代的展示页，内容已与当前架构脱节）

## [2.1.1] - 2026-09-11

### Added
- **Agent 适配层** `scripts/adapters/agent_adapter.py` — 跨 agent 兼容
  - 统一抽象 `detect / skill_facts / llm_call / archive_session` 四接口
  - Hermes 模式（state.db + hermes chat）↔ 通用降级（目录扫描 + AGENT_LLM）
- **其他 agent 接入指南** `docs/AGENT_ADAPTATION.md` — Claude Code / Codex / Cursor 3 分钟接入

### Changed
- 核心模块（metrics/outcome_scorer/preference_signals/backfill/librarian/preference_miner）去掉 Hermes 硬依赖，改走适配层
- 路径环境变量化（HERMES_HOME / HERMES_BIN / AGENT_LLM），不再写死 `~/.hermes`

## [2.1.0] - 2026-09-11

### Added
- **标准化安装器** `install.sh` — 一键安装（交互/静默/自定义 vault），自动检测平台 + 依赖 + Obsidian
- **卸载器** `uninstall.sh` — 备份后卸载（幂等、可 `--keep-vault` 保留记忆库）
- **跨平台支持** — macOS + Linux
  - `scripts/lib/platform.sh` 平台兼容层（date/stat/sed 差异统一处理）
  - 定时任务：macOS → launchd，Linux → crontab 自动切换
  - `osascript` 通知仅 macOS 执行，Linux 跳过
- **Obsidian 硬依赖** — 永久记忆 vault 载体（非可选）
  - 安装器自动检测，缺失时引导/自动安装（macOS DMG / Linux AppImage）
  - vault 自动初始化 `.obsidian/` 配置（app.json + Smart Connections 插件位）
- **发布安全检查** — 自动化验证（语法/密钥/敏感信息）确保发布质量

### Changed
- 技能命名统一为 `user-*`（保护逻辑兼容多种前缀）
- 示例内容重写为通用虚构样例（不绑定任何真实项目）
- 移除不再维护的旧文档（历史迭代产物）

## [2.0.0] - 2026-09-11

### Added
- **技能自进化系统**（skill-evolution）— Ratchet 论文方法 + mem0 + agent-memory-loop
  - 每周自动审计技能库：metrics → canonicalize → curator → librarian → 提案队列
  - 只提案、不擅自改技能（硬铁律，人工审批后执行）
  - 技能数硬 cap（默认 120，超额自动软禁用零加载技能）
  - 偏好挖掘（preference_signals + preference_miner）：从纠正信号中学习用户习惯
  - 提案效果追踪（followup）：7 天回测，执行了≠有效
  - 冷库联动：vault_mentions_90d 豁免技能退役误杀
  - 验证器 verify_evolution_pipeline.py（44 断言）
- **每日成长检查** — 自省段 + 纠正信号扫描 + 复发检测（daily_growth_check）
- **记忆系统 v3 升级**
  - 热记忆看门狗静默模式（写标记文件，不推飞书）
  - 归档标准 v2（必须写摘要段 + 产出物路径）
  - 冷库联动信号（vault_solutions / vault_mentions_90d）

### Changed
- 记忆归档 skill 重构为 v3（合并 self-improvement）
- launchd 定时任务：skill-evolution-weekly（周日 21:30）/ hermes-daily-watchdog（23:55）
- **标准化安装/卸载**：新增 `install.sh`（交互/静默/自定义 vault）+ `uninstall.sh`（备份 + 幂等 + 保留 vault 选项）
- **跨平台支持**：新增 `scripts/lib/platform.sh` 平台兼容层
  - macOS (BSD) + Linux (GNU) 统一 `date`/`stat`/`sed` 差异
  - 定时任务：macOS 用 launchd → Linux 自动用 crontab
  - `osascript` 通知仅 macOS 执行，Linux 跳过
  - plist 改为模板（`__HOME__`/`__SCRIPTS_DIR__` 变量），消除硬编码路径
- **移除 v1 遗留**：删除 hermes-* 旧版 skills（已并入 user-* v3 版）
- **新增集成测试** `tests/test_install.sh`：临时 HOME 隔离验证安装/卸载全流程（13 断言）

## [1.0.0] - 2026-06-08

### Added
- **Two-tier memory architecture** (hot: 2,200 chars / cold: unlimited)
- **Auto-archiving hook** with 4 trigger points (5 turns / 30 min / 1,500 chars / 1,800 chars)
- **Smart classification** (4 categories: daily / projects / preferences / incidents)
- **Vault post-processor** (5 things: backlinks / timelines / INDEX / README / ERRORS)
- **Error logging system** (auto_log_error.py with Python + CLI interfaces)
- **Daily summary cron** (23:50, push to Feishu DM)
- **Obsidian integration** with Smart Connections plugin (local ONNX, zero API key)
- **Self-improvement mechanism** (auto-extract skills from high-frequency errors)

### Features
- Zero-config vault path (`~/Documents/HermesMemory` default, `HERMES_VAULT` env override)
- Backward compatible (old `save_to_memory.sh` / `auto_daily_snapshot.sh` retained)
- All paths user-configurable
- Comprehensive documentation (4 docs + 16-slide HTML)

### Security
- `HERMES_VAULT` env var prevents hardcoded paths
- `.gitignore` excludes personal vault + secrets

[Unreleased]: https://github.com/Roader96/xxzAgentMemory/compare/v2.1.1...HEAD
[2.1.1]: https://github.com/Roader96/xxzAgentMemory/releases/tag/v2.1.1
[2.1.0]: https://github.com/Roader96/xxzAgentMemory/releases/tag/v2.1.0
[1.0.0]: https://github.com/Roader96/xxzAgentMemory/releases/tag/v1.0.0
