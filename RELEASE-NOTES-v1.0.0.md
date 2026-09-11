# Hermes Mind v1.0.0 — Initial Release 🎉

**发布日期**：2026-06-08
**类型**：🎉 Initial Public Release
**下载**：[Source code (zip)](https://github.com/Roader96/agent-memory-driven-evolution/archive/refs/tags/v1.0.0.zip) · [tar.gz](https://github.com/Roader96/agent-memory-driven-evolution/archive/refs/tags/v1.0.0.tar.gz)

---

## 🎯 这是什么

**Hermes Mind** 是给 AI 助手用的**持久化记忆系统**。解决"会话结束 = 上下文丢失"这个老大难。

> "我希望你明天还记得今天讲过什么。" — Roader

---

## ✨ 核心能力

### 🧠 零丢失双层记忆
- **热记忆** — system prompt 注入，2,200 字符限制
- **冷记忆** — Obsidian vault，无上限
- **实时归档** — 每 5 轮 / 30 分钟 / 阈值告警

### 🔄 智能分类
- 4 大类别：`daily` / `projects` / `preferences` / `incidents`
- 新话题自动建项目子目录
- 绝对保留字：`daily/preferences/incidents` 不被项目归并劫持

### 🛠 Vault 后处理（5 件事）
1. 反向链接注入（`[[wikilinks]]`）
2. 项目时间线生成（按时间排序）
3. INDEX.md 维护（3 列 grid）
4. README.md 维护（vault 门面）
5. ERRORS.md 维护（错误统计）

### 🔍 语义搜索
- 集成 [Smart Connections](https://github.com/brianpetro/obsidian-smart-connections) 插件
- 本地 ONNX 模型，**零 API key**
- 首次启动自动下载 ~30MB

### 📊 错误记录与自我提升
- 自动记录所有工具调用失败
- 每日扫 Hermes 自带 `logs/errors.log` 找高频
- 提炼候选生成 `LEARNINGS-REVIEW.md`

### ⏰ 自动化
- cron 23:50 跑 `daily_summary.sh`
- 自动推飞书 DM（可选）
- 完整工作流无需人工干预

---

## 📦 包含

| 模块 | 数量 | 说明 |
|------|------|------|
| 脚本 | 10 个 | 归档/后处理/钩子/计数/错误/扫描/总结 |
| Skills | 3 个 | 工作流文档（auto-memory / self-improvement / tool-restrictions）|
| 文档 | 4 个 | installation / usage / architecture / troubleshooting |
| HTML | 1 个 | 16-slide PPT 概览 |
| 示例 vault | 5 文件 | 用户可直接 fork 玩 |

---

## 📊 实战数据（v1.0.0 发布时）

```
✅ 22 个 vault 归档文件
✅ 2 个项目（NAS / 3D 打印）
✅ 3 条偏好
✅ 6 条踩坑
✅ 4 篇 daily
✅ 401 条错误统计
✅ 20 个高频提炼候选
✅ 39% 热记忆用量（健康）
```

---

## 🚀 3 步上手

```bash
# 1. 克隆
git clone https://github.com/Roader96/agent-memory-driven-evolution.git
cd agent-memory-driven-evolution
cp -R skills/* ~/.hermes/skills/
cp scripts/* ~/.hermes/scripts/
chmod +x ~/.hermes/scripts/*

# 2. 装 Obsidian
brew install --cask obsidian
# 或从 https://obsidian.md 下载

# 3. 用起来
~/.hermes/scripts/smart_archive.sh "标题" "内容" "标签"
# 然后打开 Obsidian → Open folder as vault → ~/Documents/HermesMemory
```

详见 [docs/installation.md](https://github.com/Roader96/agent-memory-driven-evolution/blob/main/docs/installation.md)

---

## 🎬 截图（建议 PR 补充）

> 📸 提交 PR 时附上你的 Obsidian 截图，能让 README 更有说服力

---

## 🐛 已知问题

| 问题 | 状态 | 解决 |
|------|------|------|
| macOS screencapture 在某些权限下失败 | 不影响使用 | `System Preferences > Security & Privacy > Screen Recording` 授权 |
| Smart Connections 首次启动需下载 30MB 模型 | 一次性 | 等 1-2 分钟 |
| Linux/Windows 路径需手动改 | 文档未覆盖 | 改 `HERMES_VAULT` 环境变量 |

---

## 🤝 贡献

欢迎 PR！建议流程：
1. Fork → 新分支
2. 写代码 + 跑 `vault_postprocess.py` 测试
3. 提交 PR 时附 `ERRORS.md` 现状

---

## 📜 License

MIT © [Roader](https://github.com/Roader96)

---

## 🙏 致谢

- [Obsidian](https://obsidian.md) — 优秀的 vault 设计
- [Smart Connections](https://github.com/brianpetro/obsidian-smart-connections) — 语义搜索能力
- [Hermes Agent](https://hermes-agent.nousresearch.com) — 自我提升机制灵感
- [OpenClaw](https://github.com/openclaw) — self-improvement 框架参考（最终未采用，但启发良多）

---

## 📚 进一步阅读

- [README](https://github.com/Roader96/agent-memory-driven-evolution)
- [PPT 概览（16 slides）](https://github.com/Roader96/agent-memory-driven-evolution/blob/main/docs/overview.html)
- [架构设计](https://github.com/Roader96/agent-memory-driven-evolution/blob/main/docs/architecture.md)
- [故障排查](https://github.com/Roader96/agent-memory-driven-evolution/blob/main/docs/troubleshooting.md)

---

**如果觉得有用，请给个 ⭐ Star！**
