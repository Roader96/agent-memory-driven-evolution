#!/usr/bin/env python3
"""Build structured, searchable Codex memory cards from local JSONL sessions.

The reader is deliberately evidence-first: assistant claims and tool-verified
signals are stored separately, and raw Codex session files are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


BJT = ZoneInfo("Asia/Shanghai")
DEFAULT_CODEX_HOME = Path.home() / ".codex"
DEFAULT_VAULT = Path(os.environ.get("HERMES_VAULT", str(Path.home() / "HermesMemory")))
MAX_EXCERPT = 640
MAX_ITEMS = 8
GENERATED_MARKER = "<!-- codex-memory: generated; do not edit this block -->"
GENERATED_END = "<!-- /codex-memory: generated -->"

NOISE_TAGS = (
    "environment_context", "app-context", "permissions instructions",
    "filesystem", "workspace_roots", "multi_agent_mode", "plugins_instructions",
    "skills_instructions", "collaboration_mode", "response-annotations",
    "image_resize_notice", "developer", "system", "model_switch", "turn_aborted",
    "task_aborted", "task_complete", "item_completed", "codex_internal_context",
)
CORRECTION_MARKERS = (
    "不是", "不对", "没解决", "没有解决", "还是不行", "还是不好", "没用",
    "卵用", "别假装", "不能算", "不够", "你说得对", "感觉还是", "做错了",
    "搞错了", "不正确", "不应该",
)
OPEN_MARKERS = (
    "未完成", "尚未完成", "还没完成", "还未完成", "待办", "仍然", "还没",
    "还未", "无法", "未验证", "不确定", "待确认", "缺少", "缺失", "风险",
    "阻塞", "卡住", "仍在失败", "仍然失败", "还在报错", "未解决",
)
DECISION_PATTERNS = (
    r"决定", r"选择", r"采用", r"改成", r"改为",
    r"最终(?:决定|选择|采用|结论)", r"结论(?:是|为)", r"保留", r"移除", r"删除",
    r"不再(?:使用|依赖|调用|运行|采用|保留)", r"只读(?:模式|探测|检查|核对)",
)
RESULT_PATTERNS = (
    r"已(?:完成|修复|验证|生成|写入|安装|部署|更新|重建|重载|切换|提交|推送)",
    r"(?:测试|门禁|仿真|用例|命令|脚本|发布|构建|检查).{0,16}(?:通过|成功|失败)",
    r"\bpass(?:ed)?\b", r"all .*passed",
    r"exit(?:ed)? (?:with )?(?:code )?0", r"returncode[\"\']?\s*[:=]\s*0",
    r"根因(?:是|为)?", r"失败(?:原因)?", r"错误(?:是|为)(?!否)", r"结论(?:是|为)",
)
FUTURE_PLAN_PATTERN = re.compile(
    r"(?:接下来|下一步|下步|随后|然后|稍后|之后会|我会|我们会|我将|我们将|"
    r"我准备|打算|计划|如果.*(?:就|会)|需要进一步|建议下一步)"
)
PROCESS_PREFIXES = (
    "我先", "我现在", "下一步", "接下来", "我会", "可以，", "可以直接",
    "好的，我", "好，我", "先检查", "正在", "我准备",
    "现在我会", "现在我在", "目前我在",
)
SYSTEM_LINE_PREFIXES = (
    "# Files mentioned", "# Response annotations", "<image", "</image",
    "Distinguish instructions", "<filesystem", "<workspace_roots", "<root>",
    "<permission_profile", "<permissions", "## My request:",
)
PATH_PATTERN = re.compile(
    r"(?:(?:/Users|/Volumes|/tmp|/var/folders|~/|\.\.?/)[^\s`<>\"'|)\],;]+|"
    r"(?:[\w./-]+/)(?:[^\s`<>\"'|)\],;]+\.(?:py|sh|md|jsonl?|db|png|html|toml|yaml|yml|log|txt)))",
    re.IGNORECASE,
)


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc).astimezone(BJT)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(BJT)
    except ValueError:
        return None


def text_from_value(value: Any) -> str:
    """Extract visible text from Codex content/output shapes."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(text_from_value(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "output", "result", "message", "value", "content", "summary"):
            if key in value:
                found = text_from_value(value[key])
                if found:
                    return found
        return ""
    return ""


def strip_tag_blocks(text: str) -> str:
    cleaned = text
    for tag in NOISE_TAGS:
        escaped = re.escape(tag)
        cleaned = re.sub(rf"<{escaped}(?:\s[^>]*)?>.*?</{escaped}\s*>", " ", cleaned, flags=re.I | re.S)
    # A few tags contain attributes or are emitted without a matching close.
    cleaned = re.sub(r"<image\b[^>]*>.*?</image\s*>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<image\b[^>]*?/?>", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"<environment_context\b[^>]*>.*?(?:</environment_context>|$)", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<app-context\b[^>]*>.*?(?:</app-context>|$)", " ", cleaned, flags=re.I | re.S)
    return cleaned


def clean_text(value: Any, role: str = "") -> str:
    text = strip_tag_blocks(text_from_value(value))
    if not text:
        return ""
    if "## My request:" in text:
        text = text.split("## My request:", 1)[1]
    text = re.sub(r"# Response annotations:.*?(?=## My request:|$)", " ", text, flags=re.I | re.S)
    text = re.sub(r"# Files mentioned by the user:.*?(?=## My request:|$)", " ", text, flags=re.I | re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"<[^>]{0,120}(?:cwd|current_date|timezone|workspace|permission)[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"/var/folders/[^\s)]+codex-clipboard-[^\s)]+", " ", text, flags=re.I)
    text = re.sub(r"\bcodex-clipboard-[\w.-]+", " ", text, flags=re.I)
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(line.startswith(prefix) for prefix in SYSTEM_LINE_PREFIXES):
            continue
        if line.startswith("<") and line.endswith(">") and any(tag in line.lower() for tag in NOISE_TAGS):
            continue
        lines.append(line)
    result = re.sub(r"\s+", " ", " ".join(lines)).strip(" -")
    if role == "user" and result.lower().startswith("my request:"):
        result = result.split(":", 1)[1].strip()
    return result


def is_meta_message(text: str) -> bool:
    lowered = text.lower().strip()
    return (
        not lowered
        or lowered.startswith("any running unified exec processes")
        or lowered.startswith("the user interrupted the previous turn")
        or lowered.startswith("computer use is not allowed")
        or lowered.startswith("script completed wall time")
    )


def safe_excerpt(text: str, limit: int = MAX_EXCERPT) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def local_day(stamp: datetime | None) -> str:
    return (stamp or datetime.now(BJT)).astimezone(BJT).date().isoformat()


def session_id_from_path(path: Path) -> str:
    match = re.search(r"(?:rollout-)?(?:\d{4}-\d{2}-\d{2}T[^-]+-)?([0-9a-f]{8}-[0-9a-f-]{27,})", path.name, re.I)
    if match:
        return match.group(1)
    return path.stem.replace("rollout-", "")


def relative_source(path: Path, codex_home: Path) -> str:
    try:
        return str(path.relative_to(codex_home))
    except ValueError:
        return str(path)


@dataclass
class Message:
    role: str
    text: str
    stamp: datetime | None
    turn_id: str
    message_id: str
    source: str
    ordinal: int
    verified: bool = False


@dataclass
class Session:
    session_id: str
    cwd: str = ""
    source: str = ""
    title: str = ""
    first_stamp: datetime | None = None
    last_stamp: datetime | None = None
    messages: list[Message] = field(default_factory=list)
    evidence: list[Message] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    source_files: set[str] = field(default_factory=set)
    seen_ids: set[str] = field(default_factory=set)
    seen_events: set[str] = field(default_factory=set)

    def add_time(self, stamp: datetime | None) -> None:
        if stamp is None:
            return
        if self.first_stamp is None or stamp < self.first_stamp:
            self.first_stamp = stamp
        if self.last_stamp is None or stamp > self.last_stamp:
            self.last_stamp = stamp


def session_title_map(index_path: Path) -> dict[str, str]:
    titles: dict[str, str] = {}
    if not index_path.exists():
        return titles
    try:
        lines = index_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return titles
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = item.get("id") or item.get("session_id") or item.get("thread_id")
        title = item.get("thread_name") or item.get("title") or item.get("name")
        if sid and title:
            titles[str(sid)] = clean_text(str(title))
    return titles


def record_text(payload: dict[str, Any]) -> str:
    for key in ("content", "output", "result", "arguments", "input", "item"):
        if key in payload:
            text = text_from_value(payload[key])
            if text:
                return text
    return ""


def is_verified_text(text: str, payload_type: str = "") -> bool:
    """Return True only for independently executable tool success evidence.

    A ``task_complete`` lifecycle event is intentionally not enough: it proves
    the turn ended, not that the assistant's claim was checked.
    """
    if payload_type not in {"function_call_output", "custom_tool_call_output"}:
        return False
    lowered = text.lower()
    denial_patterns = (
        r"not allowed", r"unavailable", r"permission denied", r"operation not permitted",
        r"traceback", r"command failed", r"exit(?:ed)? (?:with )?(?:code )?[1-9]\d*",
        r"returncode[\"\']?\s*[:=]\s*[1-9]\d*", r"不允许", r"不可用", r"没有权限",
        r"权限被拒绝", r"执行失败", r"运行失败",
    )
    if any(re.search(pattern, lowered, re.S) for pattern in denial_patterns):
        return False
    patterns = (
        r"\bpass(?:ed)?\b", r"all .*passed", r"exit(?:ed)? (?:with )?(?:code )?0",
        r"exit_code[\"\']?\s*:\s*0", r"returncode[\"\']?\s*[:=]\s*0",
        r"window:.*app:", r"ax output", r"四层.*通过",
        r"运行态仿真通过", r"门禁通过", r"全部通过", r"测试通过",
    )
    return any(re.search(pattern, lowered, re.S) for pattern in patterns)


def extract_artifacts(texts: Iterable[str]) -> list[str]:
    found: list[str] = []
    blocked_names = {".DS_Store", "COMMIT_EDITMSG", "FETCH_HEAD", "HEAD"}
    for text in texts:
        for match in PATH_PATTERN.findall(text):
            candidate = match.rstrip(".,:;，。；")
            candidate = re.sub(r":\d+$", "", candidate)
            candidate = candidate.removeprefix("./")
            if candidate.startswith("n/Users/"):
                candidate = candidate[1:]
            if "…" in candidate or candidate.endswith(("/", "\\")):
                continue
            parts = set(Path(candidate).parts)
            name = Path(candidate).name
            if ".git" in parts or name in blocked_names:
                continue
            if candidate in found or len(candidate) < 4:
                continue
            if "codex-clipboard" in candidate or candidate.startswith("http"):
                continue
            if any(token in candidate for token in ("$", "$(", "{", "}", "GATE_", "VAULT/", "GATE_LOG_DIR", "tmp}")):
                continue
            if candidate.startswith(("a/", "b/", "tmp/", "/tmp}/")):
                continue
            found.append(candidate)
    return found[:30]


def card_key(session_id: str) -> str:
    """Return a filesystem-safe, collision-resistant session directory name."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip(".-") or "session"
    if safe != session_id:
        digest = getattr(hashlib, "sha256")(session_id.encode("utf-8", "replace")).hexdigest()[:10]
        safe = f"{safe[:60]}-{digest}"
    return safe[:80]


def card_relpath(summary: dict[str, Any]) -> str:
    return f"sessions/{summary['date']}/{card_key(summary['session_id'])}"


def load_sessions(codex_home: Path, title_map: dict[str, str]) -> dict[str, Session]:
    roots = [codex_home / "archived_sessions", codex_home / "sessions"]
    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(sorted(root.rglob("*.jsonl")))
    sessions: dict[str, Session] = {}
    for path in paths:
        fallback_id = session_id_from_path(path)
        current_id = fallback_id
        try:
            stream = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            for ordinal, line in enumerate(stream):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                outer_type = str(record.get("type") or "")
                payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                stamp = parse_timestamp(record.get("timestamp") or payload.get("timestamp"))
                if outer_type == "session_meta":
                    current_id = str(payload.get("session_id") or payload.get("id") or fallback_id)
                session = sessions.setdefault(current_id, Session(current_id))
                session.source_files.add(relative_source(path, codex_home))
                session.add_time(stamp)
                if outer_type == "session_meta":
                    session.cwd = str(payload.get("cwd") or session.cwd)
                    session.source = str(payload.get("source") or session.source)
                    continue
                if outer_type == "event_msg":
                    event_type = str(payload.get("type") or "")
                    event_text = record_text(payload)
                    event_key = ":".join(
                        (
                            event_type,
                            str(payload.get("turn_id") or ""),
                            getattr(hashlib, "sha1")(event_text.encode("utf-8", "replace")).hexdigest()[:16],
                        )
                    )
                    if event_key not in session.seen_events:
                        session.seen_events.add(event_key)
                        session.event_types.append(event_type)
                    # Lifecycle events determine status only. They are not treated
                    # as independent verification of the assistant's result claim.
                    if event_text and is_verified_text(event_text, event_type):
                        evidence = Message("tool", safe_excerpt(event_text), stamp, str(payload.get("turn_id") or ""), event_key, relative_source(path, codex_home), ordinal, True)
                        session.evidence.append(evidence)
                    continue
                if outer_type != "response_item":
                    continue
                payload_type = str(payload.get("type") or "")
                message_id = str(payload.get("id") or payload.get("call_id") or f"{ordinal}:{payload_type}")
                if message_id in session.seen_ids:
                    continue
                session.seen_ids.add(message_id)
                turn_id = str((payload.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id") or payload.get("turn_id") or "")
                role = str(payload.get("role") or "")
                raw_text = record_text(payload)
                if not raw_text:
                    continue
                if role in {"user", "assistant"} and payload_type == "message":
                    visible = clean_text(raw_text, role)
                    if len(visible) >= 2 and not is_meta_message(visible):
                        session.messages.append(Message(role, safe_excerpt(visible), stamp, turn_id, message_id, relative_source(path, codex_home), ordinal))
                elif payload_type in {"custom_tool_call_output", "function_call_output"}:
                    visible = safe_excerpt(raw_text)
                    if visible:
                        session.evidence.append(Message("tool", visible, stamp, turn_id, message_id, relative_source(path, codex_home), ordinal, is_verified_text(raw_text, payload_type)))
        finally:
            stream.close()
    for session in sessions.values():
        session.title = title_map.get(session.session_id, "")
        if not session.title:
            first_user = next((item.text for item in session.messages if item.role == "user"), "")
            session.title = safe_excerpt(first_user, 90) or session.session_id[:12]
    return sessions


def split_result_sentences(text: str) -> list[str]:
    """Split visible prose into compact, result-bearing clauses."""
    chunks = re.split(r"(?<=[。！？!?；;])|\s+(?:但|不过)\b", text)
    result: list[str] = []
    for chunk in chunks:
        item = re.sub(r"\s+", " ", chunk).strip(" -•*，,、；;。.!?！？\n")
        if len(item) >= 6:
            result.append(item)
    return result


def has_result(text: str) -> bool:
    return any(re.search(pattern, text, re.I | re.S) for pattern in RESULT_PATTERNS)


def is_action_plan(text: str) -> bool:
    """Filter narrated next steps out of delivered-result sections."""
    stripped = text.strip()
    if stripped.startswith(PROCESS_PREFIXES):
        return True
    explicit_future = re.match(
        r"^(?:接下来|下一步|下步|然后|随后|稍后|先(?:只读|检查|做|跑|确认|核对)?|"
        r"现在我(?:会|在)|最后我(?:会|将)|目前我(?:会|在)|"
        r"我(?:会|将|准备|继续|再|先|打算|计划))",
        stripped,
    )
    return bool(explicit_future or (FUTURE_PLAN_PATTERN.search(stripped) and not has_result(stripped)))


def is_process_text(text: str) -> bool:
    return is_action_plan(text)


def result_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for sentence in split_result_sentences(text):
        if sentence.endswith("？") or sentence.endswith("?"):
            continue
        if is_action_plan(sentence):
            continue
        if has_result(sentence):
            sentences.append(sentence)
    return sentences


def choose_users(session: Session) -> list[str]:
    users = [item.text for item in session.messages if item.role == "user" and len(item.text) >= 2]
    unique: list[str] = []
    for item in users:
        if item not in unique:
            unique.append(item)
    return unique


def choose_claims(session: Session) -> list[str]:
    assistants = [item.text for item in session.messages if item.role == "assistant" and len(item.text) >= 8]
    scored = []
    for position, text in enumerate(assistants):
        for sentence in result_sentences(text):
            score = sum(1 for pattern in RESULT_PATTERNS if re.search(pattern, sentence, re.I | re.S))
            score += 2 + min(position, 5)
            scored.append((score, position, sentence))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen: list[str] = []
    for _, _, text in scored:
        if text not in chosen:
            chosen.append(text)
        if len(chosen) >= MAX_ITEMS:
            break
    return list(reversed(chosen))


def snippets_matching(items: Iterable[str], patterns: Iterable[str], limit: int = MAX_ITEMS) -> list[str]:
    patterns = tuple(patterns)
    result: list[str] = []
    for item in items:
        candidates = split_result_sentences(item) if len(item) > 80 else [item.strip()]
        for sentence in candidates:
            sentence = sentence.strip()
            if len(sentence) < 6 or is_action_plan(sentence):
                continue
            if re.match(r"^(?:之前|以前|原先|本来)", sentence) and not re.search(r"仍然|还没|还未|尚未|未解决", sentence):
                continue
            if any(re.search(pattern, sentence, re.I) for pattern in patterns) and sentence not in result:
                result.append(safe_excerpt(sentence, 360))
            if len(result) >= limit:
                return result
    return result


def project_name(cwd: str) -> str:
    if not cwd:
        return "未识别项目"
    name = Path(cwd).name.strip()
    return name or "未识别项目"


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\-\u4e00-\u9fff.]+", "-", value, flags=re.UNICODE).strip("-.")
    return value[:80] or "未识别项目"


def status_for(session: Session) -> str:
    ordered = session.event_types
    last_terminal = ""
    for event_type in ordered:
        if event_type in {"task_complete", "task_completed"}:
            last_terminal = "done"
        elif event_type in {"task_aborted", "turn_aborted", "error"}:
            last_terminal = "blocked"
    if ordered and ordered[-1] in {"task_complete", "task_completed"}:
        return "done"
    if ordered and ordered[-1] in {"task_aborted", "turn_aborted", "error"}:
        return "blocked"
    if any("失败" in item.text or "error" in item.text.lower() for item in session.evidence[-4:]) and last_terminal != "done":
        return "blocked"
    return "in_progress"


def build_summary(session: Session) -> dict[str, Any]:
    users = choose_users(session)
    claims = choose_claims(session)
    latest_user = users[-1] if users else ""
    goals = []
    if users:
        goals.append(users[0])
    if latest_user and latest_user != (users[0] if users else ""):
        goals.append("当前请求：" + latest_user)
    evidence = [item for item in session.evidence if item.verified]
    evidence_text = [item.text for item in evidence]
    all_text = users + claims + [item.text for item in session.evidence]
    corrections = snippets_matching(users, CORRECTION_MARKERS, 6)
    open_items = snippets_matching(list(reversed(users + claims)), OPEN_MARKERS, 8)
    decisions = snippets_matching(claims + users, DECISION_PATTERNS, 8)
    artifacts = extract_artifacts(all_text)
    return {
        "session_id": session.session_id,
        "date": local_day(session.first_stamp),
        "updated": session.last_stamp.isoformat() if session.last_stamp else "",
        "project": project_name(session.cwd),
        "cwd": session.cwd,
        "source": session.source,
        "status": status_for(session),
        "title": session.title,
        "goal": goals,
        "claims": claims[-5:],
        "verified": evidence_text[-8:],
        "open_items": open_items,
        "decisions": decisions,
        "artifacts": artifacts,
        "corrections": corrections,
        "sources": sorted(session.source_files),
        "message_count": len(session.messages),
        "evidence_count": len(evidence),
        "turn_ids": sorted({item.turn_id for item in session.messages + session.evidence if item.turn_id}),
    }


def yaml_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def card_text(summary: dict[str, Any]) -> str:
    lines = [
        "---",
        "type: codex-session",
        f"session_id: {yaml_value(summary['session_id'])}",
        f"date: {yaml_value(summary['date'])}",
        f"project: {yaml_value(summary['project'])}",
        f"status: {yaml_value(summary['status'])}",
        f"source: {yaml_value(summary['source'])}",
        f"cwd: {yaml_value(summary['cwd'])}",
        f"updated: {yaml_value(summary['updated'])}",
        "---",
        GENERATED_MARKER,
        f"# {summary['title']}",
        "",
        f"> 会话：`{summary['session_id']}` · 项目：`{summary['project']}` · 状态：`{summary['status']}`",
        "",
        "## 任务",
        "",
    ]
    lines.extend(f"- {item}" for item in (summary["goal"] or ["未提取到明确目标；请查看原始会话来源。"]))
    lines += ["", "## 决策", ""]
    lines.extend(f"- {item}" for item in (summary["decisions"] or ["未提取到明确决策。"]))
    lines += ["", "## 产出", ""]
    if summary["claims"]:
        lines.extend(f"- **助手声称**：{item}" for item in summary["claims"])
    else:
        lines.append("- 未提取到明确产出声明。")
    if summary["artifacts"]:
        lines.append("")
        lines.append("产出/涉及路径：")
        lines.extend(f"- `{item}`" for item in summary["artifacts"])
    lines += ["", "## 验证证据", ""]
    if summary["verified"]:
        lines.extend(f"- **工具/运行态已验证**：{item}" for item in summary["verified"])
    else:
        lines.append("- 没有找到可独立核验的工具输出；以上产出仅标为助手声称。")
    lines += ["", "## 待办/风险", ""]
    lines.extend(f"- {item}" for item in (summary["open_items"] or ["未提取到显式待办；仍需结合状态和证据判断是否可交付。"]))
    lines += ["", "## 用户纠正", ""]
    lines.extend(f"- {item}" for item in (summary["corrections"] or ["本会话未提取到用户纠正。"]))
    lines += ["", "## 来源", ""]
    lines.extend(f"- `{item}`" for item in summary["sources"])
    if summary["turn_ids"]:
        lines.append(f"- turn_id：`{', '.join(summary['turn_ids'][:12])}`")
    lines += ["", "---", "原始 JSONL 只读保留在 `~/.codex/sessions/` 或 `~/.codex/archived_sessions/`。"]
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def generated_path(path: Path) -> Path:
    if not path.exists() or GENERATED_MARKER in path.read_text(encoding="utf-8", errors="replace"):
        return path
    return path.with_name(path.stem + ".generated" + path.suffix)


def write_indexes(vault: Path, summaries: list[dict[str, Any]]) -> None:
    codex = vault / "codex"
    index_dir = codex / ".index"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_lines = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in summaries) + ("\n" if summaries else "")
    write_atomic(index_dir / "sessions.jsonl", index_lines)

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in summaries:
        by_date[item["date"]].append(item)
        by_project[item["project"]].append(item)
    for day, items in by_date.items():
        items.sort(key=lambda item: item.get("updated", ""), reverse=True)
        lines = [f"# Codex 会话索引 · {day}", "", GENERATED_MARKER, "", f"共 {len(items)} 个会话；日报只做导航，详情在会话卡。", ""]
        for item in items:
            card = card_relpath(item)
            lines.append(f"- [[{card}|{item['title']}]] · `{item['status']}` · `{item['project']}` · 证据 {item['evidence_count']} 条")
        write_atomic(codex / "daily" / f"{day}-会话归档.md", "\n".join(lines) + "\n")

    open_items: list[str] = ["# Codex 未决项", "", GENERATED_MARKER, "", "> 只列当前卡片中的风险/待办；已完成会话不会被假装成完成。", ""]
    for item in summaries:
        if item["status"] not in {"in_progress", "blocked"}:
            continue
        card = f"[[{card_relpath(item)}|{item['title']}]]"
        for open_item in item["open_items"][:6] or ["状态仍未终结，请查看验证证据。"]:
            open_items.append(f"- {card} · `{item['status']}`：{open_item}")
    if len(open_items) == 6:
        open_items.append("- 当前没有未决项卡片。")
    write_atomic(codex / "OPEN-ITEMS.md", "\n".join(open_items) + "\n")

    decisions = ["# Codex 决策索引", "", GENERATED_MARKER, ""]
    for item in summaries:
        if not item["decisions"]:
            continue
        card = f"[[{card_relpath(item)}|{item['title']}]]"
        decisions.append(f"## {item['project']} · {item['date']}")
        decisions.extend(f"- {card}：{decision}" for decision in item["decisions"][:6])
        decisions.append("")
    if len(decisions) == 4:
        decisions.append("暂无明确决策。")
    write_atomic(codex / "DECISIONS.md", "\n".join(decisions) + "\n")

    corrections = ["# Codex 用户纠正候选", "", GENERATED_MARKER, "", "> 这是候选事实，不自动写入 HOT-MEMORY；需重复出现或人工确认后再提升。", ""]
    for item in summaries:
        if not item["corrections"]:
            continue
        card = f"[[{card_relpath(item)}|{item['title']}]]"
        corrections.append(f"## {item['project']} · {item['date']}")
        corrections.extend(f"- {card}：{correction}" for correction in item["corrections"][:6])
        corrections.append("")
    if len(corrections) == 6:
        corrections.append("暂无候选纠正。")
    write_atomic(codex / "preferences" / "CODEX-CANDIDATES.md", "\n".join(corrections) + "\n")

    for project, items in by_project.items():
        slug = slugify(project)
        context_path = generated_path(codex / "projects" / slug / "CONTEXT.md")
        context_link = str(context_path.relative_to(codex).with_suffix(""))
        items.sort(key=lambda item: item.get("updated", ""), reverse=True)
        lines = [f"# {project} · Codex 项目上下文", "", GENERATED_MARKER, "", f"会话数：{len(items)} · 最近更新：{items[0]['date']}", "", "## 当前状态", ""]
        for item in items[:12]:
            card = f"[[{card_relpath(item)}|{item['title']}]]"
            lines.append(f"- {card} · `{item['status']}` · 验证 {item['evidence_count']} 条")
            for claim in item["claims"][-2:]:
                lines.append(f"  - 声称：{claim}")
            for evidence in item["verified"][-2:]:
                lines.append(f"  - 证据：{evidence}")
            for open_item in item["open_items"][-2:]:
                lines.append(f"  - 待办：{open_item}")
        lines += ["", "## 入口", "", "- [[../../INDEX|记忆总目录]]", "- [[../../OPEN-ITEMS|未决项]]", "- [[../../DECISIONS|决策索引]]"]
        write_atomic(context_path, "\n".join(lines) + "\n")

    index_lines = [
        "# Codex 记忆索引", "", GENERATED_MARKER, "",
        "Codex 会话已按会话卡片归档；日报只做导航，不能代替证据。", "",
        f"- 会话卡：{len(summaries)}", f"- 项目：{len(by_project)}",
        f"- 进行中/阻塞：{sum(item['status'] in {'in_progress', 'blocked'} for item in summaries)}",
        f"- 有验证证据：{sum(bool(item['verified']) for item in summaries)}", "",
        "## 入口", "", "- [[OPEN-ITEMS|当前未决项]]", "- [[DECISIONS|可复用决策]]", "- [[preferences/CODEX-CANDIDATES|用户纠正候选]]", "",
        "## 项目", "",
    ]
    for project in sorted(by_project):
        context_path = generated_path(codex / "projects" / slugify(project) / "CONTEXT.md")
        context_link = str(context_path.relative_to(codex).with_suffix(""))
        index_lines.append(f"- [[{context_link}|{project}]]")
    write_atomic(codex / "INDEX.md", "\n".join(index_lines) + "\n")


def write_cards(vault: Path, summaries: list[dict[str, Any]]) -> None:
    base = vault / "codex" / "sessions"
    for summary in summaries:
        path = base / summary["date"] / card_key(summary["session_id"]) / "memory.md"
        write_atomic(path, card_text(summary))


def score_query(summary: dict[str, Any], query: str, now: datetime | None = None) -> int:
    query = query.strip().lower()
    if not query:
        return 0
    fields = {
        "project": 40, "title": 24, "goal": 18, "claims": 14, "verified": 14,
        "open_items": 12, "decisions": 12, "corrections": 10,
    }
    score = 0
    for field_name, weight in fields.items():
        value = summary.get(field_name, [])
        if isinstance(value, list):
            value = " ".join(str(item) for item in value)
        if query in str(value).lower():
            score += weight
    tokens = [token for token in re.split(r"\s+", query) if token]
    haystack = json.dumps(summary, ensure_ascii=False).lower()
    score += sum(4 for token in tokens if token in haystack)
    if summary.get("status") in {"in_progress", "blocked"}:
        score += 8
    if now:
        try:
            age = (now.date() - date.fromisoformat(summary["date"])).days
            score += max(0, 10 - min(age, 10))
        except (KeyError, ValueError):
            pass
    return score


def recall(vault: Path, query: str, limit: int = 5) -> int:
    index_path = vault / "codex" / ".index" / "sessions.jsonl"
    summaries: list[dict[str, Any]] = []
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                summaries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    ranked = sorted(((score_query(item, query, datetime.now(BJT)), item) for item in summaries), key=lambda pair: pair[0], reverse=True)
    ranked = [(score, item) for score, item in ranked if score > 0][:limit]
    print(f"🔍 Codex 召回：{query}")
    print(f"📂 {vault / 'codex'}")
    print("---")
    if not ranked:
        print("未找到结构化会话卡；先运行 codex_memory.py 建索引。")
        return 1
    print("当前结论")
    for score, item in ranked:
        print(f"- [{item['status']}] {item['title']} · {item['project']} · {item['date']} · score={score}")
        for evidence in item.get("verified", [])[-2:]:
            print(f"  证据：{evidence}")
        for open_item in item.get("open_items", [])[-2:]:
            print(f"  待办：{open_item}")
        print(f"  卡片：codex/{card_relpath(item)}/memory.md")
    return 0


def build(vault: Path, codex_home: Path, target_date: str | None = None) -> list[dict[str, Any]]:
    titles = session_title_map(codex_home / "session_index.jsonl")
    sessions = load_sessions(codex_home, titles)
    all_summaries = [build_summary(session) for session in sessions.values() if session.messages or session.evidence]
    all_summaries.sort(key=lambda item: (item["date"], item.get("updated", ""), item["session_id"]), reverse=True)
    selected = [item for item in all_summaries if not target_date or item["date"] == target_date]
    write_cards(vault, selected)
    # Global indexes must remain complete even when only one date's cards are rebuilt.
    write_indexes(vault, all_summaries)
    return selected


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(DEFAULT_CODEX_HOME))))
    parser.add_argument("--date", help="只重建指定 BJT 日期；不传则重建所有已发现会话")
    parser.add_argument("--recall", metavar="QUERY", help="从已生成 JSONL 索引召回相关会话")
    parser.add_argument("--limit", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    vault = args.vault.expanduser().resolve()
    if args.recall is not None:
        return recall(vault, args.recall, max(1, args.limit))
    summaries = build(vault, args.codex_home.expanduser().resolve(), args.date)
    print(f"Codex structured memory: {len(summaries)} session cards")
    print(f"Vault: {vault / 'codex'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
