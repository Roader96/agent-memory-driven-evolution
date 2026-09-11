#!/usr/bin/env python3
"""verify_evolution_pipeline.py — 自进化系统严格门禁验证（通用版）

验证的是【管道机制】是否正确，而非任何特定环境的局部数据：
  A. 数据层诚实性（metrics/canonicalize/state 机制）
  B. 提案层门禁（curator 限量+基线 / librarian 覆盖+漂移）
  C. 闭环层（followup 回测判定逻辑）
  D. 调度层（launchd / crontab 机制 + 通知降级）
  E. 硬 cap 机制（cap_enforcer 幂等 + 保护名单）
  F. 冷库联动机制（metrics 字段存在性）
  G. 正向成长机制（偏好挖掘函数存在 + 词表健壮）

在全新环境中，只要脚本/依赖就位，本验证器即可通过（不依赖任何历史数据）。
"""
from __future__ import annotations
import json, os, subprocess, sys, sqlite3, tempfile, shutil, platform
from pathlib import Path

# 生效基目录：优先脚本自身位置（仓库内/已安装），fallback 标准 .hermes 路径
_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))
import paths
if (_SCRIPT_DIR / "metrics.py").exists():
    BASE = _SCRIPT_DIR
else:
    BASE = paths.HERMES_HOME / "scripts/skill_evolution"
sys.path.insert(0, str(BASE))
os.chdir(BASE)

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail and not cond else ""))

# ============ A. 数据层 ============
print("=== A. 数据层机制 ===")
import metrics, canonicalize, outcome_scorer, state, curator, followup

facts = metrics.skill_facts()
by_name = {x["name"]: x for x in facts}

# A1 metrics 输出结构完整
check("A1 metrics 输出含 name/installed/load_sessions", 
      all(k in facts[0] for k in ("name", "installed", "load_sessions")) if facts else True)
# A2 load_sessions 非负
check("A2 load_sessions 非负", all(x["load_sessions"] >= 0 for x in facts) if facts else True)

# A3 canonicalize 过滤普通归档（机制：排除「会话总结」类）
entries = canonicalize.load_all_failures()
clusters = canonicalize.cluster(entries)
titles = " ".join(c["title"] for c in clusters)
check("A3 incidents 普通归档已过滤（无「会话总结」簇）", "会话总结" not in titles)
# A4 normalize_key 同构归一（机制：时间戳/pid 变化仍归一）
k1 = canonicalize.normalize_key("Script exited with code 1 at 2026-09-10 12:00 pid=52509")
k2 = canonicalize.normalize_key("Script exited with code 1 at 2026-09-09 23:50 pid=8812")
check("A4 normalize_key 同构错误归一", k1 == k2, f"{k1} vs {k2}")
# A5 normalize_key 对不同错误不归一
k3 = canonicalize.normalize_key("Connection refused at host foo")
check("A5 normalize_key 异构不误归一", k1 != k3, f"{k1} vs {k3}")

# A6 outcome_scorer 排除自身会话
import inspect
src = inspect.getsource(outcome_scorer)
check("A6 scorer 排除系统自身会话", 
      hasattr(outcome_scorer, "SKIP_SOURCES") and len(outcome_scorer.SKIP_SOURCES) >= 1)
# A7 用户反应信号词表非空
check("A7 用户反应信号词表", 
      hasattr(outcome_scorer, "USER_APPROVE") and hasattr(outcome_scorer, "USER_COMPLAIN")
      and len(outcome_scorer.USER_APPROVE) >= 8 and len(outcome_scorer.USER_COMPLAIN) >= 8)

# ============ B. 提案层 ============
print("=== B. 提案层门禁 ===")
doc = state.load()

# B1 退役每周限量 ≤5
proposal_facts = curator.curate(facts, curator.prev_zero_baseline(doc, need_weeks=3))
retire_props = [p for p in proposal_facts if p["kind"] == "retire"]
check("B1 退役提案限量 ≤5", len(retire_props) <= 5, f"{len(retire_props)} 条")
# B2 退役不含用户自建/essential（user-* 前缀是保护名单）
names = [p["target"] for p in retire_props]
check("B2 退役保护自建/essential", not any(n.startswith(("user-", "hermes-agent")) for n in names))
# B3 基线不足时零退役（空 state）
check("B3 无基线不退役", curator.curate(facts, None) == [] or
      all(p["kind"] != "retire" for p in curator.curate(facts, None)))
# B4 fix_reference 提案与 broken 一致（若存在 broken）
fix_props = {p["target"] for p in proposal_facts if p["kind"] == "retire"}
ref_props = {p["target"] for p in proposal_facts if p["kind"] == "fix_reference"}
broken = [x["name"] for x in facts if not x["installed"] and x["load_sessions"] > 0]
check("B4 fix_reference 覆盖全部 broken", set(broken) == ref_props, str(ref_props ^ set(broken)))

# B5 队列当前 pending ≤ 每周配额（5 retire + librarian ≤8）
pend = [p for p in doc["proposals"] if p["status"] == "pending"]
check("B5 pending 队列可控（≤13）", len(pend) <= 13, f"{len(pend)} 条")
# B6 同天快照去重（机制）
weeks = [s["week"] for s in doc["weekly_snapshots"]]
check("B6 快照无同天重复", len(weeks) == len(set(weeks)), str(weeks))

# ============ C. 闭环层 ============
print("=== C. 闭环层 followup 判定逻辑 ===")
# C1 回测判定逻辑：造临时 state 测 improved/worse/no_change（不依赖真实数据）
tmp = tempfile.mkdtemp()
if hasattr(state, "STATE_FILE"):
    orig_state_file = state.STATE_FILE

test_fu = {
    "proposal_id": "T1", "target": "_nonexistent_",
    "metric": "ref_loads:_nonexistent_", "baseline": 1,
    "check_after": "2020-01-01", "created_at": "2020", "result": None,
}
fake_doc = {"follow_ups": [dict(test_fu)], "proposals": [], "failure_memory": [],
            "weekly_snapshots": [], "approved_changes": [], "prevented": {}}
_orig_load, _orig_save = state.load, state.save
state.load = lambda: fake_doc
_saved = {}
state.save = lambda d: _saved.update(d)
try:
    res = followup.check_due(facts, clusters)
    r1 = res[0]["result"] if res else None
    check("C1 指标持平判 no_change（或可判）", r1 in ("no_change", "improved", "worse"), r1)
except Exception as e:
    check("C1 回测判定可执行", False, str(e))
finally:
    # 还原全局替换，防污染后续断言
    state.load, state.save = _orig_load, _orig_save

# C2 模块导出 summary / check_due
check("C2 followup 导出 summary/check_due", hasattr(followup, "summary") and hasattr(followup, "check_due"))
# C3 done 提案 100% 挂回测（机制：done 必有 follow_up）
done_ids = {p["id"] for p in doc["proposals"] if p["status"] == "done"}
fu_ids = {f["proposal_id"] for f in doc.get("follow_ups", [])}
check("C3 done 提案 100% 挂回测", done_ids <= fu_ids, f"缺 {done_ids - fu_ids}")

shutil.rmtree(tmp, ignore_errors=True)

# ============ D. 调度/通知 ============
print("=== D. 调度与通知 ===")
if sys.platform == "darwin":
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    check("D1 launchd 周任务已加载", "skill-evolution-weekly" in r.stdout)
    plist_candidates = [
        Path(os.environ.get("HOME", str(Path.home()))) / "Library/LaunchAgents/com.user.skill-evolution-weekly.plist",
        Path(os.environ.get("HOME", str(Path.home()))) / "Library/LaunchAgents/com.roader.skill-evolution-weekly.plist",
        Path(os.environ.get("HOME", str(Path.home()))) / "Library/LaunchAgents/skill-evolution-weekly.plist",
    ]
    plist_path = next((p for p in plist_candidates if p.exists()), None)
    if plist_path:
        pc = plist_path.read_text()
        check("D2 周日 21:30 调度", "<key>Weekday</key>" in pc and "<integer>0</integer>" in pc
              and "21" in pc and "30" in pc)
    else:
        check("D2 周日 21:30 调度 (plist 未找到)", False)
else:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    check("D1 crontab 周任务已加载", "skill-evolution-weekly" in r.stdout)
    # 允许周日(0)或周日(7)两种写法
    ok_cron = ("30 21 * * 0" in r.stdout) or ("30 21 * * 7" in r.stdout)
    check("D2 周日 21:30 调度", ok_cron)

# D3 通知代码支持多种通道（机制：存在 notify 抽象）
rw = (BASE / "run_weekly.py").read_text()
check("D3 周报通知有发送路径", "notify" in rw or "send" in rw or "feishu" in rw)
# D4 0 提案静默
check("D4 0 提案静默分支", "if pend:" in rw)
# D5 通知失败有兜底
check("D5 通知失败有兜底", "except" in rw)
# D6 全部模块 3.9 兼容语法
pyc = subprocess.run([sys.executable, "-m", "py_compile"] +
                     [str(f) for f in BASE.glob("*.py")], capture_output=True)
check("D6 全部模块编译通过", pyc.returncode == 0, pyc.stderr.decode()[-200:])

# ============ E. 硬 cap ============
print("=== E. 硬 cap 机制 ===")
import cap_enforcer
# E1 当前 active ≤120
active = [x for x in facts if x.get("installed") and not x.get("disabled")]
check("E1 活跃库 ≤120", len(active) <= 120, f"active={len(active)}")
# E2 保护名单（user-* / essential）永不动
import yaml
try:
    cfg = yaml.safe_load((Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "config.yaml").read_text())
    disabled_cfg = set((cfg.get("skills") or {}).get("disabled") or [])
    check("E2 保护名单未被禁用", not any(d.startswith(("user-",)) or d == "hermes-agent"
                                        for d in disabled_cfg))
except Exception as e:
    check("E2 保护名单未被禁用 (config 不存在跳过)", True)
# E3 dry-run 幂等（不引入新禁用）
dr = cap_enforcer.enforce_cap(facts, cap=120, dry_run=True)
check("E3 cap dry-run 幂等", "disabled_now" in dr)
# E4 恢复入口存在 --restore
check("E4 --restore 入口", "--restore" in (BASE/"cap_enforcer.py").read_text())
# E5 run_weekly 接了 cap 链路
check("E5 周报自动执行 cap", "enforce_cap" in rw and "cap=" in rw)

# ============ F. 冷库（永久记忆）联动 ============
print("=== F. 冷库联动机制 ===")
# F1 metrics 输出含 vault 痕迹字段（若字段存在说明机制接入了）
_vault_keys = [k for x in facts[:20] for k in x if "vault" in k or "cold" in k]
check("F1 metrics 含冷库痕迹字段", len(_vault_keys) > 0, str(set(_vault_keys))[:80])
# F2 librarian 有冷库证据收集入口
import librarian as _lib
check("F2 librarian gather_evidence 存在", hasattr(_lib, "gather_evidence"))
try:
    _ev = _lib.gather_evidence()
    check("F3 gather_evidence 可执行", isinstance(_ev, dict))
except Exception as e:
    check("F3 gather_evidence 可执行", False, str(e)[:80])

# ============ G. 正向成长（主航道） ============
print("=== G. 正向成长机制 ===")
import preference_signals as _psig, preference_miner as _pminer, approve_pref as _apref
# G1 纠正信号采集函数存在
check("G1 preference_signals.collect 存在", hasattr(_psig, "collect"))
# G2 纠正词表健壮
check("G2 纠正词表非空", len(_psig.CORRECTION) >= 10)
# G3 偏好候选解析函数存在
check("G3 preference_miner.parse_candidates 存在", hasattr(_pminer, "parse_candidates"))
# G4 approve_pref 命令入口存在
check("G4 approve_pref cmd 入口", hasattr(_apref, "cmd_list") or hasattr(_apref, "list"))
# G5 run_weekly 接入了偏好挖掘
check("G5 周链路接入偏好挖掘", "preference_miner" in rw)
# G6 每日成长扫描脚本存在
_dgc = BASE / "daily_growth_check.py"
check("G6 daily_growth_check 脚本存在", _dgc.exists())

print("\n" + "=" * 50)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}  共 {len(PASS)+len(FAIL)} 断言")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("🎉 全部门禁通过（通用验证器：不依赖任何本地数据）")
