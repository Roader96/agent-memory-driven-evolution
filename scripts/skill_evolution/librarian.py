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
sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
import agent_adapter

HOME = Path.home()
HERMES_BIN = agent_adapter.hermes_bin()
VAULT = Path(os.environ.get("HERMES_VAULT", HOME / "HermesMemory"))
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
            and not x["name"].startswith(("roader", "Roader", "user", "auto-skill-save"))]
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

输出严格格式（纯 markdown，不要代码块包裹，不要寒暄）：
## 📊 本周健康度
（1-3 句：全局成功率、技能库规模、明显问题）
## 🔧 技能提案
### [L1] kind: target
**理由**：… **证据**：… **动作**：…
（逐条）

证据：
{evidence}
"""


def call_llm(prompt: str, timeout=420):
    # 经适配器：Hermes 走 --query-file，其他 agent 走 AGENT_LLM/stdin，失败返回空串
    return agent_adapter.llm_call(prompt, source=SRC, timeout=timeout, query_file=True)


def main():
    ev = gather_evidence()
    # 覆盖门禁用：错误簇编号 + 失败会话编号
    cluster_ids = [f"C{i+1}" for i, _ in enumerate(ev.get("error_clusters", []))]
    sess_ids = [f"F{i+1}" for i, _ in enumerate(ev.get("failed_sessions", []))]

    # 给证据加编号
    for i, c in enumerate(ev.get("error_clusters", [])):
        c["cid"] = f"C{i+1}"
    for i, s in enumerate(ev.get("failed_sessions", [])):
        s["fid"] = f"F{i+1}"

    prompt = PROMPT.format(mark=MARK,
                           evidence=json.dumps(
                               ev, ensure_ascii=False, indent=1,
                               default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else str(o),
                           )[:12000])
    out = call_llm(prompt)

    llm_ok = (len(out) > 100 and "技能提案" in out)
    if llm_ok:
        # 覆盖门禁：真痛点 = 复发 ≥3 次的簇（count≥3），必须被引用；
        # count=2 的小簇由模型取舍——强制全覆盖只会逼它为长尾噪声提案（Ratchet 反技能膨胀）
        must = {f"C{i+1}" for i, c in enumerate(ev.get("error_clusters", []))
                if (c.get("count") or 0) >= 3}
        hv_sessions = {s["fid"] for s in ev.get("failed_sessions", [])
                       if s.get("confidence") == "high"}
        found = set(re.findall(r"\b(C\d+|F\d+)\b", out))
        missing = sorted((must | hv_sessions) - found)
        if missing:
            print(f"⚠️ 图书管理员漏覆盖复发簇(≥3次) {missing}，本周降级（只走规则提案）",
                  file=sys.stderr)
            llm_ok = False

    # LLM 提案解析入队（之前只写周报会丢——提案必须进队列才能被用户审批）
    # 理由/证据/动作可能分行也可能挤在同一段，分段提取不依赖换行
    llm_props = []
    if llm_ok:
        for m in re.finditer(r"###\s*\[L\d+\]\s*(\w+):\s*(.+?)\n(.*?)(?=\n###|\Z)",
                             out, re.S):
            kind, target, body = m.group(1).strip(), m.group(2).strip(), m.group(3)
            def _grab(label):
                mm = re.search(r"\*\*" + label + r"\*\*[：:]\s*(.+?)(?=\*\*(?:理由|证据|动作)\*\*[：:]|\Z)",
                               body, re.S)
                return re.sub(r"\s+", " ", mm.group(1)).strip() if mm else ""
            reason, evidence, action = _grab("理由"), _grab("证据"), _grab("动作")
            if kind not in ("new_skill", "enhance", "retire", "fix_reference", "repair"):
                kind = "enhance"
            if not reason:
                continue
            p, added = state.add_proposal({
                "kind": kind, "target": target[:60],
                "reason": f"[librarian] {reason[:180]}",
                "evidence": f"{evidence[:180]} | 动作: {action[:120]}",
                "confidence": "medium",
            })
            if added:
                llm_props.append(p)
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
        lines.append(f"_本周 LLM 未产出（降级）。rc={rc}。_")
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
    print(f"✅ 周报: {rfile}")
    print(f"   规则提案 {len(rule_props)} 条，LLM 提案入队 {len(llm_props)} 条，LLM {'OK' if llm_ok else '降级'}")
    return llm_ok


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 2)  # 降级也视为跑完，不算失败
