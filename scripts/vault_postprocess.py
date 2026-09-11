#!/usr/bin/env python3
"""
vault_postprocess.py - 冷库后处理器
1. 扫所有 .md 提取标题，建全局标题索引
2. 给每个文件底部追加 Related Links 段（含 [[wikilinks]]）
3. 为每个 project 子目录生成 TIMELINE.md（按时间排序）
4. 给 INDEX.md 注入完整目录树
"""

import os
import re
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

VAULT = Path(os.environ.get("HERMES_VAULT", Path.home() / "HermesMemory"))
SKIP_DIRS = {".obsidian", ".checkpoints", ".trash"}

# ============ 扫所有文件，建标题索引 ============
def scan_vault():
    """返回: {filename_stem: (full_path, title)}"""
    index = {}
    for md in VAULT.rglob("*.md"):
        # 跳过系统目录
        if any(skip in md.parts for skip in SKIP_DIRS):
            continue
        try:
            with open(md, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
        except Exception:
            continue
        # 提取标题
        title = re.sub(r"^#\s*", "", first_line).strip()
        if not title:
            continue
        # key 用相对路径（无后缀）
        rel = md.relative_to(VAULT).with_suffix("")
        index[str(rel)] = (md, title)
    return index


# ============ 1) 注入反向链接到每个文件 ============
def inject_related_links(index):
    """给每个 .md 底部加 ## 相关链接 段（指向 INDEX 和同目录文件）"""
    updated = 0
    for rel_str, (path, title) in index.items():
        rel_path = Path(rel_str)
        # 决定要链什么
        related = []

        # 永远链 INDEX
        related.append(("INDEX", "📑 记忆总目录"))

        # 同目录其他文件
        parent = path.parent
        siblings = sorted(parent.glob("*.md"))
        for sib in siblings:
            if sib == path:
                continue
            sib_rel = sib.relative_to(VAULT).with_suffix("")
            sib_title = index.get(str(sib_rel), (None, sib.stem))[1]
            related.append((str(sib_rel), sib_title))

        # 已有相关链接段？先删
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        if "## 相关链接" in content:
            content = re.sub(r"\n## 相关链接.*$", "", content, flags=re.DOTALL)

        # 追加
        related_section = "\n\n## 相关链接\n\n"
        for link, label in related:
            related_section += f"- [[{link}|{label}]]\n"

        content += related_section
        path.write_text(content, encoding="utf-8")
        updated += 1

    return updated


# ============ 2) 为每个项目生成 TIMELINE.md ============
def generate_timelines(index):
    """遍历 projects/*/，生成 TIMELINE.md 按时间排序"""
    projects_dir = VAULT / "projects"
    if not projects_dir.exists():
        return 0

    created = 0
    for proj_dir in sorted(projects_dir.iterdir()):
        if not proj_dir.is_dir():
            continue

        proj_name = proj_dir.name
        files = []
        for md in proj_dir.glob("*.md"):
            # 跳过 TIMELINE 自身
            if md.stem == "TIMELINE":
                continue
            # 从文件名提取日期前缀
            date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", md.stem)
            date = date_match.group(1) if date_match else "未知日期"
            try:
                title = index[str(md.relative_to(VAULT).with_suffix(""))][1]
            except KeyError:
                title = md.stem
            files.append((date, title, md.stem))

        # 按日期排序
        files.sort()

        # 生成 TIMELINE.md
        timeline = f"# {proj_name} - 项目时间线\n\n"
        timeline += f"> **项目建立**：{files[0][0] if files else '今日'}\n"
        timeline += f"> **归档条数**：{len(files)}\n"
        timeline += f"> **最近更新**：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        timeline += "## 📅 按时间排序\n\n"

        for date, title, stem in files:
            timeline += f"### {date} - {title}\n\n"
            timeline += f"- [[{stem}]]\n\n"

        if not files:
            timeline += "_暂无归档_\n"

        timeline += "\n## 🔗 相关\n\n"
        timeline += "- [[INDEX|📑 记忆总目录]]\n"

        (proj_dir / "TIMELINE.md").write_text(timeline, encoding="utf-8")
        created += 1

    return created


# ============ 3) 更新 INDEX.md ============
def update_index(index):
    """重写 INDEX.md 含完整目录树"""
    # 收集所有 projects
    projects = []
    proj_dir = VAULT / "projects"
    if proj_dir.exists():
        for p in sorted(proj_dir.iterdir()):
            if p.is_dir():
                projects.append(p.name)

    content = f"""# Hermes 冷记忆 Vault 索引

> **vault 位置**：`~/HermesMemory/`
> **Obsidian 版本**：1.12.7
> **建立时间**：2026-06-08
> **最后更新**：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 📂 目录导航

| 目录 | 用途 | 入口 |
|------|------|------|
| [[daily/]] | 每日会话快照 | `daily/` |
| [[projects/]] | 项目资料（按话题分） | `projects/<项目名>/` |
| [[preferences/]] | 偏好（永久） | `preferences/` |
| [[incidents/]] | 踩坑+修复（避坑指南） | `incidents/` |

## 🔥 当前项目

"""

    if projects:
        for p in projects:
            content += f"- [[projects/{p}/TIMELINE|{p}]]\n"
    else:
        content += "_暂无项目_\n"

    # 统计
    total_files = len(index)
    content += f"\n## 📊 统计\n\n"
    content += f"- **总归档文件**：{total_files} 个\n"
    content += f"- **项目数**：{len(projects)} 个\n"
    content += f"- **偏好/踩坑**：见对应目录\n"

    # 快捷键
    content += """
## 🚀 快捷键

| 操作 | 快捷键 |
|------|--------|
| 全局搜索 | `Cmd + Shift + F` |
| 快速切换文件 | `Cmd + O` |
| 新建文件 | `Cmd + N` |
| 跟随链接 | `Cmd + 点击` |
| 反向链接面板 | `Cmd + 3` |
| 大纲视图 | `Cmd + 4` |
| 标签面板 | `Cmd + 5` |

## 🔌 已装插件

- **Smart Connections** - 语义搜索（用 AI 找相关笔记）

## 🔄 自动化

- **smart_archive.sh** - 智能归档（我自动调）
- **auto_archive_hook.sh** - 自动归档钩子
- **vault_postprocess.py** - 本脚本（每次新增文件后跑一次）

---
_由 user-auto-memory-archiving 维护_
"""

    (VAULT / "INDEX.md").write_text(content, encoding="utf-8")


# ============ 4) 生成/更新 README.md ============
def update_readme(index):
    """重写 README.md = vault 的'门面'，含完整说明"""
    proj_dir = VAULT / "projects"
    pref_dir = VAULT / "preferences"
    inc_dir = VAULT / "incidents"
    daily_dir = VAULT / "daily"

    # 统计各目录
    proj_count = len(list(proj_dir.glob("*/"))) if proj_dir.exists() else 0
    pref_count = len(list(pref_dir.glob("*.md"))) if pref_dir.exists() else 0
    inc_count = len(list(inc_dir.glob("*.md"))) if inc_dir.exists() else 0
    daily_count = len(list(daily_dir.glob("*.md"))) if daily_dir.exists() else 0
    total = len(index)

    # 最近归档
    recent = []
    for rel_str, (path, title) in index.items():
        mtime = path.stat().st_mtime
        recent.append((mtime, title, rel_str))
    recent.sort(reverse=True)
    recent_5 = recent[:5]

    content = f"""# 🏛️ Hermes 冷记忆 Vault

> 长期存储所有对话上下文，零丢失。Obsidian 可视化管理 + 语义搜索。

## 📊 当前状态

| 维度 | 数值 |
|------|------|
| 📁 总归档 | **{total}** 个文件 |
| 🔥 项目 | **{proj_count}** 个 |
| ⚙️ 偏好 | **{pref_count}** 条 |
| 🐛 踩坑 | **{inc_count}** 条 |
| 📅 每日快照 | **{daily_count}** 篇 |
| 🕐 最后更新 | **{datetime.now().strftime('%Y-%m-%d %H:%M')}** |

## 🆕 最近 5 条归档

"""
    if recent_5:
        for mtime, title, rel in recent_5:
            ts = datetime.fromtimestamp(mtime).strftime('%m-%d %H:%M')
            content += f"- `{ts}` [[{rel}|{title}]]\n"
    else:
        content += "_暂无_\n"

    content += """
## 🗂️ 目录结构

```
HermesMemory/
├── INDEX.md        ← 目录索引（点击跳转）
├── README.md       ← 本文件（状态总览）
├── daily/          ← 每日会话快照
├── preferences/    ← 偏好（永久）
├── incidents/      ← 踩坑+修复
├── projects/       ← 项目（自动按话题建子目录）
│   └── <项目名>/
│       ├── TIMELINE.md    ← 项目时间线（自动生成）
│       └── *.md           ← 归档条目
└── .obsidian/      ← Obsidian 配置
    └── plugins/smart-connections/   ← 语义搜索
```

## 🚀 怎么用

| 想干啥 | 怎么做 |
|--------|--------|
| 看全貌 | 打开 [[INDEX]] |
| 找某条记忆 | `Cmd + Shift + F` 搜关键词 |
| 语义搜索 | 看右侧 Smart Connections 面板 |
| 看项目历史 | 进 `projects/<项目名>/TIMELINE.md` |
| 反向链接 | 任意文件底部 `## 相关链接` |

## ⚙️ 自动化

本 vault **全自动维护**，由 `user-auto-memory-archiving` skill 驱动：

- 我（Hermes）每轮对话后自动检测是否要归档
- 归档后自动跑 `vault_postprocess.py`
- 后处理 4 件事：
  1. 注入反向链接
  2. 生成项目时间线
  3. 维护 INDEX.md
  4. **维护本 README.md**

## 🔌 已装插件

- **Smart Connections** v4.5.3 - 语义搜索（本地 ONNX 模型，零 API key）

## 📜 规则

- 用户硬规则：**所有上下文存档 + 自动分层**，不需用户提醒
- 诚实原则：找不到 = 说不知道，不编
- 频率：每 5 轮 / 每 30 分钟 / 热记忆 > 1500 字符告警

---
_vault 状态实时同步 · 由 vault_postprocess.py 维护_
"""

    (VAULT / "README.md").write_text(content, encoding="utf-8")


# ============ 5) 错误统计 ============
ERROR_LOG = VAULT / ".checkpoints" / "errors.json"

def log_error(category, message, detail=""):
    """记录错误到 errors.json（追加）"""
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    if ERROR_LOG.exists():
        try:
            errors = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
        except Exception:
            errors = []

    errors.append({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "category": category,
        "message": message,
        "detail": detail[:200] if detail else "",
    })

    # 保留最近 100 条
    errors = errors[-100:]
    ERROR_LOG.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_error_stats():
    """生成 ERRORS.md 错误统计报告"""
    if not ERROR_LOG.exists():
        # 没错误就建一个空报告
        (VAULT / "ERRORS.md").write_text(
            f"# 🐛 错误统计\n\n> 最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n✅ **无错误记录**\n"
        )
        return 0

    try:
        errors = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
    except Exception:
        errors = []

    if not errors:
        (VAULT / "ERRORS.md").write_text(
            f"# 🐛 错误统计\n\n> 最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n✅ **无错误记录**\n"
        )
        return 0

    # 按类别分组
    by_cat = defaultdict(list)
    for e in errors:
        by_cat[e.get("category", "unknown")].append(e)

    # 按日期分组（今天/本周/更早）
    today = datetime.now().date()
    today_errors = [e for e in errors if datetime.fromisoformat(e["ts"]).date() == today]
    week_ago = today.toordinal() - 7
    week_errors = [e for e in errors if datetime.fromisoformat(e["ts"]).date().toordinal() >= week_ago]

    content = f"""# 🐛 错误统计报告

> **最后更新**：{datetime.now().strftime('%Y-%m-%d %H:%M')}
> **总错误数**：{len(errors)} 条
> **今日**：{len(today_errors)} 条
> **本周**：{len(week_errors)} 条

## 📊 按类别分布

| 类别 | 次数 | 占比 |
|------|------|------|
"""

    total = len(errors)
    for cat in sorted(by_cat.keys(), key=lambda k: -len(by_cat[k])):
        count = len(by_cat[cat])
        pct = count * 100 // total if total else 0
        content += f"| {cat} | {count} | {pct}% |\n"

    content += "\n## 📅 错误时间线（最近 10 条）\n\n"
    for e in errors[-10:][::-1]:
        content += f"### {e['ts']} - {e.get('category', '?')}\n\n"
        content += f"**{e.get('message', '')}**\n\n"
        if e.get("detail"):
            content += f"```\n{e['detail']}\n```\n\n"

    # 高频错误
    content += "## 🔥 高频错误 Top 5\n\n"
    msg_count = defaultdict(int)
    for e in errors:
        msg_count[e.get("message", "")] += 1
    top = sorted(msg_count.items(), key=lambda x: -x[1])[:5]
    if top[0][1] > 0:
        for msg, cnt in top:
            content += f"- ({cnt}x) {msg}\n"
    else:
        content += "_无_\n"

    content += f"""
## 🛠 调试建议

| 类别 | 调谁查 |
|------|--------|
| smart_archive | `~/.hermes/scripts/smart_archive.sh` |
| vault_postprocess | `python3 ~/.hermes/scripts/vault_postprocess.py` |
| hook | `~/.hermes/scripts/auto_archive_hook.sh status` |
| 热记忆 | `~/.hermes/scripts/update_hot_used.sh` |

---
_由 vault_postprocess.py 自动维护 · 数据源 `.checkpoints/errors.json`_
"""

    (VAULT / "ERRORS.md").write_text(content, encoding="utf-8")
    return len(errors)


# ============ 主流程 ============
def main():
    print("🔍 扫 vault...")
    index = scan_vault()
    print(f"   找到 {len(index)} 个文件")

    print("\n🔗 注入反向链接...")
    n = inject_related_links(index)
    print(f"   更新 {n} 个文件")

    print("\n📅 生成项目时间线...")
    n = generate_timelines(index)
    print(f"   创建 {n} 个 TIMELINE.md")

    print("\n📑 更新 INDEX.md...")
    update_index(index)
    print("   完成")

    print("\n📖 更新 README.md...")
    update_readme(index)
    print("   完成")

    print("\n🐛 更新错误统计...")
    n = generate_error_stats()
    print(f"   {n} 条错误记录")

    print("\n✅ 后处理完成")


if __name__ == "__main__":
    main()
