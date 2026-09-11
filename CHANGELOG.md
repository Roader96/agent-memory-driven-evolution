# Changelog

All notable changes to Hermes Mind will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial public release
- 10 executable scripts
- 3 core skills (auto-memory-archiving / self-improvement / tool-restrictions)
- Sample vault with 5 demo files
- PPT-style overview HTML (16 slides)
- Full documentation suite

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

[Unreleased]: https://github.com/Roader96/Hermes-Mind/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Roader96/Hermes-Mind/releases/tag/v1.0.0
