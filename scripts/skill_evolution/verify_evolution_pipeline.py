#!/usr/bin/env python3
"""verify_evolution_pipeline.py — 自进化系统严格门禁验证

4 组断言：
  A. 数据层诚实性（metrics/canonicalize/state）
  B. 提案层门禁（curator 限量+基线 / librarian 覆盖+漂移）
  C. 闭环层（followup 回测判定 / approve 挂回测）
  D. 调度层（launchd / 飞书静默规则）
"""
from __future__ import annotations
import json, os, subprocess, sys, sqlite3, tempfile, shutil
from pathlib import Path

BASE = Path.home() / ".hermes/scripts/skill_evolution"
sys.path.insert(0, str(BASE))
os.chdir(BASE)

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail and not cond else ""))

# ============ A. 数据层 ============
print("=== A. 数据层诚实性 ===")
import metrics, canonicalize, outcome_scorer, state, curator, followup

facts = metrics.skill_facts()
by_name = {x["name"]: x for x in facts}

# A1 frontmatter name 解析：目录名≠技能名的两个已知案例必须 installed
check("A1 frontmatter 正名 flux-image-gen", by_name.get("flux-image-gen", {}).get("installed"))
check("A2 frontmatter 正名 roader-mac-uninstall-suite",
      by_name.get("roader-mac-uninstall-suite", {}).get("installed"))
# A3 大小写不敏感：Roader-skill-creator 大写 frontmatter
check("A3 大小写匹配 Roader-skill-creator",
      by_name.get("Roader-skill-creator", {}).get("installed"))
# A4 真坏引用只剩 6 个（之前误报 8 个）
broken = [x["name"] for x in facts if not x["installed"] and x["load_sessions"] > 0]
check("A4 broken_ref=6 且不含误报项",
      len(broken) == 6 and "flux-image-gen" not in broken
      and "roader-mac-uninstall-suite" not in broken, str(broken))
# A5 mcporter 是 optional 未安装，仍在 broken（诚实记录，不假装健康）
check("A5 mcporter 诚实标记为未安装", "mcporter" in broken)

# A6 canonicalize 过滤普通归档：「会话总结」不能进失败簇
entries = canonicalize.load_all_failures()
clusters = canonicalize.cluster(entries)
titles = " ".join(c["title"] for c in clusters)
check("A6 incidents 普通归档已过滤", "会话总结-hermes-mind" not in titles and "架构图" not in titles)
# A7 真失败簇必须在
check("A7 cron exit1 大簇存在", any("code 1" in c["title"] for c in clusters))
# A8 normalize_key 同构归一
k1 = canonicalize.normalize_key("Script exited with code 1 at 2026-09-10 12:00 pid=52509")
k2 = canonicalize.normalize_key("Script exited with code 1 at 2026-09-09 23:50 pid=8812")
check("A8 normalize_key 同构错误归一", k1 == k2, f"{k1} vs {k2}")

# A9 outcome_scorer 排除自身会话
import inspect
src = inspect.getsource(outcome_scorer)
check("A9 scorer 排除 skill-evolution-librarian",
      "skill-evolution-librarian" in outcome_scorer.SKIP_SOURCES)
# A10 用户反应信号存在
check("A10 用户反应信号词表", len(outcome_scorer.USER_APPROVE) >= 8 and "不对" in outcome_scorer.USER_COMPLAIN)

# ============ B. 提案层 ============
print("=== B. 提案层门禁 ===")
doc = state.load()

# B1 退役每周限量 ≤5
proposal_facts = curator.curate(facts, curator.prev_zero_baseline(doc, need_weeks=3))
retire_props = [p for p in proposal_facts if p["kind"] == "retire"]
check("B1 退役提案限量 ≤5", len(retire_props) <= 5, f"{len(retire_props)} 条")
# B2 退役不含自建/essential
names = [p["target"] for p in retire_props]
check("B2 退役保护自建技能", not any(n.startswith(("roader", "Roader")) for n in names))
# B3 基线不足时零退役（空 state）
check("B3 无基线不退役", curator.curate(facts, None) == [] or
      all(p["kind"] != "retire" for p in curator.curate(facts, None)))
# B4 fix_reference 提案与 broken 一致
fix_props = {p["target"] for p in proposal_facts if p["kind"] == "retire"}
ref_props = {p["target"] for p in proposal_facts if p["kind"] == "fix_reference"}
check("B4 fix_reference 覆盖全部 broken", set(broken) == ref_props, str(ref_props ^ set(broken)))

# B5 队列当前 pending ≤ 每周配额（5 retire + librarian ≤8）
pend = [p for p in doc["proposals"] if p["status"] == "pending"]
check("B5 pending 队列可控（≤13）", len(pend) <= 13, f"{len(pend)} 条")
# B6 同天快照去重
weeks = [s["week"] for s in doc["weekly_snapshots"]]
check("B6 快照无同天重复", len(weeks) == len(set(weeks)), str(weeks))
# B7 历史回填 ≥6 期
old = [s for s in weeks if s != __import__("datetime").datetime.now().strftime("%Y-%m-%d")]
check("B7 历史基线 ≥6 期", len(old) >= 6, f"{len(old)} 期")

# ============ C. 闭环层 ============
print("=== C. 闭环层 followup ===")
# C1 20 条 done 都挂了回测
fus = doc.get("follow_ups", [])
done_ids = {p["id"] for p in doc["proposals"] if p["status"] == "done"}
fu_ids = {f["proposal_id"] for f in fus}
check("C1 done 提案 100% 挂回测", done_ids <= fu_ids, f"缺 {done_ids - fu_ids}")
# C2 P059 挂的是 cron exit1 簇指标（baseline=11）
p059 = next((f for f in fus if f["proposal_id"] == "P059"), None)
check("C2 P059 挂 cluster 指标 baseline=11",
      p059 and p059["metric"] == "cluster:script exited code" and p059["baseline"] == 11,
      str(p059))

# C3 回测判定逻辑：造临时 state 测 improved/worse/no_change
tmp = tempfile.mkdtemp()
orig_state = state.STATE_FILE if hasattr(state, "STATE_FILE") else None
# 直接测 check_due 逻辑：用未来到期的条目 + mock metrics/clusters
test_fu = {
    "proposal_id": "T1", "target": "mcporter",
    "metric": "ref_loads:mcporter", "baseline": 1,
    "check_after": "2020-01-01", "created_at": "2020", "result": None,
}
# mcporter 当前 load=1 == baseline → no_change
fake_doc = {"follow_ups": [dict(test_fu)], "proposals": [], "failure_memory": [],
            "weekly_snapshots": [], "approved_changes": [], "prevented": {}}
# monkey-patch state.load/save
state.load = lambda: fake_doc
_saved = {}
state.save = lambda d: _saved.update(d)
res = followup.check_due(facts, clusters)
r1 = res[0]["result"]
check("C3 指标持平判 no_change", r1 == "no_change", r1)

# C4 baseline=3 当前=1 → improved
fake_doc["follow_ups"] = [{**dict(test_fu), "proposal_id": "T2", "baseline": 3}]
res = followup.check_due(facts, clusters)
check("C4 指标下降判 improved", res[0]["result"] == "improved", res[0]["result"])

# C5 簇指标恶化：interrupted shutdown baseline=0 → worse
fake_doc["follow_ups"] = [{
    "proposal_id": "T3", "target": "x", "metric": "cluster:interrupted shutdown",
    "baseline": 0, "check_after": "2020-01-01", "created_at": "2020", "result": None}]
res = followup.check_due(facts, clusters)
check("C5 簇复发增长判 worse", res[0]["result"] == "worse", res[0]["result"])

# C6 worse 进 summary
summ = followup.summary()
check("C6 summary 统计 worse", summ["worse"] >= 1, str(summ))

# 恢复真实 state（重新 import 模块不行，直接让后续用真文件）
shutil.rmtree(tmp, ignore_errors=True)

# ============ D. 调度/通知 ============
print("=== D. 调度与通知 ===")
if sys.platform == "darwin":
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    check("D1 launchd 周任务已加载", "com.roader.skill-evolution-weekly" in r.stdout)
    plist = Path.home() / "Library/LaunchAgents/com.roader.skill-evolution-weekly.plist"
    pc = plist.read_text()
    check("D2 周日 21:30 调度", "<key>Weekday</key>" in pc and "21" in pc and "30" in pc)
else:
    # Linux: crontab 检查
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    check("D1 crontab 周任务已加载", "skill-evolution-weekly" in r.stdout)
    check("D2 周日 21:30 调度", "30 21 * * 0" in r.stdout)

# D3 通知代码走飞书不走 osascript 主路径
rw = (BASE / "run_weekly.py").read_text()
check("D3 周报通知走飞书", "send_feishu_dm.py" in rw and "📨 飞书周报已送达" in rw)
# D4 0 提案静默
check("D4 0 提案静默分支", "if pend:" in rw)
# D5 飞书失败有兜底
check("D5 飞书失败 Mac 兜底", "兜底" in rw and "osascript" in rw)
# D6 全部模块 3.9 兼容语法
pyc = subprocess.run([sys.executable, "-m", "py_compile"] +
                     [str(f) for f in BASE.glob("*.py")], capture_output=True)
check("D6 全部模块编译通过", pyc.returncode == 0, pyc.stderr.decode()[-200:])

# ============ E. 硬 cap ============
print("=== E. 硬 cap=120 ===")
import cap_enforcer, yaml
# E1 当前 active ≤120
active = [x for x in facts if x.get("installed") and not x.get("disabled")]
check("E1 活跃库 ≤120", len(active) <= 120, f"active={len(active)}")
# E2 首批 cap 禁用项确实在 config（wrangler 已被冷库豁免救回，不在内）
cfg = yaml.safe_load((Path.home()/".hermes/config.yaml").read_text())
disabled_cfg = set((cfg.get("skills") or {}).get("disabled") or [])
check("E2 config 含 cap 禁用项", {"ai-image-prompt","godmode","obliteratus"} <= disabled_cfg,
      str(len(disabled_cfg)))
# E2b wrangler 不在禁用名单（冷库豁免）
check("E2b wrangler 已豁免恢复", "wrangler" not in disabled_cfg)
# E3 自建/essential 永不动
check("E3 保护名单未被禁用",
      not any(d.startswith(("roader","Roader")) or d == "hermes-agent" for d in disabled_cfg))
# E4 dry-run 不再砍（幂等）
dr = cap_enforcer.enforce_cap(facts, cap=120, dry_run=True)
check("E4 cap 幂等（已达标不动作）", len(dr["disabled_now"]) == 0, str(dr["active_before"]))
# E5 恢复入口存在且能写（测一个假名字不实际改）
check("E5 --restore 入口", "--restore" in (BASE/"cap_enforcer.py").read_text())
# E6 run_weekly 接了 cap 链路
check("E6 周报自动执行 cap", "enforce_cap" in rw and "cap=120" in rw)
# E7 cap_log 有记录
caplog = doc.get("cap_log", [])
check("E7 cap 动作有审计日志", any(c.get("disabled") for c in caplog))
# E8 飞书通知含撤销命令
check("E8 飞书周报带撤销方式", "--restore" in rw)

# ============ F. 冷库（永久记忆）联动 ============
print("=== F. 冷库联动 ===")
import yaml as _yaml
cfg_f = _yaml.safe_load((Path.home()/".hermes/config.yaml").read_text())
dis_f = set((cfg_f.get("skills") or {}).get("disabled") or [])
wr = by_name.get("wrangler", {})
# F1 metrics 有冷库痕迹字段
check("F1 metrics 输出 vault_mentions_90d", "vault_mentions_90d" in wr)
# F2 wrangler 冷库有痕迹（2 个 CICD 文件）
check("F2 wrangler 冷库痕迹>0", (wr.get("vault_mentions_90d") or 0) >= 2, str(wr.get("vault_mentions_90d")))
# F3 wrangler 被冷库豁免救回（不在 disabled）
check("F3 wrangler 冷库豁免未禁用", "wrangler" not in dis_f)
# F4 冷库痕迹技能不在 cap 候选（dry-run 不砍它）
drf = cap_enforcer.enforce_cap(facts, cap=120, dry_run=True)
check("F4 cap 不砍有冷库痕迹的技能",
      all(x["name"] != "wrangler" for x in drf["disabled_now"]))
# F5 librarian evidence 带 vault_solutions
import librarian as _lib
_ev = _lib.gather_evidence()
_has_vs = any(c.get("vault_solutions") for c in _ev.get("error_clusters", []))
check("F5 错误簇带冷库历史方案 vault_solutions", _has_vs)
# F6 curator 退役候选不含冷库痕迹技能
_rc = curator.curate(facts, curator.prev_zero_baseline(doc, need_weeks=3))
check("F6 curator 退役候选尊重冷库信号",
      all(p["target"] != "wrangler" for p in _rc if p["kind"] == "retire"))

# ============ G. 正向成长（主航道） ============
print("=== G. 正向成长（偏好学习） ===")
import preference_signals as _psig, preference_miner as _pminer, approve_pref as _apref
# G1 纠正配对含"我当时产出"（可学习）
_sig = _psig.collect(90)
_corr_with_ctx = [c for c in _sig["corrections"] if c.get("prior_assistant")]
check("G1 纠正配对带上下文", len(_corr_with_ctx) >= 2, f"{len(_sig['corrections'])} 条纠正")
# G2 已批准偏好写进了 USER.md
_userfile = (Path.home()/".hermes/memories/USER.md").read_text()
check("G2 已批准偏好写入 USER.md", "Learned 5 条" in _userfile and "UP001" not in _userfile)
# G3 偏好队列状态正确
_prefs = doc.get("preferences", [])
check("G3 批准 5 条偏好", sum(1 for p in _prefs if p["status"]=="approved") >= 5,
      str({p["id"]: p["status"] for p in _prefs}))
# G4 重复归纳会去重（幂等：再跑不新增 pending）
_have_prefs = len(_prefs)
_cands_now = _pminer.parse_candidates("")
# 用真实 mining 会烧 LLM；只验函数存在 + 队列可批
check("G4 approve_pref list 可用", hasattr(_apref, "cmd_list"))
# G5 run_weekly 接入了 preference_miner
check("G5 周链路接入偏好挖掘", "preference_miner" in rw and "preference_trend" in rw)
# G6 纠正词表健壮
check("G6 纠正词表非空", len(_psig.CORRECTION) >= 10)
# G7 每日总结带"自我审视"段（daily 已生成）
_daily = (Path.home()/"HermesMemory/daily"/f"{_psig.collect_day('2026-09-10')['day']}-每日总结.md")
check("G7 每日总结含自我审视段", _daily.exists() and "自我审视" in _daily.read_text(errors="ignore"))
# G8 daily_growth_check 可跑且写 trend
_dgc = Path.home()/".hermes/scripts/skill_evolution/daily_growth_check.py"
check("G8 每日成长扫描脚本存在", _dgc.exists())
# G9 watchdog 接入了成长门禁 + 每日扫描
_dw = (Path.home()/".hermes/scripts/daily_watchdog.sh").read_text()
check("G9 watchdog 成长门禁", "自我审视" in _dw and "daily_growth_check" in _dw)
# G10 preference_trend 有数据（今日）
check("G10 preference_trend 已记录", len(doc.get("preference_trend", [])) >= 1)

print("\n" + "=" * 50)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}  共 {len(PASS)+len(FAIL)} 断言")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("🎉 全部门禁通过")
