#!/usr/bin/env python3
"""state.py — 自进化状态库（ADD-only，借鉴 mem0：只追加不覆盖）

存 ~/.hermes/skill_evolution/state.json：
  weekly_snapshots  每周技能度量快照（看趋势：某技能是否在被淘汰）
  proposals         技能变更提案队列（退役/新增/修订），状态 pending/approved/rejected/done
  failure_memory    失败簇记忆（永不删，借鉴 SkillSmith：防重复诊断/复活已废技能）
  prevented         教训 id -> 实际拦住次数（闭环度量）
所有变更走提案 + 用户审批，脚本绝不自动改技能。
"""
import json
import os
from datetime import datetime
from pathlib import Path

HOME = Path.home()
DIR = HOME / ".hermes" / "skill_evolution"
STATE_FILE = DIR / "state.json"
SCHEMA_VERSION = 1  # 当前 schema 版本；变更结构时 +1 并在 _MIGRATIONS 挂迁移函数


def empty_state():
    return {
        "version": SCHEMA_VERSION,
        "weekly_snapshots": [],
        "follow_ups": [],
        "proposals": [],
        "preferences": [],
        "failure_memory": [],
        "prevented": {},
        "approved_changes": [],
    }


# 迁移链：version N → N+1。迁移前自动备份 state.json.bak-vN。
# 示例：_MIGRATIONS[1] = _m1_to_2  （函数签名: dict -> dict）
_MIGRATIONS = {}


def _migrate(d: dict, from_v: int) -> dict:
    """沿迁移链升到 SCHEMA_VERSION；每一步前备份（备份名 state.json.bak-vN）。"""
    v = from_v
    while v < SCHEMA_VERSION:
        fn = _MIGRATIONS.get(v)
        if fn is None:
            raise RuntimeError(f"state.json schema v{v} 无迁移函数（目标 v{SCHEMA_VERSION}）——拒绝静默读旧格式")
        # 迁移前备份
        try:
            bak = STATE_FILE.with_suffix(f".json.bak-v{v}")
            if not bak.exists():
                bak.write_text(json.dumps(d, ensure_ascii=False, indent=1))
        except Exception:
            pass
        d = fn(d)
        v += 1
        d["version"] = v
    return d


LOCK_FILE = DIR / "state.lock"


def _locked(mode: str):
    """固定锁文件上的文件锁上下文管理器。
    所有进程争同一把锁（锁 tmp 文件是无效的——各自锁各自的）。
    mode: 'sh' 共享读锁 / 'ex' 独占写锁。
    """
    import contextlib
    import fcntl
    @contextlib.contextmanager
    def _ctx():
        DIR.mkdir(parents=True, exist_ok=True)
        with open(LOCK_FILE, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_SH if mode == "sh" else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    return _ctx()


def load():
    if STATE_FILE.exists():
        try:
            with _locked("sh"):  # 共享锁读，防读到写一半
                d = json.loads(STATE_FILE.read_text())
            # schema 迁移：版本落后 → 沿迁移链升级并落盘（迁移失败 fail loud，不静默）
            v = d.get("version", 1)
            if v < SCHEMA_VERSION:
                d = _migrate(d, v)
                save(d)
            for k, v_ in empty_state().items():
                d.setdefault(k, v_)
            return d
        except json.JSONDecodeError:
            pass  # JSON 损坏 → 返回空（保留原容错语义）
        # RuntimeError（无迁移函数）不吞——上抛让调用方看到
    return empty_state()


def save(d):
    # 独占锁：cron 周测与 CLI approve 并发时防 lost update（原子写只防崩溃不防并发）
    with _locked("ex"):
        tmp = STATE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=1))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)  # 原子写


def update(mutator):
    """原子 读-改-写：整个周期在一把独占锁内（load/save 分开加锁仍有窗口）。
    mutator: fn(state_dict) -> None（就地修改），返回修改后的 dict。
    用法: state.update(lambda d: d["proposals"].append(p))
    """
    with _locked("ex"):
        d = empty_state()
        if STATE_FILE.exists():
            try:
                d = json.loads(STATE_FILE.read_text())
                for k, v in empty_state().items():
                    d.setdefault(k, v)
            except Exception:
                pass
        mutator(d)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        DIR.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=1))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
        return d


def add_snapshot(metrics_facts: list, global_stats: dict):
    d = load()
    # 只存轻量摘要（名字+关键计数），不存全量，控体积
    slim = [{
        "name": x["name"],
        "load": x["load_sessions"],
        "self_err": x["self_errors"],
        "reload": x["reload_sessions"],
        "edits": x["edits"],
        "disabled": x["disabled"],
    } for x in metrics_facts]
    week = datetime.now().strftime("%Y-%m-%d")
    # 同一天重跑覆盖当天快照（调试期多次跑不该产生重复期）
    d["weekly_snapshots"] = [s for s in d["weekly_snapshots"] if s.get("week") != week]
    d["weekly_snapshots"].append({
        "week": week,
        "n_installed": sum(1 for x in metrics_facts if x["installed"]),
        "n_used": sum(1 for x in metrics_facts if x["load_sessions"] > 0),
        "global": global_stats,
        "skills": slim,
    })
    # 只留 26 期（半年）
    d["weekly_snapshots"] = d["weekly_snapshots"][-26:]
    save(d)
    return d


def add_proposal(p: dict):
    d = load()
    # 同技能同类型已有 pending/done 提案则不重复提
    for ex in d["proposals"]:
        if (ex.get("target") == p["target"] and ex.get("kind") == p["kind"]
                and ex.get("status") in ("pending", "done")):
            return d, False
    p.setdefault("id", f"P{len(d['proposals'])+1:03d}")
    p.setdefault("status", "pending")
    p.setdefault("created", datetime.now().strftime("%Y-%m-%d"))
    d["proposals"].append(p)
    save(d)
    return d, True


def list_pending():
    return [p for p in load()["proposals"] if p["status"] == "pending"]
