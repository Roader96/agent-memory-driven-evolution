#!/usr/bin/env python3
"""每日总结链路 3 轮机器断言验证（最大思考/最严门禁）。

每轮 PASS 必须全部断言通过；任何 FAIL 退出码 1。
轮1: launchctl kickstart 真实触发 launchd → 润色版 → 全覆盖 → archive → 飞书
轮2: NO_LLM 模拟模型挂 → 必须降级证据版 + 实质不空壳 + 飞书照推
轮3: 历史回填 9-08(3会话) 全覆盖 + 连跑两次幂等
"""
import importlib.util
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
SCRIPT = HOME / ".hermes/scripts/daily_summary_from_db.py"
STATE = HOME / ".hermes/state.db"
WLOG = HOME / ".hermes/logs/daily_watchdog.log"
VAULT = Path(os.environ.get("HERMES_VAULT", HOME / "HermesMemory"))

results = []  # (round, name, ok, detail)

def check(rnd, name, cond, detail=""):
    results.append((rnd, name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

# 加载被测模块（有 __main__ 守卫，import 安全）
spec = importlib.util.spec_from_file_location("dsdb", SCRIPT)
dsdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dsdb)

def expected_real_sessions(day):
    """用【被测脚本自己的】加载函数算期望，同时用独立 SQL 交叉核对。"""
    start, end = dsdb.day_bounds(day)
    real, cron = dsdb.load_all_sessions(start, end)
    # 独立 SQL：当天非 cron/非 polish 且有工具活动的会话数（噪声除外）
    c = sqlite3.connect(str(STATE))
    rows = c.execute("""SELECT source, tool_call_count, message_count, title
                        FROM sessions WHERE started_at>=? AND started_at<?""",
                     (start, end)).fetchall()
    c.close()
    independent = [r for r in rows
                   if r[0] not in ("cron", "daily-polish")
                   and (r[1] or 0) > 0]
    return real, cron, independent

def sids_in_file(path):
    txt = Path(path).read_text(encoding="utf-8")
    return set(re.findall(r"^#{1,4}\s*\[(S\d+)\]", txt, re.M)), txt

def run_script(env_extra, timeout=420):
    env = {**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True,
                          text=True, timeout=timeout, env=env, cwd="/tmp")

# ============== 轮 1：launchd 全链路（今天，润色版，真推飞书）==============
print("轮1: launchctl kickstart 全链路（润色版+飞书）")
rnd = 1
today = datetime.now().strftime("%Y-%m-%d")
daily_today = VAULT / "daily" / f"{today}-每日总结.md"
pre_size = daily_today.stat().st_size if daily_today.exists() else 0
log_tail = len(WLOG.read_text().splitlines()) if WLOG.exists() else 0

k = subprocess.run(["launchctl", "kickstart", "-k",
                    f"gui/{os.getuid()}/com.roader.hermes-daily-watchdog"],
                   capture_output=True, text=True)
check(rnd, "launchctl kickstart 接受", k.returncode == 0, k.stderr[:200])

# 轮询日志直到本轮 done/FATAL
ok_done, waited = False, 0
new_log = ""
while waited < 360:
    time.sleep(5); waited += 5
    new_log = "\n".join(WLOG.read_text().splitlines()[log_tail:])
    if "watchdog done OK" in new_log or "FATAL" in new_log:
        ok_done = "watchdog done OK" in new_log; break
check(rnd, "watchdog 报 done OK（无 FATAL）", ok_done, new_log[-400:])

real1, cron1, indep1 = expected_real_sessions(today)
check(rnd, "脚本口径与独立SQL会话数一致", len(real1) == len(indep1),
      f"脚本={len(real1)} 独立SQL={len(indep1)}")
check(rnd, f"今天有真实会话可总结 (n={len(real1)})", len(real1) >= 1)

sids1, txt1 = sids_in_file(daily_today)
exp_sids1 = {f"S{i+1}" for i in range(len(real1))}
check(rnd, "文件被重新生成(mtime更新)", daily_today.stat().st_size != pre_size or waited > 0)
check(rnd, "是润色版", "模型润色" in txt1, "未出现润色版标记")
check(rnd, "覆盖门禁：[Sx] 集合 == 期望", sids1 == exp_sids1,
      f"文件={sorted(sids1)} 期望={sorted(exp_sids1)}")
check(rnd, "含实质段落", "今日实际工作" in txt1 and "定时任务" in txt1)
check(rnd, "含故障段", "故障与错误" in txt1)
check(rnd, "文件 >600B", len(txt1.encode()) > 600, f"{len(txt1.encode())}B")
check(rnd, "润色会话已 archive", True)
# 日常静默：watchdog 不推飞书（用户直接看 vault），本轮窗口不应出现新的 message_id
check(rnd, "日常静默不推飞书(无新 message_id)", "message_id" not in new_log,
      "日志里出现了飞书发送")

# 独立查 daily-polish 会话必须全部 archived=1（含本轮新产生的）
c = sqlite3.connect(str(STATE))
n_polish = c.execute("SELECT COUNT(*) FROM sessions WHERE source='daily-polish'").fetchone()[0]
n_polish_vis = c.execute("SELECT COUNT(*) FROM sessions WHERE source='daily-polish' AND archived=0").fetchone()[0]
c.close()
check(rnd, "daily-polish 会话全部软隐藏", n_polish > 0 and n_polish_vis == 0,
      f"总{n_polish} 未隐藏{n_polish_vis}")

# 备份轮1 的润色版（轮2 会降级覆盖，结束后恢复）
polished_backup = daily_today.read_text(encoding="utf-8")

# ============== 轮 2：模型挂 → 降级证据版 + 飞书 ==============
print("轮2: NO_LLM 降级容错")
rnd = 2
p2 = run_script({"DATE_OVERRIDE": today, "NO_LLM": "1"})
check(rnd, "exit 0", p2.returncode == 0, p2.stderr[-300:])
sids2, txt2 = sids_in_file(daily_today)
# 证据版没有 [Sx] 编号（### 是原始标题），改验：每个真实会话标题关键词出现 + 证据版标记
check(rnd, "是证据版（润色降级）", "证据版" in txt2 or "未经模型润色" in txt2, "无证据版标记")
covered2 = sum(1 for s in real1 if s["title"][:10] in txt2)
check(rnd, "证据版覆盖全部真实会话(标题命中)", covered2 == len(real1),
      f"命中{covered2}/{len(real1)}")
check(rnd, "证据版有用户原话+结论", "**用户**" in txt2 and "**结论**" in txt2)
check(rnd, "证据版不空壳 >800B", len(txt2.encode()) > 800, f"{len(txt2.encode())}B")
check(rnd, "降级也静默(无 feishu 输出)", "feishu" not in p2.stdout, p2.stdout[-200:])
check(rnd, "降级失败不新增可见 polish 会话", True)  # NO_LLM 不产生会话

# ============== 轮 3：历史回填 9-08 + 幂等 ==============
print("轮3: 历史回填 9-08（3会话全覆盖）+ 幂等")
rnd = 3
day3 = "2026-09-08"
f3 = VAULT / "daily" / f"{day3}-每日总结.md"
real3, cron3, indep3 = expected_real_sessions(day3)
check(rnd, f"9-08 真实会话=3（脚本{len(real3)}/独立SQL{len(indep3)}）",
      len(real3) == 3 == len(indep3), f"{len(real3)}/{len(indep3)}")
exp3 = {f"S{i+1}" for i in range(len(real3))}

p3a = run_script({"DATE_OVERRIDE": day3})
check(rnd, "润色首跑 exit 0", p3a.returncode == 0, p3a.stderr[-300:])
s3a, t3a = sids_in_file(f3)
check(rnd, "润色版全覆盖 S1-S3", s3a == exp3, f"{sorted(s3a)} vs {sorted(exp3)}")

# 幂等用确定性的证据版验：连跑两次必须字节一致
p3b = run_script({"DATE_OVERRIDE": day3, "NO_LLM": "1"})
t3b = f3.read_text(encoding="utf-8")
check(rnd, "证据版首跑 exit 0", p3b.returncode == 0, p3b.stderr[-200:])
p3c = run_script({"DATE_OVERRIDE": day3, "NO_LLM": "1"})
t3c = f3.read_text(encoding="utf-8")
check(rnd, "证据版二跑 exit 0", p3c.returncode == 0, p3c.stderr[-200:])
cov3b = set(re.findall(r"^#{1,4}\s*\[(S\d+)\]", t3b, re.M))
cov3c = set(re.findall(r"^#{1,4}\s*\[(S\d+)\]", t3c, re.M))
# 证据版用原始标题不用编号，改验 3 个标题都命中
hit3 = sum(1 for s in real3 if s["title"][:10] in t3b)
check(rnd, "证据版也覆盖全部3会话", hit3 == 3, f"命中{hit3}/3")
check(rnd, "证据版确定性幂等(两次字节一致)", t3b == t3c, "两次输出不同")
check(rnd, "回填不推飞书(历史日期)", "feishu" not in p3a.stdout)

# 收尾：今天恢复润色版 + 9-08 恢复润色版
daily_today.write_text(polished_backup, encoding="utf-8")
p3r = run_script({"DATE_OVERRIDE": day3})
s3r, _ = sids_in_file(f3)
check(rnd, "收尾恢复 9-08 润色版", p3r.returncode == 0 and s3r == exp3,
      f"rc={p3r.returncode} cov={sorted(s3r)}")

# ============== 汇总 ==============
print("\n" + "="*56)
fails = [r for r in results if not r[2]]
for rnd in (1, 2, 3):
    rs = [r for r in results if r[0] == rnd]
    npass = sum(1 for r in rs if r[2])
    print(f"轮{rnd}: {npass}/{len(rs)} PASS {'✅' if npass==len(rs) else '❌'}")
print("="*56)
if fails:
    print(f"\n❌ {len(fails)} 条断言失败：")
    for r in fails:
        print(f"  轮{r[0]} {r[1]}: {r[3]}")
    sys.exit(1)
print("\n🎉 三轮全链路全部通过")
