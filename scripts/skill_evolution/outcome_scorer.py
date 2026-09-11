#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
outcome_scorer.py — Hermes 会话任务结果打标器（Ratchet grader 角色，粗信号）。

⚠️ 重要定位声明（librarian 必读）：
    本模块输出的是**弱启发式信号**，不是精确指标。
    - 它只看会话"最后一条实质 assistant 消息"的文本关键词，
      完全不理解任务是否真的完成、用户是否满意。
    - 常见误判场景：
        * assistant 收尾说"已完成 X，但 Y 无法做到" → 关键词冲突，标 'uncertain' 或误判。
        * 会话只是闲聊/问天气，没有"任务"概念 → 无收尾信号 → 'uncertain'。
        * 用户中途关掉会话但任务其实做完了 → 'uncertain'。
        * assistant 写"已修复"但其实没修对（需 librarian/人复核）。
    - 因此每条输出都带 confidence，librarian 应只把
      outcome='fail' 且 confidence 为 high/medium 的会话列入深挖队列，
      低置信度样本仅作统计噪音参考，不可单独触发反思。

用途：
    1) 全局健康度：score_window(days=7) 给出当周成功率粗估计。
    2) 失败召回：failed_sessions 列表喂给 librarian 做反思入口。

数据源：~/.hermes/state.db（只读打开，URI mode=ro）。
纯标准库，Python 3.9 兼容（不用 match / | 类型联合 / walrus 之外的 3.10+ 语法）。
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
import agent_adapter as A
DB_PATH = str(A.state_db_path())

# ---- 关键词表（启发式核心，中文任务收尾习惯用语） ----
# 局限性：这些词是从真实 Hermes 会话收尾风格里人工归纳的，
# 覆盖率有限，新口吻/英文收尾/emoji 变体都会漏判。
SUCCESS_KEYWORDS = [
    "✅", "完成", "搞定", "已修复", "解决了", "全部完成",
    "done", "fixed", "resolved",
]
FAIL_KEYWORDS = [
    "失败", "没搞定", "无法", "放弃", "中断", "interrupted",
    "超时", "卡住", "timed out", "failed", "give up",
]

# 自动化来源，不代表真实用户任务，直接跳过
SKIP_SOURCES = ("cron", "daily-polish", "skill-evolution-librarian")

# ---- 用户反应信号（比 assistant 自述更可信：自我表扬偏差不存在于此）----
# 只匹配"纯反应"短语——它们几乎不可能是新任务指令：
#   "谢谢"/"👍" → 满意；  "不对"/"怎么又" → 失败
# 像"都补"这种短指令不匹配任何反应词，自然落回 assistant 信号。
USER_APPROVE = ["谢谢", "辛苦", "👍", "❤️", "完美", "搞定了", "可以了", "太好了",
                "nice", "thanks", "great", "满意", "对了！", "漂亮"]
USER_COMPLAIN = ["不对", "没用", "怎么又", "还是有问题", "错了", "重新来", "什么鬼",
                 "搞砸", "又崩", "不行啊", "别忽悠", "假成功", "wrong", "still broken"]


def _user_reaction(conn, session_id, after_ts):
    """取 assistant 收尾之后的用户短消息（<60字），匹配纯反应词。
    返回 'approve' / 'complain' / None。"""
    rows = conn.execute(
        """SELECT content, timestamp FROM messages
           WHERE session_id = ? AND role = 'user' AND timestamp >= ?
           ORDER BY timestamp ASC LIMIT 5""",
        (session_id, after_ts),
    ).fetchall()
    for content, _ts in rows:
        text = (content or "").strip()
        if not text or len(text) > 60:
            continue
        low = text.lower()
        if any(k in text for k in USER_COMPLAIN) or any(k in low for k in ("wrong", "still broken")):
            return "complain"
        if any(k in text for k in USER_APPROVE) or any(k in low for k in ("nice", "thanks", "great")):
            return "approve"
    return None

# "实质 assistant 消息"的最小长度阈值。
# 太短的收尾（如"好的"）不含有效信号，视作无收尾。
MIN_CLOSING_LEN = 10


def _open_ro_conn(db_path=DB_PATH):
    """以只读模式打开 state.db，避免误写。"""
    uri = "file:{}?mode=ro".format(db_path)
    return sqlite3.connect(uri, uri=True)


def _get_last_assistant_text(conn, session_id):
    """
    取会话最后一条实质 assistant 消息文本。

    优先取 content；若 content 为空但 role='hermes_reasoning'（或 reasoning_content
    有值）则退回取 reasoning_content —— 某些推理模型的收尾结论可能只写在 reasoning 里。
    局限：reasoning 常是过程性思考而非收尾陈述，用它打分会略微偏向"过程描述"。
    """
    cur = conn.execute(
        """
        SELECT role, content, reasoning_content, timestamp
        FROM messages
        WHERE session_id = ? AND role IN ('assistant', 'hermes_reasoning')
        ORDER BY timestamp DESC
        LIMIT 30
        """,
        (session_id,),
    )
    for role, content, reasoning_content, _ts in cur.fetchall():
        text = (content or "").strip()
        # [System: ...] 是运行时注入（模型切换等），不是任务收尾，跳过
        if text.startswith("[System:") or text.startswith("[OUT-OF-BAND"):
            continue
        if len(text) >= MIN_CLOSING_LEN:
            return text, _ts
        if not text and reasoning_content:
            rt = reasoning_content.strip()
            if rt.startswith("[System:"):
                continue
            if len(rt) >= MIN_CLOSING_LEN:
                return rt, _ts
    return None, None


def _classify_text(text):
    """
    按关键词对文本打标。返回 (outcome, hit_success, hit_fail)。

    规则：
    - 强成功标记（✅/全部完成/搞定/已修复）全文扫——它们常出现在长总结
      显眼位置（标题/开头），只扫收尾会漏。
    - 失败关键词只扫最后 500 字符——"失败/中断"在长文里常是中性叙述
      （如"假失败 stamp"、"rc=2 失败原因分析"），全文扫必误报。
    - 强成功全文命中 + 失败词仅收尾命中 → success（medium 置信）：
      典型形态"修复完成 ✅……附：失败原因分析"。
    """
    tail = text[-500:]
    tail_lower = tail.lower()
    full_lower = text.lower()
    strong_success = [kw for kw in ("✅", "全部完成", "搞定", "已修复")
                      if kw.lower() in full_lower]
    hits_s = [kw for kw in SUCCESS_KEYWORDS if kw.lower() in tail_lower]
    hits_f = [kw for kw in FAIL_KEYWORDS if kw.lower() in tail_lower]
    if strong_success and hits_f and not hits_s:
        return "success_strong", strong_success, hits_f
    if hits_s and not hits_f:
        return "success", hits_s, hits_f
    if hits_f and not hits_s:
        return "fail", hits_s, hits_f
    if hits_s and hits_f:
        # 关键词冲突：典型如"X 已完成但 Y 失败了"。无法判断整体成败。
        return "conflict", hits_s, hits_f
    return "none", hits_s, hits_f


def score_session(conn, session_id):
    """
    给单个会话打结果标签。

    返回 dict：
        outcome     : 'success' | 'fail' | 'uncertain'
        confidence  : 'high' | 'medium' | 'low'
        evidence    : 判定依据简述（命中关键词 / 无收尾等），供 librarian 复核
    """
    text, ts = _get_last_assistant_text(conn, session_id)

    if text is None:
        # 会话中断、无实质收尾（可能用户直接关了，或全是工具调用）
        return {
            "outcome": "uncertain",
            "confidence": "low",
            "evidence": "无实质 assistant 收尾消息（可能中断或纯工具会话）",
        }

    # 用户反应信号优先于 assistant 自述（无自我表扬偏差）
    reaction = _user_reaction(conn, session_id, ts or 0)
    if reaction == "complain":
        return {
            "outcome": "fail",
            "confidence": "high",
            "evidence": "用户收尾后表达不满（complain 反应词命中）——用户骂了，不管 assistant 说什么",
        }

    label, hits_s, hits_f = _classify_text(text)

    if reaction == "approve":
        # 用户认可 + assistant 没报失败 → 成功高置信
        if label in ("success", "success_strong", "none", "conflict"):
            return {
                "outcome": "success",
                "confidence": "high",
                "evidence": "用户收尾后表达认可（approve 反应词命中），assistant 判定={}".format(label),
            }
        # 用户认可但 assistant 报失败 → 矛盾，中置信 uncertain 待复核
        return {
            "outcome": "uncertain",
            "confidence": "medium",
            "evidence": "用户认可但 assistant 收尾命中失败词 {}（矛盾，待复核）".format(hits_f),
        }

    if label == "success_strong":
        # 强成功标记全文命中 + 失败词仅收尾出现 → 成功（中置信，供复核）
        return {
            "outcome": "success",
            "confidence": "medium",
            "evidence": "全文命中强成功标记 {}，失败词 {} 仅收尾出现（疑为中性叙述）；片段：…{}".format(
                hits_s, hits_f, text[-80:]
            ),
        }
    if label == "success":
        # 收尾明确含成功词且无失败词冲突 → 强信号
        return {
            "outcome": "success",
            "confidence": "high",
            "evidence": "收尾命中成功关键词 {}；片段：…{}".format(hits_s, text[-80:]),
        }
    if label == "fail":
        return {
            "outcome": "fail",
            "confidence": "high",
            "evidence": "收尾命中失败关键词 {}；片段：…{}".format(hits_f, text[-80:]),
        }
    if label == "conflict":
        # 关键词冲突 → 中置信度 uncertain，librarian 可选深挖
        return {
            "outcome": "uncertain",
            "confidence": "medium",
            "evidence": "收尾同时命中成功 {} 与失败 {} 关键词（部分完成？）；片段：…{}".format(
                hits_s, hits_f, text[-80:]
            ),
        }
    # 有收尾但无任何关键词 → 低置信度 uncertain（可能是闲聊/中性总结）
    return {
        "outcome": "uncertain",
        "confidence": "low",
        "evidence": "有收尾消息但无成败关键词；片段：…{}".format(text[-80:]),
    }


def score_window(days=7, db_path=DB_PATH):
    """
    统计最近 days 天窗口内全部非自动化会话的结果分布。

    返回 dict：
        success / fail / uncertain : 计数
        success_rate               : success / (success+fail)，uncertain 不计入分母
                                     （因为 uncertain 不是任务结果，计入会污染比率；
                                     这也是局限：大量中断会话被悄悄排除，比率偏乐观）
        failed_sessions            : [{id, title, evidence}]，供 librarian 反思入口
        confidence_note            : 固定警示语
    """
    since = time.time() - days * 86400
    conn = _open_ro_conn(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, title, message_count FROM sessions
            WHERE started_at >= ?
              AND source NOT IN ({})
              AND (parent_session_id IS NULL OR parent_session_id = '')
              AND COALESCE(message_count, 0) >= 4
            ORDER BY started_at DESC
            """.format(",".join("?" * len(SKIP_SOURCES))),
            (since,) + SKIP_SOURCES,
        ).fetchall()
        # 注：不过滤 archived/hidden/ended_at——
        # desktop 长寿命会话永不写 ended_at（gateway 保活），archived 只是 UI 隐藏，
        # 都是真实工作历史，都应参与评分。
        # message_count>=4 过滤掉"回复一个字"类连通性测试噪声。

        counts = {"success": 0, "fail": 0, "uncertain": 0}
        failed = []
        for sid, title, _mc in rows:
            r = score_session(conn, sid)
            counts[r["outcome"]] += 1
            if r["outcome"] == "fail":
                failed.append(
                    {
                        "id": sid,
                        "title": title,
                        "confidence": r["confidence"],
                        "evidence": r["evidence"],
                    }
                )
    finally:
        conn.close()

    decided = counts["success"] + counts["fail"]
    rate = (counts["success"] / decided) if decided else None
    return {
        "success": counts["success"],
        "fail": counts["fail"],
        "uncertain": counts["uncertain"],
        "success_rate": round(rate, 4) if rate is not None else None,
        "failed_sessions": failed,
        "confidence_note": (
            "弱启发式信号，非精确指标；success_rate 分母不含 uncertain，"
            "中断/闲聊会话被排除，比率系统性偏乐观。librarian 请按 confidence 决定是否深挖。"
        ),
    }


if __name__ == "__main__":
    result = score_window(days=7)
    print(json.dumps(result, ensure_ascii=False, indent=2))
