#!/usr/bin/env python3
"""state.py — 自进化状态库（ADD-only，借鉴 mem0：只追加不覆盖）

存 ~/.hermes/skill_evolution/state.json：
  weekly_snapshots  每周技能度量快照（看趋势：某技能是否在被淘汰）
  proposals         技能变更提案队列（退役/新增/修订），状态 pending/approved/rejected/done
  failure_memory    失败簇记忆（永不删，借鉴 SkillSmith：防重复诊断/复活已废技能）
  prevented         教训 id -> 实际拦住次数（闭环度量）
所有变更走提案 + 哥审批，脚本绝不自动改技能。
"""
import json
import os
from datetime import datetime
from pathlib import Path

HOME = Path.home()
DIR = HOME / ".hermes" / "skill_evolution"
STATE_FILE = DIR / "state.json"


def empty_state():
    return {
        "version": 1,
        "weekly_snapshots": [],
        "follow_ups": [],
        "proposals": [],
        "preferences": [],
        "failure_memory": [],
        "prevented": {},
        "approved_changes": [],
    }


def load():
    if STATE_FILE.exists():
        try:
            d = json.loads(STATE_FILE.read_text())
            for k, v in empty_state().items():
                d.setdefault(k, v)
            return d
        except Exception:
            pass
    return empty_state()


def save(d):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STATE_FILE)  # 原子写


def add_snapshot(metrics_facts: list, global_stats: dict):
    d = load()
    # 只存轻量摘要（名字+关键计数），不存全量，控体积
    slim = [{
        "name": x["name"],
        "load": x["load_sessions"],
        "self_err": x["self_errors"],
        "reload": x["reload_sessions"],
        "edits": x["edits"],
        "disabled": x["disabled"],
    } for x in metrics_facts]
    week = datetime.now().strftime("%Y-%m-%d")
    # 同一天重跑覆盖当天快照（调试期多次跑不该产生重复期）
    d["weekly_snapshots"] = [s for s in d["weekly_snapshots"] if s.get("week") != week]
    d["weekly_snapshots"].append({
        "week": week,
        "n_installed": sum(1 for x in metrics_facts if x["installed"]),
        "n_used": sum(1 for x in metrics_facts if x["load_sessions"] > 0),
        "global": global_stats,
        "skills": slim,
    })
    # 只留 26 期（半年）
    d["weekly_snapshots"] = d["weekly_snapshots"][-26:]
    save(d)
    return d


def add_proposal(p: dict):
    d = load()
    # 同技能同类型已有 pending/done 提案则不重复提
    for ex in d["proposals"]:
        if (ex.get("target") == p["target"] and ex.get("kind") == p["kind"]
                and ex.get("status") in ("pending", "done")):
            return d, False
    p.setdefault("id", f"P{len(d['proposals'])+1:03d}")
    p.setdefault("status", "pending")
    p.setdefault("created", datetime.now().strftime("%Y-%m-%d"))
    d["proposals"].append(p)
    save(d)
    return d, True


def list_pending():
    return [p for p in load()["proposals"] if p["status"] == "pending"]
