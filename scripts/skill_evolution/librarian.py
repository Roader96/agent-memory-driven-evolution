#!/usr/bin/env python3
"""librarian.py — 图书管理员（Ratchet 核心：失败簇 → 技能提案，用户审批）

每周一次。收集证据 → LLM 一次调用出提案 → 覆盖门禁 → 写提案队列 → OB 周报。
绝不自动创建/修改技能，只把候选放队列等用户点头（借 agent-memory-loop promotion-queue）。

证据来源（全本地）：
  metrics.py        技能需求/坏引用/陈旧
  canonicalize.py   错误模式簇（≥2次的重复教训）
  outcome_scorer.py 近7天失败会话（高置信）
  state.py          已否决提案（防复活）+ 已采纳历史
LLM 调用带覆盖门禁：每个输入证据簇/失败会话编号必须出现在输出提案里。
失败（超时/漏覆盖/空）→ 降级：只把 curator 的规则提案写盘，不出 LLM 提案，本周报照常。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state
import paths as _paths_mod
sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
import agent_adapter

HOME = _paths_mod.HOME
HERMES_BIN = agent_adapter.hermes_bin()
VAULT = _paths_mod.VAULT
SRC = "skill-evolution-librarian"
MARK = "[skill-evolution-librarian]"

# 依赖降级：缺哪个模块就用空
try:
    import metrics
except Exception:
    metrics = None
try:
    import canonicalize
except Exception:
    canonicalize = None
try:
    import outcome_scorer
except Exception:
    outcome_scorer = None


def gather_evidence(facts=None):
    facts = facts if facts is not None else (metrics.skill_facts() if metrics else [])
    ev = {"date": __import__("datetime").datetime.now().strftime("%Y-%m-%d")}

    # 技能概览
    used = [x for x in facts if x["load_sessions"] > 0]
    dead = [x for x in facts if x["installed"] and x["load_sessions"] == 0
            and x["age_days"] and x["age_days"] >= 90
            and not x["name"].startswith(_paths_mod.self_prefixes() + ("auto-skill-save",))]
    broken_ref = [x for x in facts if not x["installed"] and x["load_sessions"] > 0]
    slim = lambda x: {"name": x["name"], "load_sessions": x["load_sessions"],
                      "size_bytes": x.get("size_bytes"), "age_days": x.get("age_days")}
    ev["skill_stats"] = {
        "total_installed": sum(1 for x in facts if x["installed"]),
        "used": len(used), "dead_old": len(dead), "broken_ref": len(broken_ref),
        "top_used": [slim(x) for x in sorted(used, key=lambda x: -x["load_sessions"])[:10]],
    }
    ev["dead_candidates"] = [slim(x) for x in dead[:15]]
    ev["broken_refs"] = [slim(x) for x in broken_ref]

    # 错误簇（top 10 + 例证精简：evidence 总长须 <12k，否则 PROMPT 截断
    # 会把后面的簇切掉，模型看不见却还要被覆盖门禁检查 → 必降级）
    ev["error_clusters"] = []
    if canonicalize:
        try:
            cl = canonicalize.cluster(canonicalize.load_all_failures())
            trimmed = []
            # 冷库索引：错误簇 → 冷库里可能已有解决方案的文件（用户 2026-09-10：
            # 分类员要调冷记忆库，新提案优先从冷库已有经验提炼，不从零造）
            vault = VAULT
            vault_docs = []
            import time as _t
            cutoff = _t.time() - 180 * 86400
            for sub in ("preferences", "projects", "incidents", "daily"):
                d = vault / sub
                if not d.exists():
                    continue
                for md in d.rglob("*.md"):
                    if md.name.startswith("_"):
                        continue
                    try:
                        if md.stat().st_mtime < cutoff:
                            continue
                        vault_docs.append((str(md.relative_to(vault)),
                                           md.read_text(encoding="utf-8", errors="ignore").lower()))
                    except OSError:
                        continue
            for c in cl[:10]:
                c = dict(c)
                c["examples"] = [str(e)[:80] for e in (c.get("examples") or [])[:1]]
                if isinstance(c.get("sources"), (set, frozenset)):
                    c["sources"] = sorted(c["sources"])
                # 簇标题关键词搜冷库（取 2 个以上 token 命中的文件）
                kws = [w for w in re.split(r"[\s/._-]+", (c.get("title") or "").lower())
                       if len(w) >= 4]
                hits = []
                for rel, txt in vault_docs:
                    score = sum(1 for w in kws if w in txt)
                    if score >= 2:
                        hits.append(rel)
                if hits:
                    c["vault_solutions"] = hits[:3]
                trimmed.append(c)
            ev["error_clusters"] = trimmed
        except Exception as e:
            ev["error_clusters"] = [{"title": f"(canonicalize 失败: {e})"}]

    # 失败会话
    ev["failed_sessions"] = []
    if outcome_scorer:
        try:
            w = outcome_scorer.score_window(days=7)
            ev["global_health"] = {
                "success": w["success"], "fail": w["fail"],
                "uncertain": w["uncertain"], "success_rate": w["success_rate"],
            }
            ev["failed_sessions"] = w["failed_sessions"][:10]
        except Exception as e:
            ev["global_health"] = {"note": f"(outcome_scorer 失败: {e})"}

    # 已否决/已采纳/待审批（防重复提+防提案漂移：同一问题每周换着花样提）
    st = state.load()
    ev["rejected"] = [p["target"] for p in st["proposals"] if p["status"] == "rejected"]
    ev["done"] = [p["target"] for p in st["proposals"] if p["status"] == "done"]
    ev["pending"] = [f"{p['kind']}: {p['target']}" for p in st["proposals"]
                     if p["status"] == "pending"][:20]
    # 效果追踪总账：上周提案有没有真起效（恶化的必须复盘）
    try:
        import followup
        ev["followup_summary"] = followup.summary()
    except Exception:
        pass
    return ev


PROMPT = """{mark} 你是 Hermes 技能图书管理员。基于下列本周证据，提出技能改进提案（不执行，只提案给用户审批）。

硬约束（借 Ratchet / agent-memory-loop）：
1. 只从证据出发，不许编造没证据的技能
2. 提案类型只限：retire(退役候选)/fix_reference(坏引用)/repair(损坏)/enhance(现有技能修订)/new_skill(新技能)
3. 新技能必须满足：有≥2次的失败簇 或 ≥2次反复加载但缺失的场景证据；不许拍脑袋
4. 不许提已在 rejected/done/pending 列表里的 target（pending=已在队列等审批，重复提=提案漂移）
5. 每个提案必须带证据引用（来源 cluster/skill 名 + 计数）
6. 总提案 ≤ 8 个，宁缺毋滥
7. 每个提案用编号 [L1][L2]...，并独立成段
8. 若 followup_summary 里有 worse_items（上周提案执行后指标恶化），必须逐条复盘并出修正提案——执行了没效果比没执行更需要处理
9. 簇带 vault_solutions 字段时（冷库永久记忆里的历史方案文件），提案必须先评估这些已有经验：能引用/固化成技能的优先，别从零造重复技能
10. 必须在「证据覆盖」节逐项引用所有 required_coverage 编号（如 C1、F1、W1）。每项说明：提出修正 / 已有提案覆盖 / 证据不足暂缓。覆盖不等于强制创建提案，不许为凑覆盖重复提案。
11. 累计错误数增长只证明复发，不能推断错误率恶化或技能造成退化；复盘必须区分这两者。

输出严格格式（纯 markdown，不要代码块包裹，不要寒暄）：
## 📊 本周健康度
（1-3 句：全局成功率、技能库规模、明显问题）
## 🔧 技能提案
### [L1] kind: target
**理由**：… **证据**：… **动作**：…
（逐条）
## 证据覆盖
（逐项写 required_coverage 编号及处理理由；允许多个编号由同一提案覆盖）

证据：
{evidence}
"""


def call_llm(prompt: str, timeout=420):
    # 经适配器：Hermes 走 --query-file，其他 agent 走 AGENT_LLM/stdin，失败返回空串
    return agent_adapter.llm_call(prompt, source=SRC, timeout=timeout, query_file=True)


def prepare_evidence(ev: dict) -> dict:
    """Bound fields, never slice serialized JSON or remove required IDs."""
    import copy
    ev = copy.deepcopy(ev)
    for prefix, key, field in (("C", "error_clusters", "cid"), ("F", "failed_sessions", "fid")):
        ev[key] = ev.get(key, [])[:10]
        for i, item in enumerate(ev[key], 1):
            item[field] = f"{prefix}{i}"
    summary = ev.get("followup_summary", {})
    worse = list(dict.fromkeys(summary.get("worse_items", []) + summary.get("review_items", [])))
    ev["followup_reviews"] = [{"wid": f"W{i}", "observation": item}
                              for i, item in enumerate(worse, 1)]
    ev["required_coverage"] = (
        [c["cid"] for c in ev["error_clusters"] if (c.get("count") or 0) >= 3]
        + [s["fid"] for s in ev["failed_sessions"] if s.get("confidence") == "high"]
        + [w["wid"] for w in ev["followup_reviews"]])
    return ev


def evidence_json(ev: dict, budget: int = 12000) -> str:
    """Shrink optional context without hiding evidence behind a JSON cutoff."""
    def bound(value, limit):
        if isinstance(value, str):
            return value if len(value) <= limit else value[:limit] + "…"
        if isinstance(value, dict):
            return {k: bound(v, limit) for k, v in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            values = sorted(value) if isinstance(value, (set, frozenset)) else value
            return [bound(v, limit) for v in values]
        return value
    for limit in (240, 120, 60):
        slim = bound(ev, limit)
        encoded = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= budget:
            return encoded
    # Keep every required evidence item; discard optional catalogue/history.
    slim = {k: slim[k] for k in ("date", "error_clusters", "failed_sessions",
                                 "followup_reviews", "required_coverage") if k in slim}
    encoded = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > budget:
        raise ValueError("Required evidence exceeds prompt budget; refusing to truncate IDs")
    return encoded


def review_output(out: str, required: list[str]) -> str:
    if len(out) <= 100 or "技能提案" not in out:
        return "empty_or_invalid_output"
    found = set(re.findall(r"\b(C\d+|F\d+|W\d+)\b", out))
    missing = sorted(set(required) - found)
    return "missing_coverage:" + ",".join(missing) if missing else ""


def main():
    ev = prepare_evidence(gather_evidence())
    out = ""
    err = ""
    attempts = 0
    try:
        prompt = PROMPT.format(mark=MARK, evidence=evidence_json(ev))
        attempts = 1
        out = call_llm(prompt)
        err = review_output(out, ev["required_coverage"])
        if not out and agent_adapter.last_llm_failure():
            err = agent_adapter.last_llm_failure()
        # A single content repair is distinct from transport retries. Never
        # enqueue partial proposals before the complete report passes coverage.
        if err.startswith("missing_coverage:"):
            attempts = 2
            out = call_llm(prompt + "\n\n上次输出未通过覆盖检查：" + err
                           + "。请重新输出完整周报，证据覆盖节逐项说明所有必需编号。")
            err = review_output(out, ev["required_coverage"])
            if not out and agent_adapter.last_llm_failure():
                err = agent_adapter.last_llm_failure()
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    llm_ok = not err
    if not llm_ok:
        agent_adapter._log_llm_failure("librarian-degraded", f"source={SRC} reason={err}")
        print(f"⚠️ 图书管理员降级：{err}", file=sys.stderr)

    # LLM 提案解析入队（之前只写周报会丢——提案必须进队列才能被用户审批）
    # 理由/证据/动作可能分行也可能挤在同一段，分段提取不依赖换行
    llm_props = []
    if llm_ok:
        matches = list(re.finditer(r"###\s*\[L\d+\]\s*(\w+):\s*(.+?)\n(.*?)(?=\n#{2,3}\s|\Z)", out, re.S))
        for m in matches[:8]:
            kind, target, body = m.group(1).strip(), m.group(2).strip(), m.group(3)
            def _grab(label):
                mm = re.search(r"\*\*" + label + r"\*\*[：:]\s*(.+?)(?=\*\*(?:理由|证据|动作)\*\*[：:]|\Z)",
                               body, re.S)
                return re.sub(r"\s+", " ", mm.group(1)).strip() if mm else ""
            reason, evidence, action = _grab("理由"), _grab("证据"), _grab("动作")
            if kind not in ("new_skill", "enhance", "retire", "fix_reference", "repair"):
                continue
            if not reason or not evidence or not action:
                continue
            if target in ev.get("rejected", []) or target in ev.get("done", []):
                continue
            if any(entry.split(": ", 1)[-1] == target for entry in ev.get("pending", [])):
                continue
            proposal = {
                "kind": kind, "target": target[:60],
                "reason": f"[librarian] {reason[:180]}",
                "evidence": f"{evidence[:180]} | 动作: {action[:120]}",
                "confidence": "medium",
            }
            _, added = state.add_proposal(proposal)
            if added:
                llm_props.append(proposal)
    if not llm_ok:
        out = ""

    # 规则提案由 run_weekly 统一入队；librarian 单跑时才自己走一遍 curator
    import curator
    st = state.load()
    already = len(st.get("proposals", []))
    rule_props = []
    if os.environ.get("LIBRARIAN_STANDALONE") == "1":
        base = curator.prev_zero_baseline(st)
        facts = metrics.skill_facts() if metrics else []
        rule_props = curator.curate(facts, base)
        for p in rule_props:
            state.add_proposal(p)

    # 写 OB 周报
    report_dir = VAULT / "skill-evolution"
    report_dir.mkdir(parents=True, exist_ok=True)
    wk = ev["date"]
    rfile = report_dir / f"{wk}-skill-evolution-weekly.md"
    lines = [f"# 技能自进化周报 {wk}", ""]
    lines.append(f"> 生成时间：{__import__('datetime').datetime.now().strftime('%H:%M')}")
    lines.append("")
    if llm_ok:
        lines.append("## 🤖 图书管理员提案（LLM，待用户审批）")
        lines.append("")
        lines.append(out)
    else:
        lines.append("## 🤖 图书管理员")
        lines.append("")
        lines.append(f"_本周 LLM 降级：{err}。规则提案仍保留。_")
        lines.append("")
        lines.append(f"> 归因日志：`{_paths_mod.HERMES_HOME}/logs/llm_adapter.log`"
                     "（含退出码/超时/stderr 摘要，已自动重试 1 次）")
        if err:
            lines.append(f"```\n{err[-300:]}\n```")
    lines.append("")
    lines.append(f"## 📋 规则提案（馆长，已进队列）")
    lines.append("")
    if rule_props:
        for p in rule_props:
            lines.append(f"- **{p['kind']}** `{p['target']}` — {p['reason']}（{p['confidence']}）")
    else:
        lines.append("_由 run_weekly 统一入队（见队列状态）_")
    lines.append("")
    lines.append(f"## 📊 队列状态")
    lines.append("")
    st2 = state.load()
    npend = sum(1 for p in st2["proposals"] if p["status"] == "pending")
    lines.append(f"- 待审批：{npend} 条 · 历史已采纳：{sum(1 for p in st2['proposals'] if p['status']=='done')} 条")
    lines.append("")
    lines.append("---")
    lines.append("_图书管理员只提案不执行，批准请用户在会话里说/直接跑 skill_manage_")
    rfile.write_text("\n".join(lines), encoding="utf-8")
    health_dir = VAULT / ".checkpoints"
    health_dir.mkdir(parents=True, exist_ok=True)
    health = {"checked_at": __import__('datetime').datetime.now().isoformat(),
              "status": "ok" if llm_ok else "degraded", "reason": err,
              "attempts": attempts, "required_coverage": ev["required_coverage"],
              "llm_proposals_added": len(llm_props), "report": str(rfile)}
    hp = health_dir / "evolution-health.json"
    tmp = hp.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(hp)
    print(f"✅ 周报: {rfile}")
    print(f"   规则提案 {len(rule_props)} 条，LLM 提案入队 {len(llm_props)} 条，LLM {'OK' if llm_ok else '降级'}")
    if not llm_ok:
        print(f"   ⚠️ LLM 降级原因见 {_paths_mod.HERMES_HOME}/logs/llm_adapter.log")
    return llm_ok


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 2)  # 降级也视为跑完，不算失败
