# 项目型任务收尾主动归档 recipe（2026-08-10 验证）

> Roader 规则：**带项目目录的任务收尾后主动存档冷存储，不用哥提醒**。本 recipe 是可复制的执行步骤。

## 0. Vault 判定（先做这个，别写错）

Roader 的 OB = `~/HermesMemory/`（唯一）。`~/Documents/Obsidian Vault` 不是归档目标。

拿不准时看哪个 vault 是 Obsidian 实际打开的：

```bash
cat "$HOME/Library/Application Support/obsidian/obsidian.json"
# 找 "open":true 的那个 vault.path
```

## 1. 目录结构（和现有项目一致）

```text
projects/<项目名>/
├── YYYY-MM-DD-<标题>.md   # 内容主体
└── TIMELINE.md            # 项目时间线索引
```

❌ 反模式：只丢一个 `TIMELINE.md` 装全部内容（哥 2026-08-10 指出「里面只有一个 timeline 跟你之前的版本不一样」）。
✅ 正模式：日期文件放内容，TIMELINE 只做索引。

## 2. 日期文件模板

```markdown
---
created: YYYY-MM-DD
tags: [project, <主题>, obsidian-archive]
---

# <标题>

> **归档时间**：YYYY-MM-DD
> **分类**：projects/<项目名>
> **触发**：手动存档 / smart_archive

## 内容
（产物路径、源仓库、commit、技术口径、验证结果、坑）

## 相关

- [[INDEX|📑 记忆总目录]]
- [[projects/<项目名>/TIMELINE|<项目名> - 项目时间线]]
```

## 3. TIMELINE.md 模板

```markdown
# <项目名> - 项目时间线

> **项目建立**：YYYY-MM-DD
> **归档条数**：N
> **最近更新**：YYYY-MM-DD HH:MM

## 📅 按时间排序

### YYYY-MM-DD - <标题>

- [[YYYY-MM-DD-<标题>]]

## 🔗 相关

- [[INDEX|📑 记忆总目录]]
```

## 4. INDEX.md 收尾

- `🔥 当前项目` 列表加 `- [[projects/<项目名>/TIMELINE|<项目名>]]`
- 更新 `总归档文件` / `项目数` / `最后更新`

## 5. vault_postprocess 重写坑（2026-08-10 实测）

自动后处理可能把 TIMELINE 的条目标题重写成 `### YYYY-MM-DD - ---`（中文文件名标题提取失败）。

- **症状**：TIMELINE 里出现 `- ---` 空标题、归档条数对不上
- **处理**：直接 `write_file` 手写 TIMELINE.md 覆盖，不用等脚本修
- **预防**：日期文件第一行给清晰 `# 标题`，少用复杂 frontmatter

## 6. 2026-08-10 实例（AI转型系统-CICD分享）

```text
projects/AI转型系统-CICD分享/
├── 2026-08-10-AI转型系统-CICD分享项目存档.md
├── 2026-08-10-AI转型系统-CICD分享宣传海报.md
└── TIMELINE.md
```

要点：先读项目目录的 `AGENTS.md`；产物、口径、验证方式都进日期文件；TIMELINE 只放链接。
