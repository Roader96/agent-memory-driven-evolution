#!/usr/bin/env python3
"""preference_signals.py — 正向成长信号采集（emulo + PRELUDE 论文本地化）

用户 2026-09-10 定调：自进化的主航道是"学会用户的习惯、准确完成任务、变聪明"，
砍 skill 只是副航道。本模块从 state.db 原始对话里挖用户从没写下来的隐性偏好。

三类信号（PRELUDE：用户的"编辑/纠正"成本超阈值才触发归纳）：
  correction  纠正信号：用户否定/修改我的产出 = 我做错的（最强学习信号）
  approval    认可信号：用户确认/表扬 = 做对的（强化）
  habit       习惯信号：用户反复出现的祈使/约束 = 稳定工作方式

输出喂给 preference_miner（LLM 归纳）+ 直接可统计。
纯标准库 3.9 兼容，只读 state.db。
"""
from __future__ import annotations
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
import agent_adapter as A
STATE = A.state_db_path()
SKIP_SOURCES = ("cron", "daily-polish", "skill-evolution-librarian")


def _has_required_schema(conn) -> bool:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {"messages", "sessions"}.issubset(tables)

# 纠正：用户在否定/推翻我的东西（PRELUDE 的 user edit）
CORRECTION = [
    "不对", "错了", "不是", "别这样", "不要这样", "重新", "重来", "太长", "太短",
    "怎么又", "又错", "还是不行", "没对", "搞反", "反了", "我不是这个意思",
    "形式主义", "摸鱼", "忽悠", "假的", "你确定", "真的吗", "别急着", "不要急",
    "太啰嗦", "说重点", "简单点", "别扩", "别加戏", "过度", "想多了", "删了",
    "停", "先别", "不是让你", "谁让你", "我只是问问", "我只是说",
]
# 弱纠正（单独出现信号弱，需结合语境，权重低）
SOFT_CORRECTION = ["但", "不过", "可是", "然而", "改成", "换成", "应该是"]
# 认可
APPROVAL = [
    "对", "就这样", "可以", "好的", "不错", "完美", "正是", "就是这", "准确",
    "谢谢", "辛苦", "👍", "❤️", "😂", "漂亮", "靠谱", "稳", "牛", "太好了",
]
# 习惯祈使：用户反复用的命令式短语（稳定偏好的候选，需跨会话重复才算）
HABIT_PATTERNS = [
    r"必须", r"一定要", r"记住", r"以后都", r"每次都", r"老规矩", r"按.{0,6}来",
    r"不要[飞系]", r"静默", r"零 ?token", r"别推", r"不要打扰", r"发飞书",
    r"红涨绿跌", r"最小改动", r"整套",
]


def _is_real_user_text(content: str) -> bool:
    """排除系统注入、图片占位、超长粘贴（贴代码不是偏好信号）。"""
    t = (content or "").strip()
    if not t or len(t) > 300:
        return False
    if t.startswith(("[System:", "[OUT-OF-BAND", "@image")):
        return False
    if t.count("\n") > 6:
        return False
    return True


def _prior_assistant(conn, sid, ts, limit=400):
    """纠正发生前，我最后一条实质回复（PRELUDE 的 context：我做错的那个产出）。"""
    row = conn.execute("""
        SELECT content FROM messages
        WHERE session_id=? AND role='assistant' AND timestamp < ?
          AND content IS NOT NULL AND length(content) > 20
          AND content NOT LIKE '[System:%'
        ORDER BY timestamp DESC LIMIT 1
    """, (sid, ts)).fetchone()
    return (row[0][:limit] if row else "")


def collect_day(day: str) -> dict:
    """按天收集（每日 watchdog 用）：返回当天信号 + 近7天纠正趋势。"""
    conn = sqlite3.connect(str(STATE), timeout=10)
    if not _has_required_schema(conn):
        conn.close()
        return {"day": day, "corrections": [], "approvals": [], "habits": [],
                "counts": {"corrections": 0, "approvals": 0, "habits": 0}, "trend_7d": []}
    import datetime as _dt
    start = _dt.datetime.strptime(day, "%Y-%m-%d").timestamp()
    end = start + 86400
    rows = conn.execute("""
        SELECT m.session_id, m.content, m.timestamp, s.title, s.source
        FROM messages m JOIN sessions s ON m.session_id = s.id
        WHERE m.role='user' AND m.timestamp >= ? AND m.timestamp < ?
          AND COALESCE(s.archived,0)=0
          AND (s.parent_session_id IS NULL OR s.parent_session_id='')
        ORDER BY m.timestamp ASC
    """, (start, end)).fetchall()

    corrections, approvals, habits = [], [], []
    for sid, content, ts, title, source in rows:
        if source in SKIP_SOURCES:
            continue
        if not _is_real_user_text(content):
            continue
        t = content.strip()
        hit_corr = next((k for k in CORRECTION if k in t), None)
        if hit_corr:
            corrections.append({
                "session_id": sid, "title": title or "",
                "text": t[:150], "signal": hit_corr, "ts": ts,
                "prior_assistant": _prior_assistant(conn, sid, ts),
            })
            continue
        hit_appr = next((k for k in APPROVAL if t in (k,) or
                         (len(t) <= 12 and k in t)), None)
        if hit_appr and len(t) <= 12:
            approvals.append({
                "session_id": sid, "text": t[:60], "signal": hit_appr, "ts": ts,
            })
            continue
        for pat in HABIT_PATTERNS:
            m = re.search(pat, t)
            if m:
                habits.append({
                    "session_id": sid, "title": title or "",
                    "text": t[:150], "signal": m.group(0), "ts": ts,
                })
                break
    conn.close()

    # 近7天纠正趋势（学没学会回测）
    trend = []
    base = _dt.datetime.strptime(day, "%Y-%m-%d")
    for i in range(6, -1, -1):
        d0 = (base - _dt.timedelta(days=i)).strftime("%Y-%m-%d")
        c = collect_window(d0, d0)
        trend.append({"day": d0, "corrections": c["correction_count"]})
    return {
        "day": day,
        "corrections": corrections, "approvals": approvals, "habits": habits,
        "counts": {"corrections": len(corrections),
                   "approvals": len(approvals), "habits": len(habits)},
        "trend_7d": trend,
    }


def collect_window(start_day: str, end_day: str) -> dict:
    """两个日期之间（闭区间）的信号，趋势回测用。start 默认取当日往前。"""
    conn = sqlite3.connect(str(STATE), timeout=10)
    if not _has_required_schema(conn):
        conn.close()
        return {"start": start_day, "end": end_day, "corrections": [], "correction_count": 0}
    import datetime as _dt
    s0 = _dt.datetime.strptime(start_day, "%Y-%m-%d").timestamp()
    e0 = _dt.datetime.strptime(end_day + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
    rows = conn.execute("""
        SELECT m.session_id, m.content, m.timestamp, s.title, s.source
        FROM messages m JOIN sessions s ON m.session_id = s.id
        WHERE m.role='user' AND m.timestamp >= ? AND m.timestamp <= ?
          AND COALESCE(s.archived,0)=0
        ORDER BY m.timestamp ASC
    """, (s0, e0)).fetchall()
    corr = []
    for sid, content, ts, title, source in rows:
        if source in SKIP_SOURCES:
            continue
        if not _is_real_user_text(content):
            continue
        t = content.strip()
        h = next((k for k in CORRECTION if k in t), None)
        if h:
            corr.append({"text": t[:150], "signal": h, "ts": ts,
                         "prior_assistant": _prior_assistant(conn, sid, ts)})
    conn.close()
    return {"start": start_day, "end": end_day, "corrections": corr,
            "correction_count": len(corr)}


def collect(days: int = 30) -> dict:
    conn = sqlite3.connect(str(STATE), timeout=10)
    if not _has_required_schema(conn):
        conn.close()
        return {"corrections": [], "approvals": [], "habits": [],
                "counts": {"corrections": 0, "approvals": 0, "habits": 0}}
    since = time.time() - days * 86400
    rows = conn.execute("""
        SELECT m.session_id, m.content, m.timestamp, s.title, s.source
        FROM messages m JOIN sessions s ON m.session_id = s.id
        WHERE m.role='user' AND m.timestamp >= ?
          AND COALESCE(s.archived,0)=0
          AND (s.parent_session_id IS NULL OR s.parent_session_id='')
        ORDER BY m.timestamp ASC
    """, (since,)).fetchall()

    corrections, approvals, habits = [], [], []
    for sid, content, ts, title, source in rows:
        if source in SKIP_SOURCES:
            continue
        if not _is_real_user_text(content):
            continue
        t = content.strip()

        hit_corr = next((k for k in CORRECTION if k in t), None)
        if hit_corr:
            corrections.append({
                "session_id": sid, "title": title or "",
                "text": t[:150], "signal": hit_corr, "ts": ts,
                "prior_assistant": _prior_assistant(conn, sid, ts),
            })
            continue  # 纠正优先，不算认可/习惯

        hit_appr = next((k for k in APPROVAL if t in (k,) or
                         (len(t) <= 12 and k in t)), None)
        if hit_appr and len(t) <= 12:
            approvals.append({
                "session_id": sid, "text": t[:60], "signal": hit_appr, "ts": ts,
            })
            continue

        for pat in HABIT_PATTERNS:
            m = re.search(pat, t)
            if m:
                habits.append({
                    "session_id": sid, "title": title or "",
                    "text": t[:150], "signal": m.group(0), "ts": ts,
                })
                break

    conn.close()
    return {
        "window_days": days,
        "corrections": corrections,
        "approvals": approvals,
        "habits": habits,
        "counts": {
            "corrections": len(corrections),
            "approvals": len(approvals),
            "habits": len(habits),
        },
    }


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    d = collect(days)
    print(json.dumps(d["counts"], ensure_ascii=False))
    print("\n=== 纠正信号（前15）===")
    for x in d["corrections"][:15]:
        print(f"  [{x['signal']}] {x['text'][:70]}")
    print("\n=== 习惯信号（前15）===")
    for x in d["habits"][:15]:
        print(f"  [{x['signal']}] {x['text'][:70]}")
