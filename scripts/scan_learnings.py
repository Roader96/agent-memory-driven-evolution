#!/usr/bin/env python3
import os
"""
scan_learnings.py - 每日扫描 Hermes 自带 logs/errors.log 找高频错误
+ 扫 HermesMemory/incidents 和 preferences 找重复主题

数据源：
- 错误：~/.hermes/logs/errors.log（Hermes 自带，WARNING 级）
- 归档：~/Documents/HermesMemory/{incidents,preferences}/
- 我自己记的：~/.hermes/.checkpoints/errors.json（auto_log_error.py）

输出：LEARNINGS-REVIEW.md（每日评审清单）
"""
import re
import json
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

HERMES_LOGS = Path.home() / ".hermes" / "logs" / "errors.log"
VAULT = Path(os.environ.get("HERMES_VAULT", Path.home() / "Documents" / "HermesMemory"))
MY_ERROR_LOG = VAULT / ".checkpoints" / "errors.json"
REPORT = VAULT / "LEARNINGS-REVIEW.md"

# 提示提炼的阈值
HIGH_FREQ_THRESHOLD = 3


# ============ 1. 扫 Hermes 自带 errors.log ============
def parse_hermes_log():
    """从 ~/.hermes/logs/errors.log 解析工具错误
    格式: '2026-06-08 17:46:36,599 WARNING ... agent.tool_executor: Tool X returned error (Ys): {...}'
    """
    if not HERMES_LOGS.exists():
        return []

    errors = []
    pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ WARNING.*?"
        r"agent\.tool_executor: Tool (\w+) returned error.*?:\s*(.*)$"
    )

    try:
        for line in HERMES_LOGS.read_text(encoding="utf-8", errors="replace").splitlines():
            m = pattern.match(line)
            if not m:
                continue
            ts, tool, payload = m.group(1), m.group(2), m.group(3)
            # 提取错误关键信息
            # 尝试从 payload 提取 error 字段
            err_match = re.search(r'"error":\s*"([^"]+)"', payload)
            err_msg = err_match.group(1) if err_match else payload[:200]
            errors.append({
                "ts": ts,
                "tool": tool,
                "message": f"{tool}: {err_msg[:150]}",
            })
    except Exception:
        pass

    return errors


# ============ 2. 扫冷库 errors.json（多源融合，多读一份）============
def parse_my_errors():
    """从 HermesMemory/.checkpoints/errors.json 读（auto_log_error.py 写的）
    不动 Hermes 自带 logs/errors.log，只多读一份来自冷库的"""
    if not MY_ERROR_LOG.exists():
        return []
    try:
        data = json.loads(MY_ERROR_LOG.read_text(encoding="utf-8"))
        return [
            {
                "ts": e.get("ts", ""),
                "tool": e.get("category", "?"),
                "message": e.get("message", ""),
            }
            for e in data
        ]
    except Exception:
        return []


# ============ 3. 扫 HermesMemory/incidents 重复主题 ============
def scan_incidents_themes():
    inc_dir = VAULT / "incidents"
    if not inc_dir.exists():
        return []

    items = []
    for f in inc_dir.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            first_line = content.split("\n")[0]
            title = re.sub(r"^#\s*", "", first_line).strip()
            keywords = re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,}", title)
            items.append((f.name, title, keywords))
        except Exception:
            continue

    kw_files = defaultdict(list)
    for fname, title, kws in items:
        for kw in kws:
            kw_files[kw].append((fname, title))

    return [(kw, lst) for kw, lst in kw_files.items() if len(lst) >= 2]


def main():
    print("🔍 扫 Hermes 自带 errors.log...")
    hermes_errors = parse_hermes_log()
    print(f"   解析 {len(hermes_errors)} 条")

    print("\n🔍 扫我自己记的 errors.json...")
    my_errors = parse_my_errors()
    print(f"   {len(my_errors)} 条")

    print("\n🔍 扫 incidents 主题...")
    themes = scan_incidents_themes()
    print(f"   {len(themes)} 个重复主题")

    # 合并所有错误，按 message 分组
    all_errors = hermes_errors + my_errors
    msg_counter = Counter(e["message"] for e in all_errors)
    tool_counter = Counter(e["tool"] for e in all_errors)

    # 按日期分组
    today = datetime.now().date()
    today_errors = [
        e for e in all_errors
        if e["ts"] and e["ts"][:10] == today.isoformat()
    ]

    # 生成报告
    content = f"""# 🧠 每日 learnings 评审

> **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}
> **数据源**：
> - Hermes 自带日志：`~/.hermes/logs/errors.log`（{len(hermes_errors)} 条历史）
> - 我自己记的：`~/Documents/HermesMemory/.checkpoints/errors.json`（{len(my_errors)} 条）
> - 重复主题：`HermesMemory/incidents/`（{len(themes)} 个）

## 🔥 高频错误（出现 ≥{HIGH_FREQ_THRESHOLD} 次 → 建议提炼 skill）

"""

    high_freq = [(m, n) for m, n in msg_counter.most_common() if n >= HIGH_FREQ_THRESHOLD]
    if high_freq:
        for msg, cnt in high_freq[:10]:
            content += f"- **{cnt}×** {msg[:200]}\n"
    else:
        content += "_无_\n"

    content += "\n## 📊 错误 Top 15\n\n"
    content += "| 次数 | 错误 |\n|------|------|\n"
    for msg, cnt in msg_counter.most_common(15):
        content += f"| {cnt} | {msg[:120]} |\n"

    content += "\n## 🛠 按工具分布\n\n"
    content += "| 工具 | 错误数 |\n|------|--------|\n"
    for tool, cnt in tool_counter.most_common(10):
        content += f"| {tool} | {cnt} |\n"

    content += "\n## 📅 今日新错误\n\n"
    if today_errors:
        for e in today_errors[:10]:
            content += f"- `{e['ts']}` [{e['tool']}] {e['message'][:150]}\n"
    else:
        content += "_无_\n"

    content += "\n## 🔁 incidents/ 重复主题（同一关键词出现 2+ 次）\n\n"
    if themes:
        for kw, lst in themes:
            content += f"### {kw}\n\n"
            for fname, title in lst[:5]:
                content += f"- [[incidents/{fname[:-3]}|{title}]]\n"
            content += "\n"
    else:
        content += "_无_\n"

    content += f"""## 💡 建议行动

| 情况 | 行动 |
|------|------|
| 高频错误 ≥{HIGH_FREQ_THRESHOLD} 次 | 提炼为 skill（防重复） |
| 重复主题 ≥2 次 | 加到 SKILL.md 故障排查 |
| 今日错误 ≥5 | 立即 review session |

## 🛠 手动提炼

```bash
# 提炼为新 skill
~/.hermes/scripts/smart_archive.sh "学习-主题名" "内容" "incidents"

# 看完整 Hermes 错误日志
tail -50 ~/.hermes/logs/errors.log

# 看我自己的错误
cat ~/Documents/HermesMemory/.checkpoints/errors.json
```

---
_由 scan_learnings.py 自动生成 · 数据源优先用 Hermes 自带 logs/errors.log_
"""

    REPORT.write_text(content, encoding="utf-8")
    print(f"\n✅ 报告已写: {REPORT}")
    print(f"   高频提炼候选: {len(high_freq)} 个")
    print(f"   重复主题: {len(themes)} 个")
    print(f"   今日新错误: {len(today_errors)} 个")


if __name__ == "__main__":
    main()
