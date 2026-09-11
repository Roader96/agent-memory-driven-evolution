#!/usr/bin/env python3
"""backfill_snapshots.py — 历史快照回填（一次性）

快照本来只能靠每周攒，退役机制要等好几周才有基线。
但 state.db 里 skill_view 调用全带时间戳——按周切片就能重建历史基线，
让"连续 N 周零加载"的退役判定立即可用。

只回填"周加载计数"（load 字段），其他字段（self_err/reload/edits）
无法从历史精确切片，留 0 并标注 backfilled=True，retirement 判定只看 load。
"""
from __future__ import annotations
import json
import re
import sqlite3
import time
from pathlib import Path
from datetime import datetime

import state
import metrics as M


def weekly_loads(conn, weeks=6):
    """返回 {week_start_date: {skill_name: load_count}}，按自然周（周一）切片。"""
    rows = conn.execute("""
        SELECT tool_calls, timestamp FROM messages
        WHERE role='assistant' AND tool_calls IS NOT NULL AND tool_calls != ''
    """).fetchall()
    now = time.time()
    out = {}
    for tc_raw, ts in rows:
        try:
            calls = json.loads(tc_raw)
        except Exception:
            continue
        if not isinstance(calls, list):
            continue
        for c in calls:
            fn = (c or {}).get("function") or {}
            if fn.get("name") != "skill_view":
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                continue
            name = args.get("name")
            if not name:
                continue
            name = str(name).strip().split(":")[-1]
            # 自然周起点（周一 00:00）
            dt = datetime.fromtimestamp(ts)
            monday = dt.date().fromordinal(dt.date().toordinal() - dt.weekday())
            wk = monday.strftime("%Y-%m-%d")
            if (now - ts) / 86400 > weeks * 7:
                continue
            out.setdefault(wk, {}).setdefault(name, 0)
            out[wk][name] += 1
    return out


def main():
    conn = sqlite3.connect(str(M.STATE))
    conn.row_factory = sqlite3.Row
    loads = weekly_loads(conn, weeks=6)
    facts = M.skill_facts()
    installed = {x["name"] for x in facts if x["installed"]}
    # 大小写不敏感映射到 canonical（frontmatter name）
    canon = {x["name"].lower(): x["name"] for x in facts if x["installed"]}

    doc = state.load()
    existing_weeks = {s.get("week") for s in doc.get("weekly_snapshots", [])}
    added = 0
    for wk, skill_loads in sorted(loads.items()):
        if wk in existing_weeks:
            continue  # 已有真快照的周不覆盖
        slim = []
        for name, cnt in skill_loads.items():
            cname = canon.get(name.lower(), name)
            slim.append({
                "name": cname, "load": cnt,
                "self_err": 0, "reload": 0, "edits": 0,
                "disabled": False,
            })
        doc["weekly_snapshots"].append({
            "week": wk,
            "n_installed": len(installed),
            "n_used": len(skill_loads),
            "global": {"note": "backfilled from state.db history"},
            "skills": slim,
            "backfilled": True,
        })
        added += 1
        print(f"回填 {wk}: {len(skill_loads)} 个技能有加载")
    doc["weekly_snapshots"].sort(key=lambda s: s.get("week", ""))
    doc["weekly_snapshots"] = doc["weekly_snapshots"][-26:]
    state.save(doc)
    print(f"\n✅ 回填 {added} 期，当前总 {len(doc['weekly_snapshots'])} 期")


if __name__ == "__main__":
    main()
