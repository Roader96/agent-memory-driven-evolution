#!/usr/bin/env python3
"""approve_pref.py — 偏好候选审批

用法：
  python3 approve_pref.py list              # 列待批偏好
  python3 approve_pref.py approve UP001      # 标记 approved（agent 随后写进 USER profile）
  python3 approve_pref.py approve-all        # 全批
  python3 approve_pref.py reject UP001 理由  # 否决（进 failure_memory 不再提）

注意：脚本只改状态，真正写进 USER profile 由会话里的 agent 用 memory(target=user)
执行——agent 人格不允许脚本直接改，措辞也需 agent 结合现有 profile 压缩（有字数预算）。
"""
from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state


def find(pid):
    for p in state.load().get("preferences", []):
        if p.get("id") == pid:
            return p
    return None


def cmd_list():
    pend = [p for p in state.load().get("preferences", []) if p.get("status") == "pending"]
    if not pend:
        print("偏好队列空。"); return
    for p in pend:
        print(f"{p['id']} [{p['category']}] {p['title']}")
        print(f"   规则: {p['rule'][:100]}")
        print()


def _approve(p):
    p["status"] = "approved"
    p["resolved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"✅ {p['id']} 已批准：{p['title']}")
    print(f"   待 agent 写入 USER profile → {p['rule'][:80]}…")


def cmd_approve(pid):
    d = state.load()
    p = next((x for x in d.get("preferences", []) if x["id"] == pid), None)
    if not p:
        print(f"找不到 {pid}", file=sys.stderr); sys.exit(1)
    if p["status"] != "pending":
        print(f"{pid} 状态={p['status']}"); return
    _approve(p)
    state.save(d)


def cmd_approve_all():
    d = state.load()
    n = 0
    for p in d.get("preferences", []):
        if p.get("status") == "pending":
            _approve(p); n += 1
    state.save(d)
    print(f"\n共批准 {n} 条，待 agent 写入 USER profile")


def cmd_reject(pid, reason=""):
    d = state.load()
    p = next((x for x in d.get("preferences", []) if x["id"] == pid), None)
    if not p:
        print(f"找不到 {pid}", file=sys.stderr); sys.exit(1)
    p["status"] = "rejected"
    p["resolved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    p["reject_reason"] = reason
    state.save(d)
    print(f"❌ {pid} 已否决：{p['title']}（{reason}）")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        cmd_list(); sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "approve" and len(sys.argv) >= 3:
        cmd_approve(sys.argv[2])
    elif cmd == "approve-all":
        cmd_approve_all()
    elif cmd == "reject" and len(sys.argv) >= 3:
        cmd_reject(sys.argv[2], " ".join(sys.argv[3:]))
    else:
        print(__doc__)
