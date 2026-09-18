#!/usr/bin/env python3
"""结构化 Codex 记忆归档的隔离测试。

覆盖：active/archived 双源、response 去重、环境元数据过滤、证据字段、
状态卡片、幂等重建和关键词召回。测试只使用临时目录，不读取真实会话。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import codex_memory


DONE_ID = "11111111-1111-4111-8111-111111111111"
BLOCKED_ID = "22222222-2222-4222-8222-222222222222"
STAMP = "2026-09-14T10:00:00+08:00"


def dump_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def meta(session_id: str) -> dict:
    return {
        "timestamp": STAMP,
        "type": "session_meta",
        "payload": {
            "session_id": session_id,
            "id": session_id,
            "cwd": "/tmp/xxzAgentMemory",
            "source": "cli",
        },
    }


def message(session_id: str, message_id: str, role: str, text: str, stamp: str = STAMP) -> dict:
    return {
        "timestamp": stamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "id": message_id,
            "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
            "internal_chat_message_metadata_passthrough": {"turn_id": f"turn-{session_id[:4]}"},
        },
    }


class TestCodexMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="codex-memory-test-")
        self.base = Path(self.tmp.name)
        self.codex_home = self.base / ".codex"
        self.memory_home = self.base / "CodexMemory"
        self.archived = self.codex_home / "archived_sessions"
        self.active = self.codex_home / "sessions" / "2026" / "09" / "14"
        self.archived.mkdir(parents=True)
        self.active.mkdir(parents=True)
        (self.codex_home / "session_index.jsonl").write_text(
            json.dumps({"id": DONE_ID, "title": "结构化记忆仿真"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        user_text = (
            "<codex_internal_context source=\"goal\">INTERNAL_GOAL should never be indexed</codex_internal_context>\n"
            "<environment_context>SECRET_ENV should never be indexed</environment_context>\n"
            "# Files mentioned by the user: /var/folders/codex-clipboard-secret.png\n"
            "## My request:\n请验证 xxzAgentMemory 的运行态仿真，并把记忆整理成结构化卡片。"
        )
        assistant_text = "已完成结构化记忆仿真，输出卡片并保留待办风险。"
        archived_done = [
            meta(DONE_ID),
            message(DONE_ID, "user-1", "user", user_text),
            message(DONE_ID, "assistant-1", "assistant", assistant_text),
            {
                "timestamp": STAMP,
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "tool-1",
                    "output": "PASS: runtime simulation; exit_code: 0",
                    "internal_chat_message_metadata_passthrough": {"turn_id": f"turn-{DONE_ID[:4]}"},
                },
            },
        ]
        active_done = [
            meta(DONE_ID),
            # Same response id in the active copy must not create a second message.
            message(DONE_ID, "user-1", "user", user_text),
            {"timestamp": STAMP, "type": "event_msg", "payload": {"type": "task_complete", "turn_id": f"turn-{DONE_ID[:4]}"}},
        ]
        dump_jsonl(self.archived / "rollout-done.jsonl", archived_done)
        dump_jsonl(self.active / "rollout-done.jsonl", active_done)

        blocked = [
            meta(BLOCKED_ID),
            message(BLOCKED_ID, "user-2", "user", "继续检查尚未完成的记忆归档问题"),
            {"timestamp": STAMP, "type": "event_msg", "payload": {"type": "turn_aborted", "turn_id": f"turn-{BLOCKED_ID[:4]}"}},
        ]
        dump_jsonl(self.archived / "rollout-blocked.jsonl", blocked)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_deduplicates_sources_and_filters_metadata(self) -> None:
        summaries = codex_memory.build(self.memory_home, self.codex_home)
        done = next(item for item in summaries if item["session_id"] == DONE_ID)
        self.assertEqual(done["message_count"], 2)
        self.assertEqual(done["project"], "xxzAgentMemory")
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["title"], "结构化记忆仿真")
        self.assertEqual(len(done["sources"]), 2)
        self.assertTrue(done["verified"])
        self.assertTrue(any("PASS" in item for item in done["verified"]))
        self.assertTrue(any("SECRET_ENV" not in item for item in done["goal"]))

        card = self.memory_home / "sessions" / "2026-09-14" / DONE_ID / "memory.md"
        text = card.read_text(encoding="utf-8")
        for heading in ("## 任务", "## 决策", "## 产出", "## 验证证据", "## 待办/风险", "## 用户纠正"):
            self.assertIn(heading, text)
        self.assertIn("PASS: runtime simulation", text)
        self.assertIn("请验证 xxzAgentMemory", text)
        self.assertNotIn("SECRET_ENV", text)
        self.assertNotIn("INTERNAL_GOAL", text)
        self.assertNotIn("codex_internal_context", text)
        self.assertNotIn("codex-clipboard-secret", text)

        blocked = next(item for item in summaries if item["session_id"] == BLOCKED_ID)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["verified"], [])


    def test_process_plans_and_weak_continuation_are_not_results(self) -> None:
        stamp = datetime.fromisoformat(STAMP)
        session = codex_memory.Session("logic-1", cwd="/tmp/demo-project")
        session.messages = [
            codex_memory.Message("user", "继续", stamp, "t1", "u1", "test.jsonl", 1),
            codex_memory.Message("user", "不对，这个结论错了", stamp, "t1", "u2", "test.jsonl", 2),
            codex_memory.Message(
                "assistant",
                "我先只读检查。接下来会重跑门禁；如果通过就完成最终发布。",
                stamp, "t1", "a1", "test.jsonl", 3,
            ),
            codex_memory.Message(
                "assistant",
                "现在我会改成只使用已安装副本。运行态仿真已通过，并已写入验证卡片。",
                stamp, "t1", "a2", "test.jsonl", 4,
            ),
        ]
        summary = codex_memory.build_summary(session)
        self.assertIn("运行态仿真已通过", " ".join(summary["claims"]))
        self.assertNotIn("现在我会改成", " ".join(summary["claims"]))
        self.assertNotIn("最终发布", " ".join(summary["claims"]))
        self.assertNotIn("我先只读检查", " ".join(summary["open_items"]))
        self.assertNotIn("继续", summary["corrections"])
        self.assertTrue(any("不对" in item for item in summary["corrections"]))

    def test_artifact_filter_removes_git_and_truncated_noise(self) -> None:
        artifacts = codex_memory.extract_artifacts([
            "12:n/Users/demo/project/scripts/tool.py:13",
            "see ./.git/HEAD and ./.DS_Store and scripts/result.md…",
        ])
        self.assertIn("/Users/demo/project/scripts/tool.py", artifacts)
        self.assertFalse(any(".git" in item or ".DS_Store" in item or item.endswith("…") for item in artifacts))

    def test_manual_project_context_is_preserved_and_date_rebuild_keeps_global_index(self) -> None:
        codex_memory.build(self.memory_home, self.codex_home)
        project_context = self.memory_home / "projects" / "xxzAgentMemory" / "CONTEXT.md"
        project_context.parent.mkdir(parents=True, exist_ok=True)
        project_context.write_text("# manual context\n", encoding="utf-8")
        other_day = self.codex_home / "sessions" / "2026" / "09" / "15" / "rollout-other.jsonl"
        other_id = "44444444-4444-4444-8444-444444444444"
        other_records = [
            meta(other_id) | {"timestamp": "2026-09-15T10:00:00+08:00"},
            message(other_id, "other-user", "user", "请处理另一天的任务", "2026-09-15T10:00:01+08:00"),
        ]
        other_records[0]["payload"] = dict(other_records[0]["payload"], cwd="/tmp/xxzAgentMemory")
        dump_jsonl(other_day, other_records)

        selected = codex_memory.build(self.memory_home, self.codex_home, target_date="2026-09-14")
        self.assertEqual({item["session_id"] for item in selected}, {DONE_ID, BLOCKED_ID})
        self.assertEqual(project_context.read_text(encoding="utf-8"), "# manual context\n")
        generated = project_context.with_name("CONTEXT.generated.md")
        self.assertIn("Codex 项目上下文", generated.read_text(encoding="utf-8"))
        index_text = (self.memory_home / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("projects/xxzAgentMemory/CONTEXT.generated", index_text)
        index_items = [json.loads(line) for line in (self.memory_home / ".index" / "sessions.jsonl").read_text().splitlines()]
        self.assertEqual({item["session_id"] for item in index_items}, {DONE_ID, BLOCKED_ID, other_id})

    def test_tool_verification_requires_result_line_not_source(self) -> None:
        source = 'def check():\n    if returncode == 0:\n        print("门禁通过")'
        self.assertFalse(codex_memory.is_verified_text(source, "custom_tool_call_output"))
        self.assertTrue(codex_memory.is_verified_text("Process exited with code 0", "custom_tool_call_output"))
        self.assertTrue(codex_memory.is_verified_text("PASS: runtime simulation", "custom_tool_call_output"))

    def test_completed_work_is_not_misclassified_as_open_item(self) -> None:
        completed = "我已经补上并接入：新增运行态仿真并验证通过。但我不会声称完美：当前还没有真实 launchd 端到端验证"
        historical = "我已经确认问题不是摘要短，而是之前没有把跨会话决定、已验证事实和待办提炼出来"
        result = codex_memory.snippets_matching([completed, historical], codex_memory.OPEN_MARKERS)
        self.assertTrue(any("还没有真实 launchd" in item for item in result))
        self.assertFalse(any(item.startswith("我已经补上") for item in result))
        self.assertFalse(any(item.startswith("我已经确认") for item in result))

    def test_rebuild_is_idempotent_and_recall_uses_index(self) -> None:
        codex_memory.build(self.memory_home, self.codex_home)
        card = self.memory_home / "sessions" / "2026-09-14" / DONE_ID / "memory.md"
        index = self.memory_home / ".index" / "sessions.jsonl"
        first_card = card.read_bytes()
        first_index = index.read_bytes()

        codex_memory.build(self.memory_home, self.codex_home)
        self.assertEqual(first_card, card.read_bytes())
        self.assertEqual(first_index, index.read_bytes())
        self.assertEqual(len(list((self.memory_home / "sessions" / "2026-09-14" / DONE_ID).glob("memory*.md"))), 1)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = codex_memory.recall(self.memory_home, "结构化记忆仿真", limit=2)
        self.assertEqual(result, 0)
        self.assertIn(DONE_ID, output.getvalue())
        self.assertIn("当前结论", output.getvalue())


if __name__ == "__main__":
    unittest.main()
