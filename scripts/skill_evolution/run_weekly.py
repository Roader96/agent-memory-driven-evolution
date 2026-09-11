#!/usr/bin/env python3
"""run_weekly.py — 每周技能自进化编排（launchd 周日 21:30，零 token 触发 + 1 次 LLM）

流程：
  1. metrics     采集技能度量快照 → state.weekly_snapshots
  2. curator     规则提案（退役/坏引用/损坏修复）→ state.proposals
  3. librarian   LLM 周审（失败簇→提案，含覆盖门禁）→ state.proposals + OB 周报
  4. 健康摘要    全局成功率趋势 + 提案队列统计
全链路失败不重试多次（每周一次，失败下周再来 + 日志可查），但内容门禁防垃圾报告。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import metrics, state, curator, librarian
import paths

HOME = paths.HOME
VAULT = paths.VAULT  # 单一来源：HERMES_VAULT 环境变量可覆盖（曾写死 Path.home()/"HermesMemory"）


def main():
    print("=== 1. metrics 快照 ===")
    facts = metrics.skill_facts()
    used = [x for x in facts if x["load_sessions"] > 0]
    dead = [x for x in facts if x["installed"] and x["load_sessions"] == 0]
    broken = [x for x in facts if not x["installed"] and x["load_sessions"] > 0]
    gstats = {
        "total_installed": sum(1 for x in facts if x["installed"]),
        "used": len(used), "dead": len(dead), "broken_ref": len(broken),
    }
    st = state.load()
    prev = curator.prev_zero_baseline(st)
    state.add_snapshot(facts, gstats)
    print(json.dumps(gstats, ensure_ascii=False))

    # 1.5 硬 cap=120：超额自动软禁用（用户 2026-09-10 授权，全部可逆）
    cap_actions = []
    try:
        import cap_enforcer
        auto_cap = os.environ.get("AUTO_APPLY_CAP", "0") == "1"
        cr = cap_enforcer.enforce_cap(facts, cap=120, dry_run=not auto_cap)
        cap_actions = cr.get("disabled_now", [])
        if cap_actions:
            print(f"=== 1.5 硬 cap 执行：active {cr['active_before']}→{cr['active_after']}，禁用 {len(cap_actions)} 个 ===")
            for x in cap_actions:
                print(f"  ⛔ {x['name']}")
            # 被 cap 自动禁用的目标，其 pending retire 提案直接标 done（避免飞书还催审批）
            disabled_names = {x["name"] for x in cap_actions}
            from datetime import datetime as _dt
            stc = state.load()
            closed = 0
            for p in stc["proposals"]:
                if (p["status"] == "pending" and p["kind"] == "retire"
                        and p["target"] in disabled_names):
                    p["status"] = "done"
                    p["resolved_at"] = _dt.now().strftime("%Y-%m-%d %H:%M")
                    p["resolution"] = f"硬 cap=120 自动软禁用（{cr['active_before']}→{cr['active_after']}）"
                    closed += 1
            state.save(stc)
            if closed:
                print(f"  （关闭 {closed} 条重复 retire 提案）")
                # cap 自动禁用的也必须挂回测：指标=禁用后是否仍被 skill_view（有=误杀）
                try:
                    import followup
                    import canonicalize as _can
                    stf = state.load()
                    have = {f["proposal_id"] for f in stf.get("follow_ups", [])}
                    clusters_now = _can.cluster(_can.load_all_failures())
                    for p in stf["proposals"]:
                        if (p["status"] == "done" and p["id"] not in have
                                and p.get("resolution", "").startswith("硬 cap")):
                            fu = followup.create_follow_up(p, facts, clusters_now)
                            if fu:
                                stf.setdefault("follow_ups", []).append(fu)
                    state.save(stf)
                except Exception as _e:
                    print(f"  （cap 回测挂载跳过: {_e}）")
            # 重新采一遍 facts（disabled 状态变了，后续提案别重复提这些）
            facts = metrics.skill_facts()
    except Exception as e:
        print(f"⚠️ cap 执行异常（不阻断）: {e}")

    print("=== 2. curator 规则提案 ===")
    rule_props = curator.curate(facts, prev)
    n_new = 0
    for p in rule_props:
        _, added = state.add_proposal(p)
        n_new += int(added)
    print(f"规则提案 {len(rule_props)} 条，新增入队 {n_new} 条（首期无基线时退役项=0）")

    print("=== 3. follow_up 效果回测 ===")
    try:
        import followup, canonicalize
        clusters = canonicalize.cluster(canonicalize.load_all_failures()) if canonicalize else []
        checked = followup.check_due(facts, clusters)
        eff = followup.summary()
        print(f"回测 {len(checked)} 条到期项；效果总账: 改善 {eff['improved']} / 无变化 {eff['no_change']} / 恶化 {eff['worse']} / 待回测 {eff['pending']}")
        for fu in checked:
            print(f"  {fu['proposal_id']} {fu['target']}: {fu['result']} ({fu.get('result_detail','')})")
    except Exception as e:
        print(f"⚠️ follow_up 回测异常（不杀周报）: {e}")

    print("=== 4. librarian LLM 周审 ===")
    librarian_ok = False
    try:
        librarian_ok = bool(librarian.main())
    except Exception as e:
        print(f"⚠️ librarian 异常（不杀周报）: {e}", file=sys.stderr)

    # 4.5 正向成长（主航道）：从用户的纠正里归纳隐性偏好
    print("=== 4.5 preference_miner 偏好归纳 ===")
    pref_new = 0
    pref_trend = None
    try:
        import preference_signals as psig, preference_miner as pminer
        sig = psig.collect(30)
        pref_trend = sig["counts"]
        # 记录每周纠正趋势（回测"学没学会"用）
        stt = state.load()
        stt.setdefault("preference_trend", []).append({
            "week": datetime.now().strftime("%Y-%m-%d"),
            "corrections_30d": sig["counts"]["corrections"],
            "approvals_30d": sig["counts"]["approvals"],
        })
        stt["preference_trend"] = stt["preference_trend"][-26:]
        state.save(stt)
        before = len([p for p in state.load().get("preferences", []) if p["status"] == "pending"])
        pminer.mine()
        after = len([p for p in state.load().get("preferences", []) if p["status"] == "pending"])
        pref_new = max(0, after - before)
        print(f"近30天纠正 {sig['counts']['corrections']} 次，新增偏好候选 {pref_new} 条")
    except Exception as e:
        print(f"⚠️ preference_miner 异常（不杀周报）: {e}", file=sys.stderr)

    print("=== 5. 汇总 ===")
    st2 = state.load()
    pend = [p for p in st2["proposals"] if p["status"] == "pending"]
    pend_pref = [p for p in st2.get("preferences", []) if p.get("status") == "pending"]
    print(f"待审批提案 {len(pend)} 条；待批偏好 {len(pend_pref)} 条：")
    for p in pend[:12]:
        print(f"  {p['id']} [{p['kind']}] {p['target']} — {p['reason'][:50]}")
    print(f"周报: {VAULT}/skill-evolution/（最新一份）")

    # 提醒（用户定稿：飞书完整摘要，系统通知看不全弃用）
    # 有待批【偏好】或【技能提案】才发；全空静默；飞书挂 → Mac 通知兜底
    # 偏好是主航道（让我变聪明），放最前面
    if pend or pend_pref:
        eff_line = ""
        try:
            import followup
            eff = followup.summary()
            if eff["total"]:
                eff_line = (f"\n🔬 效果回测：改善 {eff['improved']} · 无变化 {eff['no_change']} · "
                            f"恶化 {eff['worse']} · 待回测 {eff['pending']}")
                for w in eff.get("worse_items", []):
                    eff_line += f"\n   ⚠️ 恶化: {w}"
        except Exception:
            pass
        lines = [f"🧬 技能自进化周报 {datetime.now().strftime('%Y-%m-%d')}",
                 "━" * 18]
        # cap 执行段放最前面（自动动作必须让用户看到）
        if cap_actions:
            lines.append(f"⛔ 硬 cap=120：本周自动软禁用 {len(cap_actions)} 个零加载技能")
            for x in cap_actions[:8]:
                lines.append(f"  · {x['name']}")
            if len(cap_actions) > 8:
                lines.append(f"  …另 {len(cap_actions)-8} 个见周报")
            lines.append("↩️ 撤销任一个：cap_enforcer.py --restore <名字>")
            lines.append("")
        # 重新统计 active（cap 后）
        active_now = sum(1 for x in facts if x.get("installed") and not x.get("disabled"))
        lines.append(f"📊 活跃库 {active_now}/120 · 全库 {gstats['total_installed']}" + eff_line)
        lines.append("")
        # 偏好候选（主航道，放技能提案前面）
        if pend_pref:
            lines.append(f"🧠 待批【习惯偏好】{len(pend_pref)} 条（批准后我立刻学会）：")
            for p in pend_pref[:6]:
                lines.append(f"• {p['id']} [{p.get('category','')}] {p.get('title','')}")
                lines.append(f"  {p.get('rule','')[:70]}")
            lines.append("回复「批准 UP001」/「偏好全批」/「UP001 否了」")
            lines.append("")
        if pend:
            lines.append(f"📋 待审批技能提案 {len(pend)} 条：")
            for p in pend[:10]:
                lines.append(f"• {p['id']} [{p['kind']}] {p['target']}")
                lines.append(f"  {p['reason'][:60]}")
            if len(pend) > 10:
                lines.append(f"  …另 {len(pend)-10} 条见周报")
        lines += ["", f"📂 全文: HermesMemory/skill-evolution/ 最新周报",
                  "技能提案回复「批准 P113」/「全部批准」我执行"]
        msg = "\n".join(lines)
        try:
            import subprocess
            r = subprocess.run(
                ["python3", str(HOME / ".hermes/scripts/send_feishu_dm.py"), msg],
                capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                print("📨 飞书周报已送达")
            else:
                raise RuntimeError(r.stderr[-120:] or r.stdout[-120:])
        except Exception as e:
            print(f"⚠️ 飞书发送失败，Mac 通知兜底: {e}", file=sys.stderr)
            if sys.platform == "darwin":  # macOS 才用 osascript 通知
                try:
                    subprocess.run(["/usr/bin/osascript", "-e",
                                    f'display notification "{len(pend)} 条提案待批，飞书推送失败" '
                                    f'with title "🧬 技能自进化周报" sound name "Basso"'],
                                   capture_output=True, timeout=10)
                except Exception:
                    pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
