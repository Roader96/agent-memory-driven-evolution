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
    _V = os.environ.get("HERMES_VAULT", os.path.expanduser("~/HermesMemory"))
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


def load_all_failures() -> List[Dict]:
    """
    扫三个数据源，返回统一 entries 列表：
    [{"id","text","source","count","first_seen","last_seen"}]
    """
    entries: List[Dict] = []

    # 来源 1：errors.jsonl
    if os.path.exists(ERRORS_JSONL):
        with open(ERRORS_JSONL, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                date = _parse_date(obj.get("date"))
                entries.append({
                    "id": "errors.jsonl:%d" % i,
                    "text": obj.get("what") or obj.get("key") or "",
                    "source": obj.get("source") or obj.get("job") or "errors.jsonl",
                    "count": int(obj.get("count") or 1),
                    "first_seen": date,
                    "last_seen": date,
                })

    # 来源 2：incidents/*.md 标题行
    # 注意：incidents 混合了真失败记录和普通归档（会话总结/架构图），
    # 只有文件名含失败信号词的才算失败条目，否则污染簇（"会话总结-xxx"曾变 C3 假痛点）
    FAIL_HINT = re.compile(r"失败|报错|翻车|断网|断连|挂掉|踩坑|反思|教训|没粘住|错误|修复|排查|兜底|fail|error|fix", re.I)
    SKIP_HINT = re.compile(r"会话总结|架构图|方案|总结-")
    for path in sorted(glob.glob(INCIDENTS_GLOB)):
        base = os.path.basename(path)
        if SKIP_HINT.search(base) or not FAIL_HINT.search(base):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                title = ""
                date = None
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("#"):
                        title = line.lstrip("#").strip()
                    else:
                        title = line
                    date = _parse_date(line)
                    break
                if not date:
                    m = re.search(r"\d{4}-\d{2}-\d{2}", os.path.basename(path))
                    date = m.group(0) if m else None
                if title:
                    entries.append({
                        "id": "incident:" + os.path.basename(path),
                        "text": title,
                        "source": "incident",
                        "count": 1,
                        "first_seen": date,
                        "last_seen": date,
                    })
        except OSError:
            continue

    # 来源 3：LEARNINGS-REVIEW.md（可选，容错）
    if os.path.exists(LEARNINGS_REVIEW):
        try:
            with open(LEARNINGS_REVIEW, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    # 取列表项作为高频错误条目
                    if re.match(r"^[-*•]\s+", line) or re.match(r"^\d+[.、)]\s+", line):
                        text = re.sub(r"^([-*•]|\d+[.、)])\s+", "", line).strip()
                        # 去掉 markdown 加粗标记
                        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
                        if len(text) < 5:
                            continue
                        cnt = 1
                        m = re.search(r"[（(]\s*(\d+)\s*次?[)）]", text)
                        if m:
                            cnt = int(m.group(1))
                            text = text[:m.start()].strip()
                        entries.append({
                            "id": "learnings:%d" % i,
                            "text": text,
                            "source": "learnings-review",
                            "count": cnt,
                            "first_seen": None,
                            "last_seen": None,
                        })
        except OSError:
            pass

    # 统一出口过滤：任何来源（含 LEARNINGS-REVIEW wiki-link）带普通归档
    # 标记的条目都剔除——wiki-link 会把 incidents 里已过滤的普通归档
    # 经 LEARNINGS-REVIEW 重新带回簇（A6 断言发现的绕过路径）。
    ARCHIVE_NOISE = re.compile(r"会话总结|架构图|^.*-方案[-|】]|总结[-—]")
    entries = [e for e in entries if not ARCHIVE_NOISE.search(e.get("text", ""))]
    return entries


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
