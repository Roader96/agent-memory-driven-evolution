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

_LINE = re.compile(r"^[ \t]*-[ \t]*\[([ x\-X])\][ \t]*((?:P|UP)\d+)\b([^\n]*)", re.M)


def _run(cmd: list[str]) -> tuple[bool, str]:
    p = subprocess.run(["/usr/bin/python3", *cmd], capture_output=True, text=True, timeout=120)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode == 0, out[-200:]


def _proposal_lines(d=None) -> list[str]:
    d = state.load() if d is None else d
    out = []
    pend = [p for p in d["proposals"] if p["status"] == "pending"]
    approved = [p for p in d["proposals"] if p["status"] == "approved"]
    if pend:
        out.append("## 待审批提案（[x]=批准 · [-]=驳回）")
        out.append("")
        for p in pend:
            out.append(f"- [ ] {p['id']} | {p['kind']} | {p['target']} | {(p.get('reason') or '')[:80]} <!-- uid:{p.get('uid','')} -->")
        out.append("")
    if approved:
        out.append("## 已批准待执行（执行完成后把对应行改成 [x] = 标记 done 并挂 7 天回测）")
        out.append("")
        for p in approved:
            out.append(f"- [ ] {p['id']} | {p['kind']} | {p['target']} | 执行完成后勾选 <!-- uid:{p.get('uid','')} -->")
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


def _checked(text, d):
    valid, stale = {}, []
    for m in _LINE.finditer(text):
        mark, pid, tail = m.groups()
        if mark.strip().lower() not in ("x", "-"):
            continue
        line = m.group(0)
        if pid.startswith("UP"):
            valid[pid] = line
            continue
        columns = tail.split("|")
        target = columns[2].strip() if len(columns) > 2 else None
        uid = re.search(r"<!-- uid:([^ >]+) -->", tail)
        try:
            p = state.unique_proposal(d, pid, target, uid.group(1) if uid else None)
            if p.get("uid") and not uid:
                raise ValueError("legacy checkbox has no immutable identity")
            section = text[:m.start()].rsplit("\n## ", 1)[-1].splitlines()[0]
            approved_section = "已批准待执行" in section
            if approved_section != (p["status"] == "approved"):
                raise ValueError("stale approval stage")
            if p["status"] not in ("pending", "approved"):
                raise ValueError("proposal already resolved")
            valid[pid] = line
        except ValueError as exc:
            stale.append(f"> {line} — {exc}")
    return valid, stale


def render():
    """Preserve matching decisions; quarantine stale decisions instead of executing them."""
    d = state.load()
    prior = APPROVALS.read_text(encoding="utf-8") if APPROVALS.exists() else ""
    expected = APPROVALS.stat().st_mtime_ns if APPROVALS.exists() else None
    checked, stale = _checked(prior, d)
    head = ["# 技能进化审批队列", "", f"> 刷新时间：{datetime.now():%Y-%m-%d %H:%M}",
            "> [x]=批准，[-]=驳回；必须保留目标和 uid。已批准区再次勾选表示确认执行完成。", ""]
    lines = head + _proposal_lines(d)
    for i, line in enumerate(lines):
        m = _LINE.match(line)
        if m and m.group(2) in checked:
            lines[i] = checked[m.group(2)]
    if stale:
        review = APPROVALS.with_name("APPROVALS.review.md")
        existing = review.read_text() if review.exists() else "# 旧勾选待人工复核（未执行）\n"
        for line in stale:
            if line not in existing:
                existing += "\n" + line + "\n"
        review.write_text(existing, encoding="utf-8")
        lines += ["", "> 有旧勾选未执行，见 APPROVALS.review.md。"]
    APPROVALS.parent.mkdir(parents=True, exist_ok=True)
    if expected is not None and APPROVALS.stat().st_mtime_ns != expected:
        raise RuntimeError("Approval file changed during rendering; refusing overwrite")
    tmp = APPROVALS.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(APPROVALS)
    return APPROVALS


def process():
    if not APPROVALS.exists():
        render()
        return 0
    text = APPROVALS.read_text(encoding="utf-8")
    d = state.load()
    checked, stale = _checked(text, d)
    actions, failures = [], len(stale)
    for pid, line in checked.items():
        m = _LINE.match(line)
        mark = m.group(1).strip().lower()
        if pid.startswith("UP"):
            cmd = [str(Path(__file__).parent / "approve_pref.py"),
                   "approve" if mark == "x" else "reject", pid]
        else:
            p = state.unique_proposal(d, pid)
            command = "approve" if mark == "x" else "reject"
            cmd = [str(Path(__file__).parent / "approve.py"), command, pid,
                   "--expected-target", p["target"]]
            if p.get("uid"):
                cmd += ["--uid", p["uid"]]
            if mark == "x" and p["status"] == "approved":
                cmd.append("--done")
        ok, output = _run(cmd)
        failures += not ok
        actions.append(f"{pid}: {'OK' if ok else 'FAIL'} {output}")
    if actions or stale:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(f"## {datetime.now().isoformat()}\n" + "\n".join(actions + stale) + "\n")
    render()
    for line in actions:
        print(line)
    if failures:
        raise ValueError(f"{failures} stale or failed approval actions; " + "; ".join(actions + stale)[-800:])
    print(f"审批拾取完成：{len(actions)} 条动作")
    return len(actions)


if __name__ == "__main__":
    try:
        cmd = sys.argv[1] if len(sys.argv) > 1 else "process"
        if cmd == "render":
            print(render())
        elif cmd == "process":
            process()
        else:
            raise ValueError("Unknown command")
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        sys.exit(2)
