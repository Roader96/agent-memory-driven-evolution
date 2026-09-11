#!/usr/bin/env python3
"""approve.py — 提案审批执行器（哥说批准才跑）

用法：
  python3 approve.py list                  # 列待审批
  python3 approve.py approve P001          # 标记批准；retire(disable) 类自动软禁用
  python3 approve.py reject P001 [理由]
  python3 approve.py undo P001             # 撤销软禁用（把名字从 skills.disabled 移除）

安全：
- 软禁用走 config.yaml skills.disabled（改前自动备份 config.yaml.bak-approve）
- 仅 retire(disable) 类自动执行；fix_reference/repair/enhance/new_skill 标记 approved 后由 agent 手动改（skill_manage），执行完再 approve --done
- ESSENTIAL（hermes-agent）和自建(roader*)提案拒绝自动执行
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state

HOME = Path.home()
CONFIG = HOME / ".hermes" / "config.yaml"
ESSENTIAL = {"hermes-agent"}


def _load_yaml():
    try:
        import yaml
    except ImportError:
        print("需要 pyyaml", file=sys.stderr)
        sys.exit(1)
    d = yaml.safe_load(CONFIG.read_text()) or {}
    return yaml, d


def _save_yaml(yaml, d):
    bak = CONFIG.with_suffix(".yaml.bak-approve")
    shutil.copy2(CONFIG, bak)
    CONFIG.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False))


def set_disabled(name: str, disabled: bool):
    yaml, d = _load_yaml()
    sk = d.setdefault("skills", {})
    lst = sk.get("disabled") or []
    if isinstance(lst, str):
        lst = [lst]
    lst = [x for x in lst if x != name]
    if disabled:
        lst.append(name)
    sk["disabled"] = sorted(set(lst))
    _save_yaml(yaml, d)


def find(pid):
    for p in state.load()["proposals"]:
        if p["id"] == pid:
            return p
    return None


def cmd_list():
    pend = [p for p in state.load()["proposals"] if p["status"] == "pending"]
    if not pend:
        print("队列空。")
        return
    for p in pend:
        print(f"{p['id']} [{p['kind']:14}] {p['target']:36} {p['reason'][:60]} ({p.get('confidence','')})")


def cmd_approve(pid, done=False):
    p = find(pid)
    if not p:
        print(f"找不到 {pid}", file=sys.stderr); sys.exit(1)
    if p["status"] != "pending":
        print(f"{pid} 状态={p['status']}，不是 pending"); return
    d = state.load()
    for x in d["proposals"]:
        if x["id"] == pid:
            if done or p["kind"] not in ("retire",):
                x["status"] = "done"
                x["resolved"] = datetime.now().strftime("%Y-%m-%d")
                print(f"✅ {pid} 标记 done（{p['kind']} {p['target']}）")
            else:
                # retire+disable：自动软禁用
                if p["target"] in ESSENTIAL or p["target"].startswith(("roader", "Roader")):
                    print(f"⛔ {p['target']} 受保护（essential/自建），拒绝自动执行")
                    return
                set_disabled(p["target"], True)
                x["status"] = "done"
                x["resolved"] = datetime.now().strftime("%Y-%m-%d")
                x["executed"] = f"skills.disabled += {p['target']}"
                print(f"✅ {pid} 已批准并软禁用 {p['target']}（config.yaml skills.disabled，可 undo）")
    d["approved_changes"].append({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "id": pid, "kind": p["kind"], "target": p["target"],
    })
    state.save(d)
    # 标 done 自动挂 7 天回测（Ratchet 闭环：执行了≠有效）
    if x_status_done(d, pid):
        try:
            import followup, metrics, canonicalize
            facts = metrics.skill_facts()
            clusters = canonicalize.cluster(canonicalize.load_all_failures())
            fu = followup.create_follow_up(p, facts, clusters)
            if fu:
                d2 = state.load()
                d2.setdefault("follow_ups", []).append(fu)
                state.save(d2)
                print(f"   ↳ 已挂 7 天回测: {fu['metric']} (baseline={fu['baseline']})")
        except Exception as e:
            print(f"   ↳ 回测挂载失败（不影响审批）: {e}")


def x_status_done(d, pid):
    return any(x["id"] == pid and x["status"] == "done" for x in d["proposals"])


def cmd_reject(pid, reason=""):
    p = find(pid)
    if not p:
        print(f"找不到 {pid}", file=sys.stderr); sys.exit(1)
    d = state.load()
    for x in d["proposals"]:
        if x["id"] == pid:
            x["status"] = "rejected"
            x["resolved"] = datetime.now().strftime("%Y-%m-%d")
            x["reject_reason"] = reason
    state.save(d)
    print(f"❌ {pid} 已否决：{p['target']}（{reason}）——以后不再重复提")


def cmd_undo(pid):
    p = find(pid)
    if not p:
        print(f"找不到 {pid}", file=sys.stderr); sys.exit(1)
    if p.get("executed", "").startswith("skills.disabled"):
        set_disabled(p["target"], False)
        d = state.load()
        for x in d["proposals"]:
            if x["id"] == pid:
                x["status"] = "pending"
                x.pop("executed", None)
        state.save(d)
        print(f"↩️ {pid} 撤销：{p['target']} 已从 skills.disabled 移除，提案回到 pending")
    else:
        print(f"{pid} 没有可撤销的自动执行记录")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "approve":
        cmd_approve(sys.argv[2], done="--done" in sys.argv)
    elif cmd == "reject":
        cmd_reject(sys.argv[2], " ".join(sys.argv[3:]))
    elif cmd == "undo":
        cmd_undo(sys.argv[2])
    else:
        print(f"未知命令 {cmd}", file=sys.stderr); sys.exit(1)
