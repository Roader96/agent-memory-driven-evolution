#!/usr/bin/env python3
"""followup.py — 提案执行效果追踪（Ratchet 闭环最后一环）

用户的问题：P059 建了之后 cron 失败有没有真减少？——不能只说"执行了"，要回测。

机制：
  1. 提案标 done 时自动创建 follow_up（关联可测指标 + baseline + 7 天后检查）
  2. run_weekly 每周检查到期项，回测写 result: improved/no_change/worse/inconclusive
  3. 结果喂给 librarian evidence——模型能看到"上周提案有效/无效"，无效的会复盘

指标类型（全都真实可测，不许编）：
  cluster:<key>   某错误簇的近 7 天复发次数（baseline=创建时 count），期望下降
  ref_loads:<name> 某技能名的加载尝试总次数（baseline=创建时累计），期望不再增长
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta

import state


# kind/target → 关联指标映射（启发式：从提案证据里能推什么指标就挂什么）
CLUSTER_MAP = {
    "cron-exit1-triage": "script exited code",
    "cron-shutdown-interrupt-recovery": "interrupted shutdown",
    "zh-copy-preflight": "typo",  # 长期指标
    "systematic-debugging": "terminal",
    "hermes-agent": "env",  # .env 报错簇
    "hermes-custom-providers": "env",
    "hermes-plugin-automation": "script exited code",
    "macos-power-management": "interrupted shutdown",
}


def create_follow_up(proposal: dict, metrics_facts: list, clusters: list) -> dict | None:
    """为 done 提案建回测条目。找不到可测指标就挂 target 级观察项。"""
    target = proposal.get("target", "")
    kind = proposal.get("kind", "")
    week_later = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    # 坏引用类：跟踪该名字的加载次数应停止增长
    if kind in ("fix_reference", "retire") and "/" not in target:
        base = next((x["load_sessions"] for x in metrics_facts if x["name"] == target), 0)
        return {
            "proposal_id": proposal.get("id"), "target": target,
            "metric": f"ref_loads:{target}", "baseline": base,
            "check_after": week_later, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "result": None,
        }

    # cron/错误簇类：跟踪关联簇复发（前缀匹配，target 可能带中文后缀）
    key = next((v for k, v in CLUSTER_MAP.items() if target.startswith(k)), None)
    if key:
        base = 0
        for c in clusters:
            title = (c.get("title") or "").lower()
            if key in title or key in (c.get("cluster_key") or "").lower():
                base = max(base, c.get("count") or 0)
        return {
            "proposal_id": proposal.get("id"), "target": target,
            "metric": f"cluster:{key}", "baseline": base,
            "check_after": week_later, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "result": None,
        }

    # 兜底：只记"待 librarian 复核"，无自动指标
    return {
        "proposal_id": proposal.get("id"), "target": target,
        "metric": "manual_review", "baseline": None,
        "check_after": week_later, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "result": None,
    }


def check_due(metrics_facts: list, clusters: list) -> list:
    """检查到期 follow_up，回测写 result。返回本轮回测了的条目。"""
    doc = state.load()
    today = datetime.now().strftime("%Y-%m-%d")
    checked = []
    changed = False
    for fu in doc.get("follow_ups", []):
        if fu.get("result") or fu.get("check_after", "9999") > today:
            continue
        metric = fu.get("metric", "")
        base = fu.get("baseline") or 0
        if metric.startswith("ref_loads:"):
            name = metric.split(":", 1)[1]
            cur = next((x["load_sessions"] for x in metrics_facts if x["name"] == name), None)
            if cur is None:
                fu["result"] = "improved"  # 名字彻底没人用了
            elif cur <= base:
                fu["result"] = "improved" if cur < base else "no_change"
            else:
                fu["result"] = "worse"  # 还在被加载，教训没拦住
            fu["result_detail"] = f"baseline={base} 现在={cur}"
        elif metric.startswith("cluster:"):
            key = metric.split(":", 1)[1]
            cur = 0
            for c in clusters:
                title = (c.get("title") or "").lower()
                if key in title or key in (c.get("cluster_key") or "").lower():
                    cur = max(cur, c.get("count") or 0)
            # count 是累计值：不再增长=改善；增长=复发
            if cur <= base:
                fu["result"] = "improved" if cur < base else "no_change"
            else:
                fu["result"] = "worse"
            fu["result_detail"] = f"baseline={base} 现在={cur}"
        else:
            fu["result"] = "inconclusive"
            fu["result_detail"] = "无自动指标，待用户/librarian 人工复核"
        fu["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        checked.append(fu)
        changed = True
    if changed:
        state.save(doc)
    return checked


def summary() -> dict:
    """效果追踪总账（喂 librarian evidence）。"""
    doc = state.load()
    fus = doc.get("follow_ups", [])
    out = {"total": len(fus), "improved": 0, "no_change": 0, "worse": 0,
           "inconclusive": 0, "pending": 0, "worse_items": []}
    for fu in fus:
        r = fu.get("result")
        if r is None:
            out["pending"] += 1
        else:
            out[r] = out.get(r, 0) + 1
            if r == "worse":
                out["worse_items"].append(f"{fu['proposal_id']}:{fu['target']} ({fu.get('result_detail','')})")
    return out
