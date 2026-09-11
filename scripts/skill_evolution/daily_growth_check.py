#!/usr/bin/env python3
"""daily_growth_check.py — 每日成长扫描（用户 2026-09-10 指示"平时也要找能进化/优化的点"）

不烧 LLM，纯规则。每天 watchdog 后跑：
  1. 统计当天纠正/认可/习惯（复用 preference_signals.collect_day）
  2. 同类纠正复发检测：近 3 天同一 signal 出现 ≥2 次 → 打高亮（下周喂给 preference_miner）
  3. 成长趋势写进 state.json preference_trend（周度 preference_miner 用）
  4. 输出一行摘要：当天无纠正 / 有 N 次纠正（M 类复发）→ 供 daily/log 记

用法：
  /usr/bin/python3 daily_growth_check.py >> daily_watchdog.log 2>&1
退出码：0 正常；2 当天无数据但 db 正常（不是失败）
"""
from __future__ import annotations
import json, sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes/scripts/skill_evolution"))
import preference_signals as ps
import state as st

def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    d = ps.collect_day(today)
    counts = d["counts"]

    # 同类复发：近3天同一 signal 出现 ≥2 次
    rec = Counter()
    base = datetime.strptime(today, "%Y-%m-%d")
    for i in range(1, 3):
        day0 = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        d0 = ps.collect_day(day0)
        rec.update(x["signal"] for x in d0["corrections"])
    rec.update(x["signal"] for x in d["corrections"])
    recur = {sig: n for sig, n in rec.items() if n >= 2}

    # 趋势写进 state.json
    s = st.load()
    s.setdefault("preference_trend", []).append({
        "day": today,
        "corrections": counts["corrections"],
        "approvals": counts["approvals"],
        "habits": counts["habits"],
    })
    s["preference_trend"] = s["preference_trend"][-26:]
    st.save(s)

    if counts["corrections"] == 0:
        print(f"[growth] {today} 无纠正，继续巩固")
    else:
        line = (f"[growth] {today} 纠正 {counts['corrections']} 次，"
                f"认可 {counts['approvals']}，习惯 {counts['habits']}")
        if recur:
            line += f" ⚠️ 复发: {recur}"
        print(line)
    return 0

if __name__ == "__main__":
    sys.exit(main())