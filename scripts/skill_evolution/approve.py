#!/usr/bin/env python3
"""approve.py — 提案审批执行器（用户批准才跑）

用法：
  python3 approve.py list                  # 列待审批
  python3 approve.py approve P001          # 标记批准；retire(disable) 类自动软禁用
  python3 approve.py reject P001 [理由]
  python3 approve.py undo P001             # 撤销软禁用（把名字从 skills.disabled 移除）

安全：
- 软禁用走 config.yaml skills.disabled（改前自动备份 config.yaml.bak-approve）
- 仅 retire(disable) 类自动执行；fix_reference/repair/enhance/new_skill 标记 approved 后由 agent 手动改（skill_manage），执行完再 approve --done
- ESSENTIAL（hermes-agent）和自建(user- 前缀（可用 SELF_SKILL_PREFIXES 追加）)提案拒绝自动执行
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state
import paths

HOME = paths.HOME
CONFIG = paths.HERMES_HOME / "config.yaml"  # 曾写死 HOME/".hermes"
ESSENTIAL = {"hermes-agent"}
SELF_PREFIX = paths.self_prefixes()


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
    return state.unique_proposal(state.load(), pid)


def cmd_list():
    for p in state.list_pending():
        print(f"{p['id']} [{p['kind']}] {p['target']} — {p.get('reason','')[:80]}")


def cmd_approve(pid, done=False, expected_target=None, expected_uid=None):
    def mutate(d):
        p = state.unique_proposal(d, pid, expected_target, expected_uid)
        if p["status"] == "approved" and not done:
            print(f"{pid} 已批准待执行；完成后用 approve.py approve {pid} --done")
            return
        if p["status"] not in ("pending", "approved"):
            raise ValueError(f"{pid} 状态={p['status']}，拒绝过期审批")
        if p["kind"] == "retire" and not done:
            if p["target"] in ESSENTIAL or p["target"].startswith(SELF_PREFIX):
                raise ValueError("Protected skill cannot be retired automatically")
            set_disabled(p["target"], True)
            p["executed"] = f"skills.disabled += {p['target']}"
            p["status"] = "done"
        elif done:
            p["status"] = "done"
        else:
            p["status"] = "approved"
        p["resolved"] = datetime.now().strftime("%Y-%m-%d")
        d["approved_changes"].append({"ts": datetime.now().isoformat(timespec="seconds"),
            "id": pid, "proposal_uid": p.get("uid"), "kind": p["kind"], "target": p["target"]})
        if p["status"] == "done":
            import followup, metrics, canonicalize
            existing = [f for f in d["follow_ups"] if f.get("proposal_uid") == p.get("uid")
                        and f.get("target") == p["target"] and f.get("proposal_id") == pid]
            if not existing:
                try:
                    fu = followup.create_follow_up(p, metrics.skill_facts(),
                        canonicalize.cluster(canonicalize.load_all_failures()))
                except Exception as exc:
                    # Confirmed execution may be recorded even when telemetry is
                    # unavailable, but its effect must remain explicitly unknown.
                    fu = {"proposal_id": pid, "target": p["target"],
                          "metric": "manual_review", "baseline": None, "result": None,
                          "check_after": datetime.now().strftime("%Y-%m-%d"),
                          "evidence_error": f"{type(exc).__name__}: {exc}"[:200]}
                if fu:
                    fu.update(proposal_uid=p.get("uid"), link_status="verified")
                    d["follow_ups"].append(fu)
        print(f"✅ {pid} {p['target']} → {p['status']}")
        if p["status"] == "approved":
            print(f"执行完成后运行 approve.py approve {pid} --done")
    return state.update(mutate)


def x_status_done(d, pid):
    return state.unique_proposal(d, pid)["status"] == "done"


def cmd_reject(pid, reason="", expected_target=None, expected_uid=None):
    def mutate(d):
        p = state.unique_proposal(d, pid, expected_target, expected_uid)
        if p["status"] != "pending":
            raise ValueError("Only pending proposals can be rejected")
        p.update(status="rejected", resolved=datetime.now().strftime("%Y-%m-%d"), reject_reason=reason)
        print(f"❌ {pid} {p['target']} 已驳回")
    return state.update(mutate)


def cmd_undo(pid, expected_target=None, expected_uid=None):
    def mutate(d):
        p = state.unique_proposal(d, pid, expected_target, expected_uid)
        if not p.get("executed", "").startswith("skills.disabled"):
            raise ValueError("No automatic execution to undo")
        set_disabled(p["target"], False)
        p["status"] = "pending"
        p.pop("executed", None)
    return state.update(mutate)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "approve", "reject", "undo"], nargs="?", default="list")
    parser.add_argument("pid", nargs="?")
    parser.add_argument("reason", nargs="*", default=[])
    parser.add_argument("--done", action="store_true")
    parser.add_argument("--expected-target")
    parser.add_argument("--uid")
    args = parser.parse_args()
    try:
        if args.command == "list":
            cmd_list()
        else:
            if not args.pid:
                parser.error("proposal ID required")
            kw = {"expected_target": args.expected_target, "expected_uid": args.uid}
            if args.command == "approve":
                cmd_approve(args.pid, done=args.done, **kw)
            elif args.command == "reject":
                cmd_reject(args.pid, " ".join(args.reason), **kw)
            else:
                cmd_undo(args.pid, **kw)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        sys.exit(2)
