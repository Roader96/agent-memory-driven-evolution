#!/usr/bin/env python3
"""metrics.py — 技能贡献度度量（自进化的证据地基）

从 agent 数据源采集（经 agent_adapter 抽象）：
  - Hermes：state.db（SQLite 强制采集）
  - 其他 agent：通用文件系统降级
每个技能统计：
  load_sessions  多少个会话加载过它（skill_view）
  fail_after     加载后同会话出现工具失败的次数（粗粒度疗效信号）
  edits          被 skill_manage 修订次数
  last_used      最近加载时间
外加：年龄、体积、是否 bundled、是否已禁用。

只读取，不改动任何东西。输出 JSON 到 stdout（供 curator/librarian 消费）。
"""
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
import agent_adapter as A

HOME = Path.home()
AGENT = A.detect()
STATE = A.state_db_path()
SKILLS_DIR = A._hermes_home() / "skills"
CONFIG = A._hermes_home() / "config.yaml"

# 工具失败信号（tool 结果消息）
FAIL_RE = re.compile(r'"success"\s*:\s*false|exit_code["\s:]+-?[1-9]|Traceback \(most recent', re.I)


def disabled_names() -> set:
    try:
        import yaml
        d = yaml.safe_load(CONFIG.read_text()) or {}
        v = (d.get("skills") or {}).get("disabled") or []
        if isinstance(v, str):
            v = [v]
        return {str(x).strip() for x in v}
    except Exception:
        return set()


def extract_skill_views(conn):
    """返回 [(session_id, msg_id, skill_name, ts, view_ok)]。
    view_ok = skill_view 这条工具调用自身返回是否成功（紧接的 tool 结果）。
    不把同会话其他工具的失败算到技能头上（那会冤枉高频技能）。"""
    rows = conn.execute("""
        SELECT session_id, id, tool_calls, timestamp FROM messages
        WHERE role='assistant' AND tool_calls IS NOT NULL
          AND tool_calls LIKE '%skill_view%'
    """).fetchall()
    out = []
    for sid, mid, tc, ts in rows:
        try:
            calls = json.loads(tc)
        except Exception:
            continue
        for c in calls:
            fn = (c or {}).get("function") or {}
            if fn.get("name") != "skill_view":
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                continue
            name = args.get("name")
            if name:
                # 分类限定名 category:name / plugin:name → 取裸名
                name = str(name).strip().split(":")[-1]
                # tool_call_id 用于精确关联工具结果（并行调用时不再按位置猜）
                call_id = (c or {}).get("id") or (c or {}).get("call_id")
                out.append((sid, mid, name, ts, call_id))
    return out


def view_outcomes(conn, views):
    """判定每次 skill_view 自身成败：按 tool_call_id 精确关联工具结果。
    返回 {(sid,mid): ok}。
    降级：tool_call_id 查不到（旧数据）时按 id 顺序推断，并计入 approx 数。"""
    ok_map = {}
    approx = 0
    for sid, mid, name, ts, call_id in views:
        r = None
        if call_id:
            r = conn.execute(
                "SELECT content FROM messages WHERE role='tool' AND tool_call_id=?",
                (call_id,)).fetchone()
        if r is None:
            # 降级：旧数据无 tool_call_id → 按位置推断（近似，计入 approx）
            r = conn.execute("""
                SELECT content FROM messages
                WHERE session_id=? AND role='tool' AND id > ?
                  AND content IS NOT NULL
                ORDER BY id LIMIT 1""", (sid, mid)).fetchone()
            approx += 1
        ok = True
        if r and r[0]:
            c = r[0]
            if FAIL_RE.search(c) or (c.lstrip().startswith("[skill_view]") and "not found" in c.lower()):
                ok = False
        ok_map[(sid, mid)] = ok
    if approx:
        print(f"ℹ️ view_outcomes: {approx}/{len(views)} 条按位置近似关联（旧数据无 tool_call_id）",
              file=sys.stderr)
    return ok_map


def session_outcomes(conn):
    """session_id -> 'success'|'fail'|'uncertain'。
    任务级弱信号：会话最后一条实质 assistant 消息的收尾语气。
    不是'中间有没有报错'（那会冤枉技能），而是任务最终收没收尾。"""
    res = {}
    rows = conn.execute("""
        SELECT session_id, content FROM messages
        WHERE role='assistant' AND active=1 AND content IS NOT NULL
          AND length(trim(content))>20
        ORDER BY session_id, id
    """).fetchall()
    last = {}
    for sid, c in rows:
        last[sid] = c
    succ = ("✅", "完成", "搞定", "已修复", "解决了", "成功", "全部完成", "已完成", "落地")
    fail = ("失败", "没搞定", "无法", "放弃", "报错", "中断", "interrupted",
            "超时", "timed out", "未完成", "卡住", "翻车")
    for sid, c in last.items():
        tail = c[-400:]
        if any(k in tail for k in succ):
            res[sid] = "success"
        elif any(k.lower() in tail.lower() for k in fail):
            res[sid] = "fail"
        else:
            res[sid] = "uncertain"
    return res


def skill_facts():
    # 经适配器连接：Hermes 读 state.db，其他 agent 自动降级
    conn = A.connect_state_db()
    if conn is None:
        # 降级：无 Hermes 库 — 通用文件系统统计
        return A.generic_skill_facts()
    conn.row_factory = sqlite3.Row
    views = extract_skill_views(conn)
    outcomes = view_outcomes(conn, views)

    # name -> 聚合。只统计能测准的信号：
    #   load_sessions 需求度（多少会话加载）
    #   self_errors   skill_view 自身报错（技能缺失/损坏）
    #   reload_sessions 同会话加载≥2次（粗信号：一次没解决/被反复翻，谨慎解读）
    # 不伪造"照做后成功率"——没有任务评分器，质量疗效标 N/A。
    agg = {}
    per_session = {}
    for sid, mid, name, ts, _call_id in views:
        a = agg.setdefault(name, {
            "sessions": set(), "self_errors": 0, "last_used": 0,
        })
        a["sessions"].add(sid)
        a["last_used"] = max(a["last_used"], ts or 0)
        if outcomes.get((sid, mid)) is False:
            a["self_errors"] += 1
        per_session.setdefault((name, sid), 0)
        per_session[(name, sid)] += 1

    reloads = {}
    for (name, sid), n in per_session.items():
        if n >= 2:
            reloads[name] = reloads.get(name, 0) + 1

    # skill_manage 修订次数
    edits = {}
    for tc, in conn.execute("""SELECT tool_calls FROM messages
            WHERE role='assistant' AND tool_calls LIKE '%skill_manage%'"""):
        try:
            calls = json.loads(tc)
        except Exception:
            continue
        for c in calls:
            fn = (c or {}).get("function") or {}
            if fn.get("name") != "skill_manage":
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                continue
            for op in (args.get("operations") or []):
                nm = op.get("name")
                if nm:
                    edits[nm] = edits.get(nm, 0) + 1
    conn.close()

    disabled = disabled_names()
    now = datetime.now().timestamp()

    def base(name, installed, size=0, age=None):
        return {
            "name": name, "installed": installed, "disabled": name in disabled,
            "size_bytes": size, "age_days": age,
            "load_sessions": 0, "self_errors": 0, "reload_sessions": 0,
            "usage_quality": "measured",  # Hermes 模式：来自 state.db 真实会话数据
            "edits": 0, "last_used_days": None, "quality": "N/A（无任务评分器）",
        }

    result = {}
    if SKILLS_DIR.exists():
        for skill_md in SKILLS_DIR.rglob("SKILL.md"):
            if ".archive" in skill_md.parts:
                continue
            # hermes 按 frontmatter name 解析技能名，不是目录名！
            # （目录 my-image-gen 的 name 可以是 image-gen；
            #   目录名大小写与 frontmatter 不一致也正常）
            name = skill_md.parent.name
            try:
                head = skill_md.read_text(encoding="utf-8", errors="replace")[:2000]
                m = re.search(r'^name:\s*["\']?([^\n"\']+?)["\']?\s*$', head, re.M)
                if m and m.group(1).strip():
                    name = m.group(1).strip()
            except OSError:
                pass
            st = skill_md.stat()
            result[name] = base(name, True, st.st_size,
                                int((now - st.st_mtime) / 86400))

    for name, a in agg.items():
        # 大小写不敏感匹配（frontmatter "My-Skill" vs 调用 "my-skill"）
        canonical = next((k for k in result if k.lower() == name.lower()), None)
        if canonical is None:
            canonical = name
            result[canonical] = base(canonical, False)
        r = result[canonical]
        r["load_sessions"] = len(a["sessions"])
        r["self_errors"] = a["self_errors"]
        r["reload_sessions"] = reloads.get(name, 0) + reloads.get(canonical, 0)
        r["last_used_days"] = int((now - a["last_used"]) / 86400) if a["last_used"] else None
    for name, n in edits.items():
        if name in result:
            result[name]["edits"] = n

    # 冷库（永久记忆）技能激活痕迹：近 90 天 daily/projects/preferences/incidents
    # 的 md 里出现技能名。自然语言会和命令名撞（wrangler CLI≠wrangler 技能），
    # 所以只作"退役豁免/人工复核"信号，不当精确用量。
    vault_mentions = {}
    try:
        import paths as _paths
        vault = _paths.VAULT  # 单一来源（曾写死 HOME/"HermesMemory"）
        cutoff = datetime.now().timestamp() - 90 * 86400
        name_lower = {x["name"].lower(): x["name"] for x in result.values() if x["installed"]}
        for md in vault.rglob("*.md"):
            if "skill-evolution" in md.parts or md.name.startswith("_"):
                continue
            try:
                if md.stat().st_mtime < cutoff:
                    continue
                txt = md.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for nl, canonical in name_lower.items():
                if len(nl) < 6:
                    continue
                if re.search(r"(?<![a-z0-9-])" + re.escape(nl) + r"(?![a-z0-9-])", txt):
                    vault_mentions[canonical] = vault_mentions.get(canonical, 0) + 1
    except Exception:
        pass

    result_list = list(result.values())
    for x in result_list:
        x["vault_mentions_90d"] = vault_mentions.get(x["name"], 0)
    return result_list


if __name__ == "__main__":
    facts = skill_facts()
    facts.sort(key=lambda x: (-x["load_sessions"], x["name"]))
    json.dump({"generated": datetime.now().isoformat(timespec="seconds"),
               "skills": facts}, sys.stdout, ensure_ascii=False, indent=1)
    print()
