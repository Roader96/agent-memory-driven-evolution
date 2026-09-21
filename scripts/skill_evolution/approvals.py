#!/usr/bin/env python3
"""approvals.py — 不依赖飞书/agent 在线的本地审批流（Obsidian 勾选制）

文件：HERMES_VAULT/skill-evolution/APPROVALS.md

约定：
  - [ ] PID   待处理
  - [x] PID   批准（待审批提案 → approve；已批准待执行 → --done 标完成并挂回测）
  - [-] PID   驳回（仅 pending 可驳回）
  - UP 开头   偏好候选（approve_pref 通道）

节奏：
  - run_weekly 每周日生成/刷新
  - daily_watchdog 每天 23:55 拾取执行（本脚本 process）
  - 也可以随时手动跑：python3 approvals.py process
  - 或直接在对话里说「批准 P122」，由 agent 调 approve.py（同一个执行器）
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state
import paths

VAULT = paths.VAULT
APPROVALS = VAULT / "skill-evolution" / "APPROVALS.md"
LOG = VAULT / "skill-evolution" / "APPROVALS.log"

_LINE = re.compile(r"^\s*-\s*\[([ x\-X])\]\s*((?:P|UP)\d+)\b", re.M)


def _run(cmd: list[str]) -> tuple[bool, str]:
    p = subprocess.run(["/usr/bin/python3", *cmd], capture_output=True, text=True, timeout=120)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode == 0, out[-200:]


def _proposal_lines() -> list[str]:
    d = state.load()
    out = []
    pend = [p for p in d["proposals"] if p["status"] == "pending"]
    approved = [p for p in d["proposals"] if p["status"] == "approved"]
    if pend:
        out.append("## 待审批提案（[x]=批准 · [-]=驳回）")
        out.append("")
        for p in pend:
            out.append(f"- [ ] {p['id']} | {p['kind']} | {p['target']} | {(p.get('reason') or '')[:80]}")
        out.append("")
    if approved:
        out.append("## 已批准待执行（执行完成后把对应行改成 [x] = 标记 done 并挂 7 天回测）")
        out.append("")
        for p in approved:
            out.append(f"- [ ] {p['id']} | {p['kind']} | {p['target']} | 执行完成后勾选")
        out.append("")
    pref = [p for p in d.get("preferences", []) if p.get("status") == "pending"]
    if pref:
        out.append("## 待批偏好候选（[x]=批准学会 · [-]=否决不再提）")
        out.append("")
        for p in pref:
            out.append(f"- [ ] {p['id']} | {p.get('title','')} | {(p.get('rule') or '')[:80]}")
        out.append("")
    if not out:
        out = ["## 队列为空", "", "当前没有待审批提案或偏好。", ""]
    return out


def render() -> Path:
    """按当前 state 重新生成 APPROVALS.md（幂等，会覆盖旧勾选——处理完才会重渲染）。"""
    head = [
        "# 技能进化审批队列",
        "",
        f"> 刷新时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "> 规则：把 `[ ]` 改成 `[x]` = 批准；改成 `[-]` = 驳回（仅待审批可驳）。",
        "> 每晚 23:55 watchdog 自动拾取执行；retire 类批准即自动软禁用，",
        "> enhance/fix 类批准后进入「已批准待执行」，执行完再勾一次 = done + 挂回测。",
        "",
    ]
    APPROVALS.parent.mkdir(parents=True, exist_ok=True)
    APPROVALS.write_text("\n".join(head + _proposal_lines()), encoding="utf-8")
    return APPROVALS


def process() -> int:
    """拾取 APPROVALS.md 里的勾选并执行，然后重渲染。返回处理条数。"""
    if not APPROVALS.exists():
        render()
        return 0
    text = APPROVALS.read_text(encoding="utf-8")
    actions: list[str] = []
    # 分区上下文：approved 区的 [x] 是 --done，待审批区的 [x] 是 approve
    section = ""
    for m in _LINE.finditer(text):
        mark, pid = m.group(1).strip().lower(), m.group(2)
        line_start = text.rfind("\n", 0, m.start()) + 1
        in_approved = "已批准待执行" in text[:line_start].rsplit("\n## ", 1)[-1]
        if mark == "x":
            if pid.startswith("UP"):
                ok, out = _run([str(Path(__file__).parent / "approve_pref.py"), "approve", pid])
                actions.append(f"approve {pid}: {'OK' if ok else 'FAIL ' + out}")
            elif in_approved:
                ok, out = _run([str(Path(__file__).parent / "approve.py"), "approve", pid, "--done"])
                actions.append(f"done {pid}: {'OK' if ok else 'FAIL ' + out}")
            else:
                ok, out = _run([str(Path(__file__).parent / "approve.py"), "approve", pid])
                actions.append(f"approve {pid}: {'OK' if ok else 'FAIL ' + out}")
        elif mark == "-":
            if pid.startswith("UP"):
                ok, out = _run([str(Path(__file__).parent / "approve_pref.py"), "reject", pid, "vault-驳回"])
            else:
                ok, out = _run([str(Path(__file__).parent / "approve.py"), "reject", pid, "vault-驳回"])
            actions.append(f"reject {pid}: {'OK' if ok else 'FAIL ' + out}")
    if actions:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"## {datetime.now().strftime('%Y-%m-%d %H:%M')}\n" +
                     "\n".join(f"- {a}" for a in actions) + "\n")
    render()
    for a in actions:
        print(f"  {a}")
    print(f"审批拾取完成：{len(actions)} 条动作" if actions else "审批拾取完成：无新勾选")
    return len(actions)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "process"
    if cmd == "render":
        print(f"已生成 {render()}")
        sys.exit(0)
    sys.exit(0 if process() is not None else 1)
