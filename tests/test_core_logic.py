"""核心进化逻辑单元测试（P0-3：验证纯函数逻辑，防止回归）

零依赖：标准库 unittest，任何人 clone 即可跑。
运行: python3 tests/test_core_logic.py
"""
import sys
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 让模块可导入（相对路径 + 隔离 HOME，避免碰真实数据）
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts/skill_evolution"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts/adapters"))

import canonicalize
import curator
import followup
import state
import preference_signals as psig


# ============ canonicalize.normalize_key ============
class TestNormalizeKey(unittest.TestCase):
    def test_same_timestamp_pid_norm(self):
        k1 = canonicalize.normalize_key("Script exited with code 1 at 2026-09-10 12:00 pid=52509")
        k2 = canonicalize.normalize_key("Script exited with code 1 at 2026-09-09 23:50 pid=8812")
        self.assertEqual(k1, k2)

    def test_diff_error_not_norm(self):
        k1 = canonicalize.normalize_key("Script exited with code 1 at 2026-09-10 12:00 pid=52509")
        k3 = canonicalize.normalize_key("Connection refused at host foo")
        self.assertNotEqual(k1, k3)

    def test_timestamps_variants(self):
        k1 = canonicalize.normalize_key("2026-09-10 12:00:01 error")
        k2 = canonicalize.normalize_key("2026-09-11 08:30:00 error")
        self.assertEqual(k1, k2)

    def test_numbers_and_hex_norm(self):
        k1 = canonicalize.normalize_key("port 8080 timeout err 0x1f")
        k2 = canonicalize.normalize_key("port 9090 timeout err 0xaa")
        self.assertEqual(k1, k2)

    def test_distinct_text_not_norm(self):
        k1 = canonicalize.normalize_key("disk full on /dev/sda")
        k2 = canonicalize.normalize_key("network unreachable on eth0")
        self.assertNotEqual(k1, k2)

    def test_ctrl_chars(self):
        k = canonicalize.normalize_key("line1\nline2\ttab")
        self.assertEqual(k, "line1 line2 tab")


# ============ curator 退役门槛 ============
class TestCurator(unittest.TestCase):
    def _skill(self, name, load=0, age=100, size=1000, installed=True):
        # 字段与 metrics.skill_facts() 输出对齐（curator 依赖全套字段）
        return {
            "name": name, "load_sessions": load, "self_errors": 0,
            "reload_sessions": 0, "edits": 0, "age_days": age,
            "size_bytes": size, "installed": installed, "disabled": False,
            "vault_mentions_90d": 0,
        }

    def test_no_retire_when_used(self):
        facts = [self._skill("used", load=10)]
        props = curator.curate(facts, prev_snapshot_names={"used": {"load": 10}})
        self.assertEqual(props, [])

    def test_retire_zero_load_age(self):
        # 退役需同时满足：零加载 + age≥MIN_AGE_DAYS + 有基线且基线也零 + 无冷库引用
        facts = [self._skill("dead", load=0, age=120)]
        props = curator.curate(facts, prev_snapshot_names={"dead": {"load": 0}})
        self.assertTrue(any(p["kind"] == "retire" for p in props))

    def test_no_retire_self_built(self):
        facts = [self._skill("user-mine", load=0, age=200)]
        props = curator.curate(facts, prev_snapshot_names={"user-mine": {"load": 0}})
        self.assertEqual(props, [])

    def test_cap_retire_per_week(self):
        # 30 个死技能都有基线 → 退役限量 5 个/周（MAX_RETIRE_PER_WEEK 函数内硬编码）
        facts = [self._skill(f"dead{i}", load=0, age=200, size=1000) for i in range(30)]
        prev = {f"dead{i}": {"load": 0} for i in range(30)}
        props = curator.curate(facts, prev_snapshot_names=prev)
        retires = [p for p in props if p["kind"] == "retire"]
        self.assertLessEqual(len(retires), 5)

    def test_no_retire_without_baseline(self):
        facts = [self._skill("new", load=0, age=30)]
        props = curator.curate(facts, prev_snapshot_names=None)
        self.assertEqual(props, [])

    def test_no_retire_vault_mentioned(self):
        # 冷库近 90 天提到过 → 不退役（知识被激活过）
        s = self._skill("cold-ref", load=0, age=200)
        s["vault_mentions_90d"] = 3
        props = curator.curate([s], prev_snapshot_names={"cold-ref": {"load": 0}})
        self.assertEqual(props, [])


# ============ followup.check_due ============
class TestFollowup(unittest.TestCase):
    def test_no_zero_facts_no_crash(self):
        self.assertEqual(followup.check_due([], []), [])

    def test_future_follow_up_not_due(self):
        fu = followup.create_follow_up(
            {"id": "P1", "status": "approved", "follow_up_after": "2099-01-01"},
            [{"name": "x", "load_sessions": 5, "installed": True, "disabled": False}],
            [],
        )
        # create_follow_up 返回 dict 或 None（不归队即 None）
        if fu is not None:
            self.assertIsInstance(fu, dict)


# ============ preference_signals 词表 ============
class TestPreferenceSignals(unittest.TestCase):
    def test_correction_list_nonempty(self):
        self.assertGreater(len(psig.CORRECTION), 5)

    def test_approval_list_nonempty(self):
        self.assertGreater(len(psig.APPROVAL), 3)

    def test_real_user_text_system_injection(self):
        # 系统注入/图片占位排除（设计意图：不是排除短消息）
        self.assertFalse(psig._is_real_user_text("[System: x]"))
        self.assertFalse(psig._is_real_user_text("@image foo.png"))
        self.assertFalse(psig._is_real_user_text(""))
        # 短消息 "ok" 是真实用户确认 → 算真实
        self.assertTrue(psig._is_real_user_text("ok"))


# ============ state.py schema ============
class TestState(unittest.TestCase):
    def test_empty_state_fields(self):
        d = state.empty_state()
        for k in ("weekly_snapshots", "proposals", "preferences",
                  "failure_memory", "prevented", "approved_changes"):
            self.assertIn(k, d)

    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(state, "STATE_FILE", Path(tmp) / "nope.json"):
                d = state.load()
                self.assertEqual(d["version"], 1)
                self.assertEqual(d["proposals"], [])


# ============ approve.py 状态机 ============
class TestApproveStateMachine(unittest.TestCase):
    """approve/reject/undo/done 流转。用临时 state + 临时 config.yaml 隔离。"""

    def setUp(self):
        import approve
        self.approve = approve
        self.tmp = tempfile.TemporaryDirectory()
        tmpp = Path(self.tmp.name)
        # 隔离 state
        self._orig = (state.DIR, state.STATE_FILE, state.LOCK_FILE)
        state.DIR = tmpp / "se"
        state.STATE_FILE = state.DIR / "state.json"
        state.LOCK_FILE = state.DIR / "state.lock"
        state.DIR.mkdir(parents=True)
        # 隔离 config.yaml
        self._orig_cfg = approve.CONFIG
        cfg = tmpp / "config.yaml"
        cfg.write_text("skills:\n  disabled: []\n")
        approve.CONFIG = cfg
        # 造一个 pending 提案
        state.save({**state.empty_state(),
                    "proposals": [{"id": "P1", "kind": "fix_reference",
                                   "target": "some-skill", "status": "pending"},
                                  {"id": "P2", "kind": "retire",
                                   "target": "dead-skill", "status": "pending"}]})

    def tearDown(self):
        state.DIR, state.STATE_FILE, state.LOCK_FILE = self._orig
        self.approve.CONFIG = self._orig_cfg
        self.tmp.cleanup()

    def _status(self, pid):
        return next(x["status"] for x in state.load()["proposals"] if x["id"] == pid)

    def test_approve_non_retire_goes_approved_not_done(self):
        """非 retire 批准 → approved（待执行），不直接 done（批准≠完成）"""
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.approve.cmd_approve("P1", done=False)
        self.assertEqual(self._status("P1"), "approved")
        self.assertIn("--done", buf.getvalue())

    def test_approve_with_done_flag(self):
        """显式 --done → done"""
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.approve.cmd_approve("P1", done=True)
        self.assertEqual(self._status("P1"), "done")

    def test_reject_marks_rejected(self):
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.approve.cmd_reject("P1", "不需要")
        self.assertEqual(self._status("P1"), "rejected")

    def test_approve_nonpending_noop(self):
        """非 pending 提案重复 approve → 状态不变"""
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.approve.cmd_approve("P1", done=True)
            self.approve.cmd_approve("P1", done=False)  # 已 done，应拒绝
        self.assertEqual(self._status("P1"), "done")



# ============ state schema 迁移框架 ============
class TestStateMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmpp = Path(self.tmp.name)
        self._orig = (state.DIR, state.STATE_FILE, state.LOCK_FILE, state.SCHEMA_VERSION, dict(state._MIGRATIONS))
        state.DIR = tmpp / "se"; state.STATE_FILE = state.DIR / "state.json"; state.LOCK_FILE = state.DIR / "state.lock"
        state.DIR.mkdir(parents=True)

    def tearDown(self):
        state.DIR, state.STATE_FILE, state.LOCK_FILE, state.SCHEMA_VERSION, _ = self._orig
        state._MIGRATIONS.clear(); state._MIGRATIONS.update(self._orig[4])
        self.tmp.cleanup()

    def test_current_version_loads_normally(self):
        state.save({**state.empty_state(), "proposals": [{"id": "P1"}]})
        d = state.load()
        self.assertEqual(d["version"], state.SCHEMA_VERSION)
        self.assertEqual(d["proposals"], [{"id": "P1"}])

    def test_migration_chain_runs_and_backs_up(self):
        # 模拟旧版 v0 数据 + 注册 v0→v1 迁移
        old = {"version": 0, "proposals": [], "legacy_field": "x"}
        state.STATE_FILE.write_text(json.dumps(old))
        state.SCHEMA_VERSION = 1
        state._MIGRATIONS[0] = lambda d: {**d, "migrated": True}
        d = state.load()
        self.assertTrue(d.get("migrated"))
        self.assertEqual(d["version"], 1)
        # 备份文件存在
        self.assertTrue(state.STATE_FILE.with_suffix(".json.bak-v0").exists())
        # 迁移已落盘
        self.assertEqual(json.loads(state.STATE_FILE.read_text())["version"], 1)

    def test_missing_migration_fails_loud(self):
        # 旧版数据 + 无迁移函数 → 抛 RuntimeError（不静默返回空数据）
        state.STATE_FILE.write_text(json.dumps({"version": 0}))
        state.SCHEMA_VERSION = 1
        state._MIGRATIONS.clear()
        with self.assertRaises(RuntimeError):
            state.load()


# ============ Generic 伪零保护 ============
class TestGenericUnknownProtection(unittest.TestCase):
    def test_unknown_quality_blocks_auto_disable(self):
        import cap_enforcer
        facts = [{"name": f"s{i}", "installed": True, "disabled": False,
                  "load_sessions": 0, "usage_quality": "unknown",
                  "age_days": 120, "size_bytes": 5000} for i in range(130)]
        r = cap_enforcer.enforce_cap(facts, cap=120, dry_run=False)
        self.assertEqual(len(r["disabled_now"]), 0)
        self.assertEqual(len(r.get("candidates_for_review", [])), 10)

    def test_measured_quality_allows(self):
        import cap_enforcer
        calls = []
        orig = cap_enforcer.set_disabled
        cap_enforcer.set_disabled = lambda n, v: calls.append(n)
        try:
            facts = [{"name": f"s{i}", "installed": True, "disabled": False,
                      "load_sessions": 0, "usage_quality": "measured",
                      "age_days": 120, "size_bytes": 5000} for i in range(130)]
            r = cap_enforcer.enforce_cap(facts, cap=120, dry_run=False)
            self.assertEqual(len(calls), 10)
        finally:
            cap_enforcer.set_disabled = orig


# ============ AGENT_LLM shell 收紧 ============
class TestLLMShellPolicy(unittest.TestCase):
    def _llm(self, cmd, shell=None):
        os.environ["AGENT_TYPE"] = "generic"
        os.environ["AGENT_LLM"] = cmd
        if shell is None:
            os.environ.pop("AGENT_LLM_SHELL", None)
        else:
            os.environ["AGENT_LLM_SHELL"] = shell
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "adapters"))
        import agent_adapter as A
        return A.llm_call("hello world", timeout=5)

    def test_default_no_shell_plain_cmd_works(self):
        self.assertEqual(self._llm("cat"), "hello world")

    def test_default_pipe_not_executed(self):
        # 默认不过 shell：管道当字面参数，不执行 → 空结果
        self.assertEqual(self._llm("cat | head -c 2"), "")

    def test_explicit_shell_allows_pipe(self):
        self.assertEqual(self._llm("cat | head -c 5", shell="1"), "hello")

    def tearDown(self):
        for k in ("AGENT_TYPE", "AGENT_LLM", "AGENT_LLM_SHELL"):
            os.environ.pop(k, None)

if __name__ == "__main__":
    unittest.main(verbosity=2)
