#!/usr/bin/env python3
"""运行态仿真：隔离 HOME 中执行已安装脚本并验证真实产物。"""
import os
import json
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


with tempfile.TemporaryDirectory(prefix="hermes-runtime-") as td:
    base = Path(td)
    home = base / "home"
    hermes = home / ".hermes"
    vault = home / "HermesMemory"
    scripts = hermes / "scripts"
    (hermes / "cron").mkdir(parents=True)
    vault.mkdir(parents=True)
    scripts.mkdir(parents=True)
    shutil.copytree(ROOT / "scripts", scripts, dirs_exist_ok=True)

    codex_home = home / ".codex"
    codex_archive = codex_home / "archived_sessions"
    codex_archive.mkdir(parents=True)
    codex_session = "33333333-3333-4333-8333-333333333333"
    codex_file = codex_archive / "rollout-runtime.jsonl"
    codex_records = [
        {"timestamp": "2026-09-14T10:00:00+08:00", "type": "session_meta", "payload": {
            "session_id": codex_session, "cwd": "/tmp/xxzAgentMemory", "source": "cli"
        }},
        {"timestamp": "2026-09-14T10:00:01+08:00", "type": "response_item", "payload": {
            "type": "message", "id": "codex-user", "role": "user",
            "content": [{"type": "input_text", "text": "请验证结构化 Codex 记忆维护链路"}]
        }},
        {"timestamp": "2026-09-14T10:00:02+08:00", "type": "response_item", "payload": {
            "type": "message", "id": "codex-assistant", "role": "assistant",
            "content": [{"type": "output_text", "text": "已完成结构化记忆维护并验证产物。"}]
        }},
        {"timestamp": "2026-09-14T10:00:03+08:00", "type": "event_msg", "payload": {
            "type": "task_complete", "turn_id": "runtime-turn"
        }},
    ]
    codex_file.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in codex_records))

    db = hermes / "state.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE sessions (
      id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL,
      message_count INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0,
      title TEXT, archived INTEGER DEFAULT 0
    );
    CREATE TABLE messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
      role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL,
      active INTEGER DEFAULT 1
    );
    """)
    day = "2026-09-14"
    start = time.mktime(time.strptime(day, "%Y-%m-%d"))
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                ("real-1", "codex", start + 3600, 4, 2, "仿真修复任务", 0))
    con.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,?)",
                ("real-1", "user", "请修复仿真链路并验证本地运行", start + 3601))
    con.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,?)",
                ("real-1", "assistant", "已修复运行链路，结论是本地仿真通过。", start + 3602))
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                ("noise-1", "codex", start + 7200, 2, 0, "噪声会话", 0))
    # 广告/营销邮件会话（品牌强词 + HTML 邮件正文，tools>0 不走极简噪声规则）
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                ("ad-1", "codex", start + 9000, 5, 2, "前程无忧 每日职位推荐", 0))
    con.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,?)",
                ("ad-1", "user",
                 "<html><body><table><tr><td>【免费直播】今晚八点职位推荐直播预告，"
                 "点击查看 <a href=\"https://example.com/unsubscribe\">unsubscribe 退订</a></td></tr></table></body></html>",
                 start + 9001))
    # 正常业务讨论：含 edm/邮件营销/退订率 弱词但无邮件结构，不得误杀
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                ("biz-1", "codex", start + 10800, 8, 4, "EDM渠道ROI复盘", 0))
    con.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,?)",
                ("biz-1", "user",
                 "复盘EDM渠道ROI，讨论邮件营销和退订率指标怎么算，顺便看取消订阅率",
                 start + 10801))
    con.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,?)",
                ("biz-1", "assistant", "已确认：本周 EDM 渠道 ROI 分析口径已统一并产出结论。",
                 start + 10802))
    con.commit(); con.close()

    env = {**os.environ, "HOME": str(home), "HERMES_HOME": str(hermes),
           "HERMES_VAULT": str(vault), "DATE_OVERRIDE": day, "NO_LLM": "1",
           "CODEX_HOME": str(codex_home),
           "PYTHONPATH": str(scripts / "skill_evolution")}
    summary = scripts / "daily_summary_from_db.py"
    result = subprocess.run(["python3", str(summary)], env=env,
                            capture_output=True, text=True, cwd=base)
    check(result.returncode == 0, "已安装总结脚本在仿真 state.db 上退出 0")
    report = vault / "daily" / f"{day}-每日总结.md"
    check(report.exists(), "运行态生成每日总结文件")
    text = report.read_text()
    check("仿真修复任务" in text and "请修复仿真链路" in text,
          "总结包含真实会话用户原话和标题")
    check("噪声会话" not in text and "未经模型润色" in text,
          "噪声过滤和 NO_LLM 降级证据版生效")
    check("噪声会话" not in text and "未经模型润色" in text,
          "噪声过滤和 NO_LLM 降级证据版生效")
    check("前程无忧" not in text and "unsubscribe" not in text,
          "广告/营销邮件会话整体不进入日报")
    # 自进化系统自身的 LLM 调用会话（skill-evolution-*/preference-miner）不进日报（防串台）
    con = sqlite3.connect(db)
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                ("sys-1", "skill-evolution-librarian", start + 12600, 6, 0,
                 "技能改进提案生成", 0))
    con.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,?)",
                ("sys-1", "user", "基于本周证据生成技能改进提案，覆盖所有复发簇", start + 12601))
    con.commit(); con.close()
    result2 = subprocess.run(["python3", str(summary)], env=env,
                             capture_output=True, text=True, cwd=base)
    check(result2.returncode == 0, "加入系统源会话后总结脚本仍退出 0")
    check("技能改进提案生成" not in (vault / "daily" / f"{day}-每日总结.md").read_text(),
          "自进化系统自身调用会话不进日报（防串台）")

    # ---- 免飞书审批流（Obsidian 勾选 → approvals.py 拾取执行）----
    sk_dir = hermes / "skill_evolution"
    sk_dir.mkdir(parents=True, exist_ok=True)
    (sk_dir / "state.json").write_text(json.dumps({
        "version": 1, "proposals": [
            {"id": "P900", "kind": "enhance", "target": "sandbox-target",
             "reason": "仿真审批", "confidence": "medium", "status": "pending"},
            {"id": "P901", "kind": "retire", "target": "sandbox-dead",
             "reason": "仿真驳回", "confidence": "medium", "status": "pending"},
        ], "approved_changes": [], "follow_ups": [],
    }, ensure_ascii=False), encoding="utf-8")
    approvals_py = scripts / "skill_evolution" / "approvals.py"
    env_ap = {**env}
    r0 = subprocess.run(["python3", str(approvals_py), "render"], env=env_ap,
                        capture_output=True, text=True, cwd=base)
    check(r0.returncode == 0, "approvals render 退出 0")
    ap_file = vault / "skill-evolution" / "APPROVALS.md"
    check(ap_file.exists() and "P900" in ap_file.read_text(),
          "APPROVALS.md 已生成且包含待审批提案")
    # 勾选：P900 批准、P901 驳回
    t = ap_file.read_text().replace("- [ ] P900", "- [x] P900").replace("- [ ] P901", "- [-] P901")
    ap_file.write_text(t, encoding="utf-8")
    r1 = subprocess.run(["python3", str(approvals_py), "process"], env=env_ap,
                        capture_output=True, text=True, cwd=base)
    check(r1.returncode == 0, "approvals process 退出 0")
    st = json.loads((sk_dir / "state.json").read_text())
    stmap = {x["id"]: x["status"] for x in st["proposals"]}
    check(stmap.get("P900") == "approved", "勾选批准 → 非 retire 提案置 approved 待执行")
    check(stmap.get("P901") == "rejected", "勾选驳回 → 提案置 rejected")
    # 二次勾选 P900 = 标记 done（执行完成）
    t2 = ap_file.read_text().replace("- [ ] P900", "- [x] P900")
    ap_file.write_text(t2, encoding="utf-8")
    r2 = subprocess.run(["python3", str(approvals_py), "process"], env=env_ap,
                        capture_output=True, text=True, cwd=base)
    check(r2.returncode == 0, "二次 process 退出 0")
    st2 = json.loads((sk_dir / "state.json").read_text())
    stmap2 = {x["id"]: x["status"] for x in st2["proposals"]}
    check(stmap2.get("P900") == "done", "已批准提案再勾选 → 标记 done")
    check("EDM渠道ROI复盘" in text,
          "弱广告词的正常业务讨论不被误杀")

    # 广告过滤两级特征的函数级回归（强词命中 / 弱词必须叠加邮件结构）
    import importlib.util
    _spec = importlib.util.spec_from_file_location("ds_under_test", summary)
    _ds = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_ds)
    check(_ds.is_noise("【免费直播】职位推荐", 9, 3, "直播预告 Boss直聘"),
          "回归：强广告词会话判噪声")
    check(not _ds.is_noise("优化邮件指标", 12, 5, "分析本月edm退订率和邮件营销转化"),
          "回归：纯文本EDM业务讨论不判噪声")
    check(_ds.is_noise("EDM October offers", 9, 3,
                       'Click here to <a href="https://x/u">unsubscribe</a> from this email'),
          "回归：HTML 结构营销邮件判噪声")
    check(_ds.denoise("普通业务讨论" * 20) and not _ds.denoise("普通业务讨论" * 20).startswith("[广告"),
          "回归：普通长文本不被降噪误压")

    archive = scripts / "smart_archive.sh"
    content = "## 摘要\n仿真验证已完成并产出文件。\n\n## 完成内容\n运行态测试。"
    ar = subprocess.run(["bash", str(archive), "运行态仿真", content, "incidents"],
                        env=env, capture_output=True, text=True)
    check(ar.returncode == 0, "归档脚本真实写入退出 0")
    files = list((vault / "incidents").glob("*.md"))
    check(len(files) == 1 and "仿真验证已完成" in files[0].read_text(),
          "归档产物存在且内容完整")

    bad = subprocess.run(["bash", str(archive), "拒绝测试", "无摘要"],
                         env=env, capture_output=True, text=True)
    check(bad.returncode != 0, "缺摘要输入被运行态拒绝")

    adapter = subprocess.run(["python3", str(scripts / "adapters/agent_adapter.py")],
                             env={**env, "AGENT_TYPE": "generic"},
                             capture_output=True, text=True)
    check(adapter.returncode == 0, "generic 适配层真实执行退出 0")
    codex_memory_home = home / "CodexMemory"
    standalone_bin = codex_memory_home / "bin"
    standalone_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scripts" / "codex_memory.py", standalone_bin / "codex_memory.py")
    shutil.copy2(ROOT / "scripts" / "codex_memory_maintenance.sh", standalone_bin / "codex_memory_maintenance.sh")
    shutil.copy2(ROOT / "scripts" / "codex_run_maintenance.sh", codex_memory_home / "run_maintenance.sh")
    for standalone_path in (
        standalone_bin / "codex_memory.py",
        standalone_bin / "codex_memory_maintenance.sh",
        codex_memory_home / "run_maintenance.sh",
    ):
        standalone_path.chmod(0o755)

    codex_log = codex_memory_home / "logs" / "codex_memory.log"
    codex_maintenance = standalone_bin / "codex_memory_maintenance.sh"
    standalone_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("HERMES_") and key != "CODEX_MEMORY_HOME"
    }
    standalone_env.update({
        "HOME": str(home),
        "CODEX_HOME": str(codex_home),
        "CODEX_MEMORY_HOME": str(codex_memory_home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    })

    cm = subprocess.run(["bash", str(codex_maintenance)], env=standalone_env,
                         capture_output=True, text=True)
    check(cm.returncode == 0, "Codex 独立维护入口真实执行退出 0")
    codex_cards = list((codex_memory_home / "sessions" / day).glob("*/memory.md"))
    card_text = codex_cards[0].read_text() if len(codex_cards) == 1 else ""
    check("结构化 Codex 记忆维护链路" in card_text,
          "Codex 维护入口在 ~/CodexMemory 生成按会话记忆卡")
    check("没有找到可独立核验的工具输出" in card_text,
          "task_complete 生命周期事件不冒充独立工具验证")
    check(not (vault / "codex").exists(), "Codex 记忆没有写入 HermesMemory/codex")

    lock = codex_memory_home / "locks" / "codex_memory.lock"
    lock.mkdir(parents=True, exist_ok=True)
    (lock / "pid").write_text(str(os.getpid()), encoding="utf-8")
    locked = subprocess.run(["/bin/bash", str(codex_maintenance)], env=standalone_env,
                            capture_output=True, text=True)
    check(locked.returncode == 0 and "already running" in codex_log.read_text(),
          "并行维护遇到活锁时静默跳过，避免并发重写 CodexMemory")

    (lock / "pid").write_text("999999", encoding="utf-8")
    stale = subprocess.run(["/bin/bash", str(codex_maintenance)], env=standalone_env,
                           capture_output=True, text=True)
    check(stale.returncode == 0 and not lock.exists(),
          "陈旧维护锁可被安全回收")

    # Full isolation: simulate removal of both Hermes runtime and Hermes vault.
    removed_hermes = home / ".hermes-removed-by-test"
    removed_vault = home / "HermesMemory-removed-by-test"
    if removed_hermes.exists():
        shutil.rmtree(removed_hermes)
    if removed_vault.exists():
        shutil.rmtree(removed_vault)
    hermes.rename(removed_hermes)
    vault.rename(removed_vault)
    try:
        check(not hermes.exists() and not vault.exists(),
              "隔离测试已模拟 ~/.hermes 与 ~/HermesMemory 均不存在")
        standalone = subprocess.run(
            ["/bin/bash", str(codex_memory_home / "run_maintenance.sh")],
            env=standalone_env, capture_output=True, text=True, cwd=base
        )
        check(standalone.returncode == 0,
              f"Hermes 和 HermesMemory 不存在时独立 Codex wrapper 仍退出 0: {standalone.stderr}")
        maintenance_lines = [
            line for line in (codex_memory_home / "maintenance.log").read_text().splitlines()
            if line.strip()
        ]
        check(maintenance_lines[-1].endswith("OK codex structured memory maintenance"),
              "独立 Codex wrapper 写入成功标记")
        check(str(standalone_bin / "codex_memory.py") in codex_log.read_text(),
              "独立维护使用 CodexMemory/bin 下的脚本，而不是 Hermes 目录")
    finally:
        removed_vault.rename(vault)
        removed_hermes.rename(hermes)

print("运行态仿真全部通过")
