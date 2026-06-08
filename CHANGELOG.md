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
