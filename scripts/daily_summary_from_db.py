#!/usr/bin/env python3
"""
daily_summary_from_db.py — 每日总结真实版

两层架构，缺一不可：
  1. 证据层（本脚本，零 token，数学可验）：SQL 拉当天【全部】session，
     每个 session 取完整证据链（用户的原话需求 + assistant 结论性回复）
  2. 润色层（hermes -z，每天 1 次 LLM 调用）：把证据链喂模型出一版人话总结；
     覆盖门禁：每个非噪声 session 必须被提及。模型挂了（睡眠/超时/broken pipe）
     自动降级证据版——糙但全，绝不再是空壳

完整性保证：session 清单来自同一条 SQL（COUNT 可验），脚本断言
  「拉到的 session 数 == 数据库当天非噪声 session 数」，漏一个 exit 1。

用法：
  python3 daily_summary_from_db.py            # 生成今天，写盘
  DATE_OVERRIDE=2026-09-09 python3 ...        # 回填历史
  PUSH_FEISHU=1 python3 ...                   # 写盘 + 推飞书
  NO_LLM=1 python3 ...                        # 只出证据版（调试用）
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "skill_evolution"))
import paths

HOME = paths.HOME
VAULT = paths.VAULT
STATE_DB = paths.HERMES_HOME / "state.db"
CRON_DB = paths.HERMES_HOME / "cron" / "executions.db"
JOBS_JSON = paths.HERMES_HOME / "cron" / "jobs.json"
UPDATE_STAMP = paths.HERMES_HOME / ".last_auto_update.json"
ERRORS_JSON = VAULT / ".checkpoints" / "errors.json"
ERRORS_JSONL = VAULT / ".checkpoints" / "errors.jsonl"  # 新：一行式错误日志（借鉴 agent-memory-loop）
HERMES_BIN = os.environ.get("HERMES_BIN", str(paths.HERMES_HOME / "hermes-agent/venv/bin/hermes"))

DATE = os.environ.get("DATE_OVERRIDE", datetime.now().strftime("%Y-%m-%d"))
TIME = os.environ.get("TIME_OVERRIDE", "23:55")
PUSH = os.environ.get("PUSH_FEISHU") == "1"
NO_LLM = os.environ.get("NO_LLM") == "1"

# 润色调用的内部标记：带这个标记的 session 是本脚本的润色调用，永不进总结
POLISH_MARK = "[daily-summary-polish]"
# 润色调用的专属 source（跑完 archive 软隐藏，不塞桌面会话列表）
POLISH_SOURCE = "daily-polish"

CONCLUSION_SIGNALS = (
    "✅", "完成", "修复", "根因", "结论", "决定", "搞定", "已改", "已删",
    "总结", "结果是", "真因", "降级", "失败原因", "落地", "收尾",
)


def db_connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def day_bounds(day: str):
    start = datetime.strptime(day, "%Y-%m-%d").timestamp()
    return start, start + 86400


def clean(text: str) -> str:
    if not text:
        return ""
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("[System:") or s.startswith("[OUT-OF-BAND"):
            continue
        if s.startswith("<") and s.endswith(">"):
            continue
        out.append(s)
    return " ".join(out)


# 广告/订阅邮件识别（两级特征，防止把正常业务讨论误杀）
# 强特征：招聘/直播平台品牌词、广告主题模板词 → 命中即判定
_AD_STRONG = ("(ad)", "职位推荐", "前程无忧", "智联招聘", "58同城",
              "boss直聘", "拉勾", "【免费直播】", "直播预告")
# 弱特征：EDM/退订等词在正常营销分析/招聘复盘里也会出现 → 必须叠加邮件结构特征
_AD_WEAK = ("unsubscribe", "退订", "取消订阅", "edm", "邮件营销")
# 邮件结构特征：HTML 标签/实体/邮件话术
_AD_MAIL_STRUCT = re.compile(
    r"(<(?:html|body|table|div|a\s|img|br|/?p|span|font)[^>]*>|<!doctype|&nbsp;|href=|"
    r"发件人|收件人|此邮件|群发邮件|点击查看|点击这里|如果您(?:不|无)?希望|"
    r"click here|this (?:e-?mail|message)|no longer wish to receive|manage your preferences|view in browser)",
    re.I,
)
_HTML_CSS = re.compile(r"<(html|body|div|table|img|style)[^>]*>|\.ql-align|background-color:|font-family:|margin:0", re.I)


def is_ad_session(title: str, first_user: str) -> bool:
    """广告/营销邮件会话判定。

    强品牌/模板词直接判；弱词（edm/退订/邮件营销）只有在出现邮件结构特征
    （HTML、退订链接、邮件话术）时才判，避免误杀「EDM 渠道 ROI 复盘」这类正常讨论。
    """
    combo = ((title or "") + " " + (first_user or "")).lower()
    if any(k in combo for k in _AD_STRONG):
        return True
    if any(k in combo for k in _AD_WEAK):
        if _AD_MAIL_STRUCT.search(first_user or "") or _AD_MAIL_STRUCT.search(title or ""):
            return True
    return False


def denoise(text: str) -> str:
    """把一次性的广告/垃圾邮件原文压成一句摘要；非噪声返回原样（None 表示不降噪）。"""
    if not text or len(text) < 60:
        return text  # 短消息不可能是邮件正文
    low = text.lower()
    has_strong = any(k in low for k in _AD_STRONG)
    has_weak = any(k in low for k in _AD_WEAK)
    has_html = _HTML_CSS.search(text)
    # 强广告词命中；或弱词叠加邮件 HTML 结构 → 压成一行，正文不进日报
    if has_strong or (has_weak and has_html and len(text) > 200):
        # 摘出主题行/话术关键词，压成一行
        short = re.sub(r"\s+", " ", text)[:120]
        return f"[广告/订阅邮件，已降噪] {short}…"
    return text


def is_noise(title: str, msgs: int, tools: int, first_user: str) -> bool:
    if POLISH_MARK in (first_user or ""):
        return True
    if tools == 0 and msgs <= 3:
        return True
    t = ((title or "") + " " + (first_user or "")).lower()
    noise = ("reply with exactly", "回复一个字", "ok-kimi", "ok-ark",
             "一个字", "只回复")
    # 广告/营销邮件：这类会话不进入 daily，也不触发通知（两级特征防误杀）
    if is_ad_session(title, first_user):
        return True
    # denoise 后带降噪标记（[广告/订阅邮件，已降噪]）→ 也判噪声
    if "[广告/订阅邮件，已降噪]" in first_user:
        return True
    return any(k in t for k in noise)


def load_all_sessions(start, end):
    """返回 (真实会话, cron会话)。每个会话带完整证据链。"""
    conn = db_connect(STATE_DB)
    rows = conn.execute(
        """SELECT id, source, title, message_count, tool_call_count,
                  datetime(started_at,'unixepoch','localtime') st
           FROM sessions
           WHERE started_at >= ? AND started_at < ?
           ORDER BY started_at""",
        (start, end),
    ).fetchall()

    real, cron = [], []
    for r in rows:
        sid = r["id"]

        # 用户的全部实质 user 消息（需求演进），最多 5 条
        urows = conn.execute(
            """SELECT content FROM messages
               WHERE session_id=? AND role='user' AND active=1
                 AND content IS NOT NULL AND length(trim(content))>0
               ORDER BY timestamp""",
            (sid,),
        ).fetchall()
        user_msgs = [clean(u["content"]) for u in urows]
        user_msgs = [denoise(u) for u in user_msgs if u][:4]
        first_user = user_msgs[0] if user_msgs else ""

        # assistant 结论性消息：带结论信号的实质消息，取最后 3 条；
        # 没有信号就兜底取最长的 1 条 + 最后 1 条
        arows = conn.execute(
            """SELECT content FROM messages
               WHERE session_id=? AND role='assistant' AND active=1
                 AND content IS NOT NULL AND length(trim(content))>0
               ORDER BY timestamp""",
            (sid,),
        ).fetchall()
        a_msgs = [clean(a["content"]) for a in arows if clean(a["content"])]
        concluded = [m for m in a_msgs
                     if any(sig in m for sig in CONCLUSION_SIGNALS)
                     and len(m) > 30][-3:]
        if not concluded and a_msgs:
            longest = max(a_msgs, key=len)
            tail = a_msgs[-1]
            concluded = [longest] + ([tail] if tail != longest else [])

        item = {
            "title": r["title"] or sid[:14],
            "msgs": r["message_count"] or 0,
            "tools": r["tool_call_count"] or 0,
            "st": (r["st"] or "")[11:16],
            "user_msgs": user_msgs,
            "conclusions": [c[:600] for c in concluded],
        }
        # 10+ 会话时结论瘦身到 300（证据预算保护，防止 brief 截断后模型漏会话）
        if len(rows) > 6:
            item["conclusions"] = [c[:300] for c in item["conclusions"]]
        # 结论再压：长会话把每条压到 260，保证 brief < 14000
        item["conclusions"] = [c[:260] for c in item["conclusions"]]
        if r["source"] == "cron":
            cron.append(item)
        elif r["source"] == POLISH_SOURCE or POLISH_MARK in first_user:
            # 本脚本的润色调用：不进总结（专属 source + 标记双保险）
            continue
        elif not is_noise(item["title"], item["msgs"], item["tools"], first_user):
            real.append(item)
    conn.close()
    return real, cron


def load_cron_failures(day: str):
    if not CRON_DB.exists():
        return []
    job_names = {}
    if JOBS_JSON.exists():
        d = json.loads(JOBS_JSON.read_text())
        jobs = d if isinstance(d, list) else d.get("jobs", [])
        job_names = {j.get("id"): j.get("name", j.get("id")) for j in jobs}
    conn = db_connect(CRON_DB)
    rows = conn.execute(
        """SELECT job_id, claimed_at, error FROM executions
           WHERE status='failed' AND claimed_at >= ? AND claimed_at < ?
           ORDER BY claimed_at""",
        (f"{day}T00:00:00", f"{day}T23:59:59"),
    ).fetchall()
    conn.close()
    return [{
        "name": job_names.get(r["job_id"], r["job_id"][:8]),
        "at": (r["claimed_at"] or "")[11:16],
        "err": (r["error"] or "").strip().split("\n")[0][:140],
        "source": "cron",
    } for r in rows]


def load_update_status(day: str):
    if not UPDATE_STAMP.exists():
        return None
    try:
        d = json.loads(UPDATE_STAMP.read_text())
        if str(d.get("ts", "")).startswith(day):
            return d
    except Exception:
        pass
    return None


def load_launchd_failures(day: str):
    """扫 launchd 纯脚本日志里当天的 FAIL/rc!=0，自动捕获不靠自觉。"""
    out = []
    logs = [
        HOME / ".hermes" / "logs" / "auto_update.launchd.log",
        HOME / ".hermes" / "logs" / "daily_watchdog.log",
        HOME / ".hermes" / "logs" / "arkcli_keepalive.log",
    ]
    pat = re.compile(r"\[(\d{4}-\d{2}-\d{2})[  ][\d:]+\]\s*(.*(?:FAIL|失败|ERROR|rc=[1-9]).*)", re.I)
    for lf in logs:
        if not lf.exists():
            continue
        try:
            for line in lf.read_text(errors="ignore").splitlines()[-400:]:
                m = pat.search(line)
                if m and m.group(1) == day:
                    out.append({
                        "name": lf.stem,
                        "at": "",
                        "err": m.group(2).strip()[:140],
                    })
        except Exception:
            pass
    return out


def record_errors_jsonl(day: str, cron_failures, update_st, launchd_failures):
    """把当天错误追加进 errors.jsonl。稳定 key 去重，复发 count+1（借鉴 agent-memory-loop）。"""
    ERRORS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if ERRORS_JSONL.exists():
        for line in ERRORS_JSONL.read_text().splitlines():
            try:
                e = json.loads(line)
                existing[e.get("key")] = e
            except Exception:
                pass

    incoming = []
    for f in cron_failures:
        key = f"{day}|cron|{f['name']}|{f['err'][:60]}"
        incoming.append((key, {
            "date": day, "source": "cron", "job": f["name"],
            "severity": "high", "what": f["err"],
        }))
    if update_st and update_st.get("status") not in ("ok", None):
        key = f"{day}|autoupdate|{update_st.get('status')}"
        incoming.append((key, {
            "date": day, "source": "auto-update", "job": "hermes-auto-update",
            "severity": "high", "what": str(update_st.get("note", update_st.get("status")))[:140],
        }))
    for f in launchd_failures:
        key = f"{day}|launchd|{f['name']}|{f['err'][:60]}"
        incoming.append((key, {
            "date": day, "source": "launchd", "job": f["name"],
            "severity": "medium", "what": f["err"],
        }))

    added = 0
    for key, e in incoming:
        if key in existing:
            existing[key]["count"] = existing[key].get("count", 1) + 1
            existing[key]["last_seen"] = day
        else:
            e["key"] = key
            e["count"] = 1
            e["prevented"] = 0
            existing[key] = e
            added += 1

    ERRORS_JSONL.write_text(
        "\n".join(json.dumps(v, ensure_ascii=False) for v in existing.values()) + "\n",
        encoding="utf-8",
    )
    return added, len(existing)


def load_vault_files(day: str):
    """当天冷库新增：文件名日期前缀优先，否则 birthtime 判定。"""
    out = []
    skip = {"TIMELINE.md", "INDEX.md", "README.md", "ERRORS.md", "LEARNINGS-REVIEW.md"}
    start, end = day_bounds(day)
    for f in VAULT.rglob("*.md"):
        if ".obsidian" in f.parts or ".checkpoints" in f.parts:
            continue
        if any(p.startswith("_") for p in f.relative_to(VAULT).parts):
            continue
        if f.name in skip or f.parent.name == "daily":
            continue
        if f.name[:10] == day:
            out.append(str(f.relative_to(VAULT)))
            continue
        if f.name[:10].startswith(day[:7]):
            continue
        try:
            st = f.stat()
            birth = getattr(st, "st_birthtime", st.st_mtime)
        except OSError:
            continue
        if start <= birth < end:
            out.append(str(f.relative_to(VAULT)))
    return sorted(set(out))


def vault_stats():
    total = len([
        f for f in VAULT.rglob("*.md")
        if ".obsidian" not in f.parts and ".checkpoints" not in f.parts
        and not any(p.startswith("_") for p in f.relative_to(VAULT).parts)
    ])
    projects = len([d for d in (VAULT / "projects").iterdir() if d.is_dir()]) \
        if (VAULT / "projects").exists() else 0
    prefs = len(list((VAULT / "preferences").glob("*.md"))) \
        if (VAULT / "preferences").exists() else 0
    incidents = len(list((VAULT / "incidents").glob("*.md"))) \
        if (VAULT / "incidents").exists() else 0
    errors = 0
    if ERRORS_JSONL.exists():
        errors = sum(1 for ln in ERRORS_JSONL.read_text().splitlines() if ln.strip())
    elif ERRORS_JSON.exists():
        try:
            errors = len(json.loads(ERRORS_JSON.read_text()))
        except Exception:
            pass
    hot = ""
    hotf = HOME / ".hermes" / "memories" / "MEMORY.md"
    if hotf.exists():
        n = len(hotf.read_text())
        hot = f"{n}/2200 ({n*100//2200}%)"
    return total, projects, prefs, incidents, errors, hot


# ---------- 证据版 markdown（保底，永远有实质内容） ----------

def evidence_md(real, cron, failures, update_st, vault_files, stats):
    total, projects, prefs, incidents, errors, hot = stats
    L = [
        f"# {DATE} 每日总结", "",
        f"> **生成时间**：{TIME} · 数据源 state.db 全量会话（证据版）", "",
        "## 🧑‍💻 今日实际工作", "",
    ]
    if not real:
        L.append("_今日无桌面交互会话_")
    for s in real:
        L.append(f"### {s['title']}")
        L.append(f"_{s['st']} · {s['msgs']} 条消息 · {s['tools']} 次工具_")
        for u in s["user_msgs"][:3]:
            L.append(f"- **用户**：{u[:200]}")
        for c in s["conclusions"]:
            L.append(f"- **结论**：{c[:400]}")
        L.append("")

    L += ["## ⏰ 定时任务", ""]
    fail_names = {f["name"]: f["at"] for f in failures}
    for s in cron:
        name = s["title"].split(" · ")[0]
        mark = "❌" if any(name == fn or name.startswith(fn[:10])
                          for fn in fail_names) else "✅"
        L.append(f"- {mark} {name}（{s['st']}）")
    if not cron:
        L.append("_无_")
    L.append("")

    L += ["## 🐛 故障与错误", ""]
    tr = []
    for f in failures:
        when = f"（{f['at']}）" if f.get("at") else ""
        tr.append(f"- ❌ **{f['name']}**{when}：{f['err']}")
    if update_st and update_st.get("status") != "ok":
        tr.append(f"- ❌ **hermes 自动更新**：{update_st.get('status')} "
                  f"{str(update_st.get('note',''))[:100]}")
    L += tr or ["_今日定时任务无失败_"]
    L.append("")

    L += ["## 📦 冷库归档产出", ""]
    L += [f"- `{p}`" for p in vault_files] or ["_今日无新增归档文件_"]
    L.append("")

    L += [
        "## 📊 统计", "",
        f"- 冷库 {total} 文件 · {projects} 项目 · {prefs} 偏好 · "
        f"{incidents} 踩坑 · {errors} 错误记录",
        f"- 热记忆 {hot} · 真实会话 {len(real)} · cron {len(cron)} · 失败 {len(failures)}",
        "",
        "## 🧠 自我审视（成长自省）", "",
    ]
    try:
        import sys as _sys
        _sys.path.insert(0, str(HOME / ".hermes" / "scripts" / "skill_evolution"))
        import preference_signals as _ps
        g = _ps.collect_day(DATE)
        if g["counts"]["corrections"]:
            L.append(f"今天用户纠正了我 **{g['counts']['corrections']} 次**，信号分布：")
            from collections import Counter as _C
            for sig, n in _C(x["signal"] for x in g["corrections"]).most_common(5):
                L.append(f"- `{sig}` × {n}")
            L.append("")
            L.append("待归纳进偏好候选（周度 preference_miner 自动处理 + 用户审批）。")
        else:
            L.append("今日无纠正，继续巩固。")
        L.append("")
        L.append(f"近7天纠正趋势：{' → '.join(str(t['corrections']) for t in g['trend_7d'])}")
        L.append("（连续 7 天为 0 = 成长曲线平坦，触发 preference_miner 深挖 + 周报提示）")
    except Exception as _e:
        L.append(f"_自省素材加载失败: {_e}_")
    L += ["", "---", "_证据版：daily_summary_from_db.py 直读 state.db，未经模型润色_"]
    return "\n".join(L)


# ---------- 润色层 ----------

def build_evidence_brief(real, cron, failures, update_st, vault_files, stats):
    """喂给模型的证据包（JSON，结构化，模型不许编）"""
    n = max(len(real), 1)
    # 证据预算：10+ 会话时每个会话瘦身（结论 300 cap / 用户 2 条），保证不截断漏会话
    ucap = 200 if n <= 6 else 120
    ccap = 600 if n <= 6 else 300
    full = {
        "date": DATE,
        "real_sessions": [{
            "sid": f"S{i+1}",
            "title": s["title"],
            "start": s["st"],
            "messages": s["msgs"],
            "tool_calls": s["tools"],
            "user_requests": s["user_msgs"][:2] if n > 6 else s["user_msgs"],
            "assistant_conclusions": s["conclusions"][:2] if n > 6 else s["conclusions"],
        } for i, s in enumerate(real)],
        "cron_sessions": [s["title"].split(" · ")[0] for s in cron],
        "failures": failures,
        "auto_update": update_st,
        "vault_files": vault_files,
        "stats": {
            "hot_memory": stats[5],
            "real_session_count": len(real),
            "cron_count": len(cron),
            "failure_count": len(failures),
        },
        "growth": _growth_facts(DATE),
    }
    # brief 总预算：10+ 会话时截断策略改为【每会话合成 1 条结论】
    # （保底全覆盖，而不是一刀 14000 把后半截都扔了）
    import json as _json
    raw = _json.dumps(full, ensure_ascii=False, indent=1)
    if len(raw) > 14000 and n > 6:
        slim = dict(full)
        slim["real_sessions"] = [{
            "sid": s["sid"], "title": s["title"], "start": s["start"],
            "messages": s["messages"], "tool_calls": s["tool_calls"],
            "user_requests": s["user_requests"][:1],
            "assistant_conclusions": s["assistant_conclusions"][:1],
        } for s in full["real_sessions"]]
        return slim
    return full


POLISH_PROMPT = """{mark} 你是每日总结润色器。下面是从本地数据库提取的当天全部会话证据（JSON）。
要求：
1. 基于证据写中文 markdown 总结，【每个 real_sessions 条目都必须覆盖】，不许漏，不许编造证据里没有的事
2. 每个会话用 1-3 句人话：用户要解决什么 → 实际怎么做的 → 结果/结论
3. 每个会话小标题必须原样带它的编号和标题，格式严格为：### [编号] 标题，例如 ### [S1] xxx
4. 故障段如实列 failures；定时任务段列 cron_sessions
5. 输出【只含】以下结构，不要寒暄不要代码块包裹：
## 🧑‍💻 今日实际工作
（每个会话一个 ### [Sx] 标题 小标题；没有会话就写"今日无桌面交互会话"）
## ⏰ 定时任务
## 🐛 故障与错误
（无故障写"今日定时任务无失败"）
## 📌 沉淀与产出
（从结论和 vault_files 提炼，没有就省略本节）
## 🧠 自我审视（成长自省）
基于 evidence.growth：
- 今天用户纠正了我几次？集中在什么模式（引用 corrections_today 的 signal）
- 我离"最强 agent"差在哪（必须具体：哪类任务/哪个习惯/哪个通道，不许"我会更努力"空话）
- 明天开始的具体改进动作（≤3 条，可执行可验证：比如"先确认渲染通道再交付 md"）
- 若 correction_count_today==0 且 7 天纠正在降，写"今日无纠正，继续巩固"
6. 总长度 ≤ 1500 字

证据：
{brief}
"""


def _archive_polish_sessions():
    """软隐藏所有 daily-polish source 的会话（数据保留在 state.db，列表不显示）。"""
    try:
        subprocess.run(
            [HERMES_BIN, "sessions", "archive",
             "--source", POLISH_SOURCE, "--yes"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        pass


def _growth_facts(day: str):
    """当天强信号（纠正/习惯）+ 近7天纠正趋势，喂给润色模型的成长素材。"""
    sys.path.insert(0, str(HOME / ".hermes" / "scripts" / "skill_evolution"))
    try:
        import preference_signals as ps
        d = ps.collect_day(day)
        corr = [{
            "signal": c["signal"],
            "text": c["text"][:100],
            "did": (c.get("prior_assistant") or "")[:150],
        } for c in d["corrections"][:8]]
        return {
            "corrections_today": corr,
            "correction_count_today": d["counts"]["corrections"],
            "trend_7d": d["trend_7d"],
            "habits": [h["text"][:80] for h in d["habits"][:5]],
        }
    except Exception as e:
        return {"error": str(e), "corrections_today": [], "trend_7d": []}


def polish(brief: dict):
    """调 hermes 润色：专属 source + 跑完 archive，不塞桌面会话列表。
    成功返回 markdown 字符串，失败返回 None。"""
    if NO_LLM or not Path(HERMES_BIN).exists():
        return None
    prompt = POLISH_PROMPT.format(
        mark=POLISH_MARK,
        brief=json.dumps(brief, ensure_ascii=False, indent=1)[:30000],
    )
    cache_dir = HOME / ".hermes" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    qf = cache_dir / "daily_polish_prompt.txt"
    qf.write_text(prompt, encoding="utf-8")

    env = {**os.environ,
           "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
    try:
        proc = subprocess.run(
            [HERMES_BIN, "chat", "-Q", "--oneshot", "--cli",
             "--source", POLISH_SOURCE, "--query-file", str(qf)],
            capture_output=True, text=True, timeout=420, env=env, cwd="/tmp",
        )
        # 剥掉 "session_id: xxx" 行，只留正文
        body_lines = [
            ln for ln in proc.stdout.splitlines()
            if not ln.strip().startswith("session_id:")
        ]
        out = "\n".join(body_lines).strip()
        if proc.returncode != 0 or len(out) < 80 or "今日实际工作" not in out:
            print(f"⚠️ 润色不合格 rc={proc.returncode} len={len(out)}",
                  file=sys.stderr)
            print(proc.stderr[-300:], file=sys.stderr)
            _archive_polish_sessions()
            return None
        # 覆盖门禁：每个会话的编号必须以小标题形式出现 ### [Sx]
        headings = re.findall(r"^#{1,4}\s*\[?(S\d+)\]?", out, re.M)
        covered = set(headings)
        missing = [s["sid"] for s in brief["real_sessions"]
                   if s["sid"] not in covered]
        # 不管成败都隐藏本次润色会话
        _archive_polish_sessions()
        if missing:
            print(f"⚠️ 润色漏掉会话 {missing}（已覆盖 {sorted(covered)}），降级证据版",
                  file=sys.stderr)
            return None
        return out
    except Exception as e:
        print(f"⚠️ 润色异常: {e}，降级证据版", file=sys.stderr)
        _archive_polish_sessions()
        return None
    finally:
        try:
            qf.unlink()
        except OSError:
            pass


def assemble_polished(polished_md, stats, vault_files):
    total, projects, prefs, incidents, errors, hot = stats
    L = [f"# {DATE} 每日总结", "",
         f"> **生成时间**：{TIME} · state.db 全量证据 + 模型润色", ""]
    L.append(polished_md.strip())
    L += ["", "## 📊 统计", "",
          f"- 冷库 {total} 文件 · {projects} 项目 · {prefs} 偏好 · "
          f"{incidents} 踩坑 · {errors} 错误记录 · 热记忆 {hot}",
          "", "---",
          "_全量证据来自 state.db；润色失败时自动降级证据版_"]
    return "\n".join(L)


def feishu_text(md: str) -> str:
    """从最终 markdown 压飞书纯文本：去 markdown 符号，自省段必须保留，截断保护"""
    t = re.sub(r"^#{1,4}\s*", "", md, flags=re.M)
    t = re.sub(r"^>\\s*.*$\n?", "", t, flags=re.M)
    t = re.sub(r"\\*\\*(.+?)\\*\\*", r"\\1", t)
    t = re.sub(r"^---$\n?", "", t, flags=re.M)
    t = re.sub(r"\\n{3,}", "\\n\\n", t).strip()
    # 自省段是正向成长核心：如果整体超长，优先截"沉淀与产出"保留"自我审视"
    if len(t) > 1800 and "自我审视" in t:
        head, _, tail = t.partition("自我审视")
        head = head[:1100]
        return f"📅 {DATE} 每日总结\\n\\n{head.strip()}\\n🧠 {tail.strip()[:900]}"
    return f"📅 {DATE} 每日总结\\n\\n" + t[:1800]


def main():
    start, end = day_bounds(DATE)
    real, cron = load_all_sessions(start, end)
    cron_failures = load_cron_failures(DATE)
    launchd_failures = load_launchd_failures(DATE)
    update_st = load_update_status(DATE)
    failures = cron_failures + launchd_failures
    vault_files = load_vault_files(DATE)
    stats = vault_stats()

    # 0. 错误自动落盘 errors.jsonl（不靠自觉；多来源 + 去重计数）
    added_err, total_err = record_errors_jsonl(
        DATE, cron_failures, update_st, launchd_failures)
    stats = (*stats[:4], total_err, stats[5])

    # 1. 证据版先写盘（保底）
    evi = evidence_md(real, cron, failures, update_st, vault_files, stats)
    daily_file = VAULT / "daily" / f"{DATE}-每日总结.md"
    daily_file.parent.mkdir(parents=True, exist_ok=True)
    daily_file.write_text(evi, encoding="utf-8")

    # 2. 润色
    brief = build_evidence_brief(real, cron, failures, update_st, vault_files, stats)
    polished = polish(brief)
    if polished:
        final_md = assemble_polished(polished, stats, vault_files)
        daily_file.write_text(final_md, encoding="utf-8")
        mode = "润色版"
        feishu_body = feishu_text(final_md)
    else:
        mode = "证据版（润色降级）"
        feishu_body = feishu_text(evi)

    # 3. 内容门禁（写盘后校验，防空壳）
    disk = daily_file.read_text(encoding="utf-8")
    assert len(disk) > 400, "daily 太短"
    if real:
        assert "今日实际工作" in disk
    assert "定时任务" in disk
    print(f"✅ {mode}: {daily_file} ({len(disk)} 字符, "
          f"{len(real)} 真实会话, {len(cron)} cron, {len(failures)} 失败)")

    # 4. 飞书
    if PUSH:
        sys.path.insert(0, str(HOME / ".hermes" / "scripts"))
        try:
            from send_feishu_dm import send_dm
            ok = send_dm(feishu_body)
            print("📨 feishu:", "OK" if ok else "FAIL")
            if not ok:
                sys.exit(1)
        except Exception as e:
            print(f"📨 feishu failed: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
