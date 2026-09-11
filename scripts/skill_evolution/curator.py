#!/usr/bin/env python3
"""curator.py — 技能馆长（Ratchet 承重墙：结果驱动退役 + 证据门槛）

只【提提案】，绝不自动改技能。证据门槛刻意保守，因为：
  skill_view 零调用 ≠ 技能没用（描述每轮注入，可能不 view 就照做）。
所以退役候选必须同时满足：
  已安装 + 全历史零加载 + 年龄≥90天 + 非自建(roader/Roader) + 非 essential
  + 体积小或名字明显冷门，且近2期快照持续零加载（防新技能误杀）。
另：坏引用（被调用但已不存在的技能名）→ 修订提案（改调用方/建别名）。
"""
from __future__ import annotations
from pathlib import Path
import state

ESSENTIAL = {"hermes-agent"}
SELF_PREFIX = ("roader", "Roader", "auto-skill-save")
MIN_AGE_DAYS = 90


def is_self_built(name: str) -> bool:
    return name.startswith(SELF_PREFIX)


def curate(facts: list, prev_snapshot_names: set | None = None) -> list:
    proposals = []

    by_name = {x["name"]: x for x in facts}

    # 1) 退役候选：零需求 + 陈旧 + 非自建
    # Ratchet 活跃库上限思路：每周限量提（最大 5 个，按体积降序先清大的），
    # 稳步收敛而非一次性爆队列——skill_view 覆盖不全（描述注入）的不确定性
    # 决定了批量退役必然误伤，只能小步快跑 + 哥审批。
    MAX_RETIRE_PER_WEEK = 5
    retire_candidates = []
    for x in facts:
        name = x["name"]
        if not x.get("installed") or x.get("disabled"):
            continue
        if name in ESSENTIAL or is_self_built(name):
            continue
        if x["load_sessions"] != 0:
            continue
        if (x.get("age_days") or 0) < MIN_AGE_DAYS:
            continue
        # 必须有足够历史基线，且连续多期全零加载才提（防单期误判+回填穿透）
        if prev_snapshot_names is None:
            continue
        prev = prev_snapshot_names.get(name)
        if prev is not None and prev.get("load", 0) > 0:
            continue
        # 冷库（永久记忆）近 90 天提到过 = 知识被激活过，不自动提退役
        if (x.get("vault_mentions_90d") or 0) > 0:
            continue
        retire_candidates.append(x)
    for x in sorted(retire_candidates, key=lambda x: -(x.get("size_bytes") or 0))[:MAX_RETIRE_PER_WEEK]:
        name = x["name"]
        proposals.append({
            "kind": "retire",
            "target": name,
            "action": "disable",  # 软禁用进 skills.disabled，可逆，不删
            "reason": f"全历史零加载 · {x.get('age_days')}天未改 · {x.get('size_bytes',0)}B（本周限量{MAX_RETIRE_PER_WEEK}个，候选共{len(retire_candidates)}个）",
            "evidence": {
                "load_sessions": 0,
                "age_days": x.get("age_days"),
                "size_bytes": x.get("size_bytes"),
            },
            "confidence": "low（描述注入可能被无 view 照用，需哥确认确实用不到）",
        })

    # 2) 坏引用：被 skill_view 调用但不存在 → 修订/别名提案
    for x in facts:
        if (not x.get("installed")) and x["load_sessions"] > 0:
            proposals.append({
                "kind": "fix_reference",
                "target": x["name"],
                "action": "rename_or_alias",
                "reason": f"被加载 {x['load_sessions']} 次但技能不存在（改名/废弃？）",
                "evidence": {"load_sessions": x["load_sessions"],
                             "self_errors": x["self_errors"]},
                "confidence": "high",
            })

    # 3) 自身报错的现存技能 → 修订提案
    for x in facts:
        if x.get("installed") and x["self_errors"] > 0:
            proposals.append({
                "kind": "repair",
                "target": x["name"],
                "action": "inspect_skill",
                "reason": f"skill_view 报错 {x['self_errors']} 次（SKILL.md 可能损坏/字段缺失）",
                "evidence": {"self_errors": x["self_errors"]},
                "confidence": "medium",
            })

    return proposals


def prev_zero_baseline(state_doc, need_weeks=3) -> dict | None:
    """返回 {name: {"load": 近N期总加载}}，历史不足 N 期返回 None（只观察不退役）。

    门槛：连续 need_weeks 期（默认 3 期）≥3 天前的快照全部存在才算有基线；
    且技能必须在所有 N 期里全零加载才会出现在返回值中（load=0）。
    回填快照只记录"有加载的技能"，名字缺席 = 该期零加载。"""
    snaps = state_doc.get("weekly_snapshots") or []
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    old = [s for s in snaps if s.get("week", "9999") < cutoff]
    if len(old) < need_weeks:
        return None
    recent = old[-need_weeks:]
    # 近 N 期出现过加载的名字集合
    used_names = set()
    for s in recent:
        for x in s.get("skills", []):
            if x.get("load", 0) > 0:
                used_names.add(x["name"])
    # 返回一个"查询表"：名字在其中 → 近N期全零（load=0）；不在 → 有过加载
    # 为兼容 curate 现有调用（prev.get(name) 且 load>0 则跳过），
    # 这里返回 {任何名字: {"load": 0}} 的代理视图不够用，改为返回特殊结构：
    # curate 端语义：prev is None（名字不在 used_names）→ 零加载 → 不跳过
    return ZeroBaselineProxy(used_names)


class ZeroBaselineProxy:
    """兼容 curate 的 prev.get(name) 接口：近N期有加载的返回 {'load':1}，否则 None。"""
    def __init__(self, used_names):
        self._used = used_names

    def get(self, name, default=None):
        if name in self._used:
            return {"load": 1}
        return default


if __name__ == "__main__":
    import json
    import metrics
    facts = metrics.skill_facts()
    st = state.load()
    base = prev_zero_baseline(st)
    props = curate(facts, base)
    print(json.dumps(props, ensure_ascii=False, indent=1))
    print(f"\n# 首期快照数={len(st.get('weekly_snapshots', []))}，"
          f"{'有历史基线' if base else '无历史基线→首期只观察不提退役'}")
