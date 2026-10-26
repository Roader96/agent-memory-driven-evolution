#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
canonicalize.py — 错误/学习条目的模式归一化模块

借鉴 Ratchet pattern canonicalisation：同一个 bug 的两种描述合并成一条教训，
计数累加，防止"一个错存两条"。

数据源（只读）：
- ~/HermesMemory/.checkpoints/errors.jsonl
- ~/HermesMemory/incidents/*.md
- ~/HermesMemory/LEARNINGS-REVIEW.md（可选，容错）

纯标准库，Python 3.9 兼容。
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from typing import List, Dict, Optional, Any

# ---------- 数据路径（单一来源：HERMES_VAULT 可覆盖，曾写死 ~/HermesMemory） ----------
from pathlib import Path as _Path
import sys as _sys
_sys.path.insert(0, str(_Path(__file__).parent))
try:
    import paths as _paths
    _V = str(_paths.VAULT)
except ImportError:
    _V = str(_paths.VAULT)
ERRORS_JSONL = os.path.join(_V, ".checkpoints/errors.jsonl")
INCIDENTS_GLOB = os.path.join(_V, "incidents/*.md")
LEARNINGS_REVIEW = os.path.join(_V, "LEARNINGS-REVIEW.md")


# ---------- 归一化规则（顺序敏感：先长后短） ----------
_RULES = [
    # 引号内长串（错误消息、参数值等）
    (re.compile(r'"[^"]{8,}"'), '"STR"'),
    (re.compile(r"'[^']{8,}'"), "'STR'"),
    (re.compile(r"`[^`]{4,}`"), "`CODE`"),
    # 绝对路径（Unix / Windows）
    (re.compile(r"(?:/[\w.\-一-鿿]+){2,}/?"), "/PATH"),
    (re.compile(r"[A-Za-z]:\\(?:[\w.\-]+\\)+[\w.\-]*"), "WINPATH"),
    # ISO 日期时间
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"), "DATETIME"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "DATE"),
    (re.compile(r"\d{2}:\d{2}(:\d{2})?"), "TIME"),
    # 十六进制（hash、token、内存地址）
    (re.compile(r"0x[0-9a-fA-F]+"), "HEX"),
    (re.compile(r"\b[0-9a-fA-F]{8,}\b"), "HEX"),
    # UUID
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "UUID"),
    # PID / 端口号 / IP
    (re.compile(r"\b(?:pid|PID)\s*[=:]?\s*\d+"), "pid=NUM"),
    (re.compile(r"\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b"), "IP"),
    (re.compile(r":\d{2,5}\b"), ":PORT"),
    # 版本号
        (re.compile(r"\bv?\d+(\.\d+){1,3}\b"), "VER"),
        # 剩余长数字（ID、行号、耗时等）
        (re.compile(r"\b\d{2,}\b"), "NUM"),
    ]

# 需要剔除的噪声词（对聚类无区分度）
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
    "at", "for", "with", "by", "and", "or", "not", "no", "it", "this",
    "that", "be", "been", "has", "have", "had", "from", "as", "but",
    "的", "了", "在", "是", "和", "与", "或", "被", "把", "让", "使",
    "一个", "没有", "不", "未", "也", "都", "就", "时", "中",
}


def normalize_key(text: str) -> str:
    """
    把任意错误/教训文本归一成稳定指纹。

    处理：去时间戳、去路径、去具体数字/ID/引号内容 → 小写 → 压空格 →
    提取核心 token（去停用词，保留动词/名词/中文词）→ 取前 8 个核心 token
    拼接成 key。同构错误（只是时间/路径/ID 不同）会得到相同 key。
    """
    if not text:
        return ""
    s = text.strip()
    # Obsidian wiki-link [[路径|别名]] → 取别名（链接文本），让链接与纯标题能聚到一起
    s = re.sub(r"\[\[[^\]|]*\|([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    # 逐条应用占位符替换规则
    for pat, repl in _RULES:
        s = pat.sub(repl, s)
    # 小写 + 压空格
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    # 提取 token：英文单词(含数字)/ 中文连续段 / 占位符
    # 数字不单独成 token（本来就是归一目标），但"字母+数字"单词保留（node18、line1 有区分度）
    tokens = re.findall(r"[a-z_][a-z0-9_]*|[一-鿿]+|[A-Z]{2,}", s)
    # 去掉停用词和单字符噪声（保留有信息量的词）
    core = []
    for t in tokens:
        tl = t.lower()
        if tl in _STOPWORDS:
            continue
        if len(tl) < 2 and not re.match(r"[一-鿿]", t):
            continue
        core.append(tl)
    # 取前 8 个核心 token，保证 key 稳定且不太长
    return " ".join(core[:8])


def _parse_date(s: Any) -> Optional[str]:
    """容错解析日期字符串，返回 YYYY-MM-DD 或 None。"""
    if not s:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(s))
    return m.group(0) if m else None


def cluster(entries: List[Dict]) -> List[Dict]:
    """
    把同 normalize_key 的条目合并。

    entries: [{"id","text","source","count","first_seen","last_seen"}]
    返回: [{"cluster_key","title","count","sources","first_seen","last_seen","examples"}]
    按 count 降序。
    """
    groups: Dict[str, Dict] = {}
    for e in entries:
        text = e.get("text") or ""
        key = normalize_key(text)
        if not key:
            # 空文本用 id 兜底，避免全部揉成一团
            key = "raw:" + hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
        g = groups.get(key)
        cnt = int(e.get("count") or 1)
        fs = e.get("first_seen")
        ls = e.get("last_seen")
        if g is None:
            g = {
                "cluster_key": key,
                "title": text[:120],
                "count": 0,
                "sources": set(),
                "first_seen": fs,
                "last_seen": ls,
                "examples": [],
            }
            groups[key] = g
        g["count"] += cnt
        src = e.get("source")
        if src:
            g["sources"].add(src)
        # 维护最早/最晚时间
        if fs and (g["first_seen"] is None or fs < g["first_seen"]):
            g["first_seen"] = fs
        if ls and (g["last_seen"] is None or ls > g["last_seen"]):
            g["last_seen"] = ls
        # 保留前 2 条原始文本做示例
        if text and len(g["examples"]) < 2 and text not in g["examples"]:
            g["examples"].append(text[:200])
        # title 取较短的那条（更概括）
        if text and len(text) < len(g["title"]):
            g["title"] = text[:120]
    out = list(groups.values())
    out.sort(key=lambda x: -x["count"])
    return out


GENERIC_HEADINGS = {"摘要", "summary", "事件经过", "修复", "相关链接", "背景", "问题", "解决方案"}
FAIL_HINT = re.compile(r"失败|报错|翻车|断网|断连|挂掉|踩坑|反思|教训|没粘住|错误|修复|排查|兜底|fail|error|fix|fatal|exception|timeout|interrupted", re.I)
BANNER = re.compile(r"^(?:Hermes Agent\s+v?\d|[-=─━]{3,}|upstream\s+[a-f0-9]+)", re.I)


def incident_title(path):
    lines = _Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            if title.lower() not in GENERIC_HEADINGS:
                return title
    # Generic section headings cannot identify an event. The dated filename
    # identifies the actual incident even when every note starts with 摘要.
    return re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", _Path(path).stem)


def load_all_failures(days=None):
    """Read authoritative events only; LEARNINGS-REVIEW is a derived index.

    A review listing an incident is not a second occurrence of that incident.
    Exact duplicate event records are deduplicated; unknown dates are excluded
    from explicitly bounded review windows, not silently counted as recent.
    """
    entries, seen = [], set()
    if os.path.exists(ERRORS_JSONL):
        for i, line in enumerate(_Path(ERRORS_JSONL).read_text(encoding="utf-8").splitlines()):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            text = obj.get("what") or obj.get("key") or ""
            if not isinstance(text, str) or BANNER.search(text.strip()) or not FAIL_HINT.search(text):
                continue
            identity = str(obj.get("event_id") or obj.get("run_id") or json.dumps(obj, sort_keys=True))
            if identity in seen:
                continue
            seen.add(identity)
            date = _parse_date(obj.get("last_seen") or obj.get("date") or obj.get("timestamp"))
            entries.append({"id": f"errors.jsonl:{i}", "text": text,
                "source": obj.get("source") or obj.get("job") or "errors.jsonl",
                "count": max(1, int(obj.get("count") or 1)),
                "first_seen": _parse_date(obj.get("first_seen")) or date, "last_seen": date})
    for path in sorted(glob.glob(INCIDENTS_GLOB)):
        name = os.path.basename(path)
        if re.search(r"会话总结|架构图|方案|总结-", name) or not FAIL_HINT.search(name):
            continue
        try:
            title = incident_title(path)
        except OSError:
            continue
        if title.lower() in GENERIC_HEADINGS or BANNER.search(title):
            continue
        date = _parse_date(name)
        entries.append({"id": "incident:" + name, "text": title, "source": "incident",
                        "count": 1, "first_seen": date, "last_seen": date})
    if days is not None:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        entries = [e for e in entries if e.get("last_seen") and e["last_seen"] >= cutoff]
    return [e for e in entries if not re.search(r"会话总结|架构图|总结[-—]", e.get("text", ""))]


def _json_default(o: Any) -> Any:
    """让 set 可以被 json.dumps 序列化。"""
    if isinstance(o, set):
        return sorted(o)
    return str(o)


if __name__ == "__main__":
    # 调试入口：加载全部失败条目并聚类，打印 JSON
    all_entries = load_all_failures()
    clusters = cluster(all_entries)
    print(json.dumps({
        "总条目数": len(all_entries),
        "聚类数": len(clusters),
        "clusters": clusters,
    }, ensure_ascii=False, indent=2, default=_json_default))
