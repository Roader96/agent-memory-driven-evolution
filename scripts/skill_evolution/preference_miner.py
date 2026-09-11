#!/usr/bin/env python3
"""preference_miner.py — 正向成长核心（PRELUDE CIPHER + emulo 本地化）

主航道：不是砍技能，是让 agent 越来越懂用户。

流程：
  1. preference_signals 挖"纠正配对"（用户否定的 + 我当时做错的产出）
  2. LLM 归纳成结构化偏好候选（可观察行为，不是空话）
  3. 存 state.preference_pending，飞书让用户批准
  4. 批准后由 agent 用 memory(target=user) 写进 USER profile（每轮系统提示注入，立刻生效）
  5. 7 天回测：同类纠正信号是否减少（学没学会）

归纳铁律（借 PRELUDE）：
- 只从真实纠正配对归纳，禁止编造
- 偏好必须可执行（"交付前确认格式"），不许写空话（"要细心"）
- 每条带证据（用户原话 + 会话）
- 和已批准偏好去重
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state
import preference_signals as psig

HOME = Path.home()
HERMES_BIN = str(HOME / ".hermes/hermes-agent/venv/bin/hermes")
SRC = "preference-miner"
MARK = "[preference-miner]"

PROMPT = """{mark} 你是 Hermes 的偏好归纳器（PRELUDE/CIPHER 机制）。
下面是用户（用户）近 90 天对 agent 的真实"纠正配对"：用户否定/修改了 agent 的产出。
你的任务：从这些 edit 信号里归纳出用户的【隐性工作偏好】——他从没明确写进规则、但反复要求的东西。

已有偏好（去重用，不要重复提）：
{existing}

硬规则：
1. 只从给出的真实配对归纳，禁止编造没有证据的偏好
2. 每条必须是【可执行行为】：好例子"交付 HTML 类任务时先确认渲染目标（markdown vs 文件）"；坏例子"要细心""注意格式"（空话，agent 无法执行）
3. 归类到：delivery(交付物)/communication(沟通方式)/authority(权限边界)/workstyle(工作方式)/quality(质量标准)
4. 单次偶发不提（至少语义上像稳定倾向）；同一类纠正合并成一条，列全部证据
5. 宁缺毋滥，最多 6 条。没有值得归纳的就输出 0 条
6. 每条必须能回答"agent 下次具体该怎么做"

输出严格格式（纯 markdown，不要代码块包裹）：
## 偏好候选（共 N 条）

### [U1] category: 一句话偏好标题
**规则**：agent 下次遇到 X 场景时，具体怎么做（可执行）
**证据**：用户原话「…」；涉及若干次纠正
**为什么**：从用户的纠正推断出的底层偏好

数据：
{data}
"""


def call_llm(prompt, timeout=300):
    qf = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    qf.write(prompt); qf.close()
    env = {**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
    try:
        p = subprocess.run(
            [HERMES_BIN, "chat", "-Q", "--oneshot", "--cli",
             "--source", SRC, "--query-file", qf.name],
            capture_output=True, text=True, timeout=timeout, env=env, cwd="/tmp")
        out = "\n".join(ln for ln in p.stdout.splitlines()
                        if not ln.strip().startswith(("session_id:", "Warning:"))).strip()
        return p.returncode, out, p.stderr
    except Exception as e:
        return -1, "", str(e)
    finally:
        try: os.unlink(qf.name)
        except OSError: pass
        try:
            subprocess.run([HERMES_BIN, "sessions", "archive", "--source", SRC, "--yes"],
                           capture_output=True, timeout=60)
        except Exception:
            pass


def parse_candidates(out):
    cands = []
    for m in re.finditer(
            r"###\s*\[U\d+\]\s*(\w+)\s*[:：]\s*(.+?)\n\*\*规则\*\*[：:]\s*(.+?)\n"
            r"\*\*证据\*\*[：:]\s*(.+?)\n\*\*为什么\*\*[：:]\s*(.+?)(?=\n###|\Z)",
            out, re.S):
        cat, title, rule, evidence, why = (re.sub(r"\s+", " ", x).strip() for x in m.groups())
        cands.append({"category": cat, "title": title[:80], "rule": rule[:240],
                      "evidence": evidence[:240], "why": why[:200]})
    return cands


def existing_prefs():
    """已批准 + 待批的偏好标题，喂 LLM 去重。"""
    doc = state.load()
    out = []
    for p in doc.get("preferences", []):
        if p.get("status") in ("approved", "pending"):
            out.append(f"- [{p.get('category')}] {p.get('title')}")
    return "\n".join(out) or "（暂无）"


def mine():
    sig = psig.collect(90)
    corr = sig["corrections"]
    if not corr:
        print("无纠正信号，跳过归纳")
        return []
    data = []
    for i, c in enumerate(corr, 1):
        data.append(json.dumps({
            "id": f"E{i}",
            "用户否定": c["text"],
            "agent当时产出": c.get("prior_assistant", "")[:200],
            "场景": c.get("title", ""),
        }, ensure_ascii=False))
    prompt = PROMPT.format(mark=MARK, existing=existing_prefs(),
                           data="\n".join(data)[:9000])
    rc, out, err = call_llm(prompt)
    if rc != 0 or len(out) < 50:
        print(f"⚠️ 偏好归纳 LLM 失败: rc={rc} {err[-150:]}", file=sys.stderr)
        return []
    cands = parse_candidates(out)
    doc = state.load()
    pend = doc.setdefault("preferences", [])
    have_titles = {p.get("title") for p in pend}
    added = 0
    week_later = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    for c in cands:
        if c["title"] in have_titles:
            continue
        c.update({"id": f"UP{len(pend)+1:03d}", "status": "pending",
                  "proposed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                  "follow_up_after": week_later})
        pend.append(c); added += 1
    state.save(doc)
    print(f"偏好候选 {len(cands)} 条，新增 {added} 条入队")
    return [c for c in cands]


if __name__ == "__main__":
    mine()
