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
            "session_id": codex_session, "cwd": "/tmp/Hermes-Mind-v2", "source": "cli"
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

    codex_maintenance = scripts / "codex_memory_maintenance.sh"
    cm = subprocess.run(["bash", str(codex_maintenance)], env=env,
                         capture_output=True, text=True)
    check(cm.returncode == 0, "Codex 结构化记忆维护入口真实执行退出 0")
    codex_cards = list((vault / "codex" / "sessions" / day).glob("*/memory.md"))
    card_text = codex_cards[0].read_text() if len(codex_cards) == 1 else ""
    check("结构化 Codex 记忆维护链路" in card_text,
          "Codex 维护入口生成按会话记忆卡")
    check("没有找到可独立核验的工具输出" in card_text,
          "task_complete 生命周期事件不冒充独立工具验证")

    codex_standalone_home = vault / "codex"
    codex_log = codex_standalone_home / "logs" / "codex_memory.log"
    lock = codex_standalone_home / "locks" / "codex_memory.lock"
    lock.mkdir(parents=True, exist_ok=True)
    (lock / "pid").write_text(str(os.getpid()), encoding="utf-8")
    locked = subprocess.run(["/bin/bash", str(codex_maintenance)], env=env,
                            capture_output=True, text=True)
    check(locked.returncode == 0 and "already running" in codex_log.read_text(),
          "并行维护遇到活锁时静默跳过，避免并发重写 Vault")

    (lock / "pid").write_text("999999", encoding="utf-8")
    stale = subprocess.run(["/bin/bash", str(codex_maintenance)], env=env,
                           capture_output=True, text=True)
    check(stale.returncode == 0 and not lock.exists(),
          "陈旧维护锁可被安全回收")

    # Standalone isolation: install the Codex-owned wrapper/bin layout and then
    # simulate Hermes uninstallation by renaming the temporary ~/.hermes away.
    standalone_bin = codex_standalone_home / "bin"
    standalone_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scripts" / "codex_memory.py", standalone_bin / "codex_memory.py")
    shutil.copy2(ROOT / "scripts" / "codex_memory_maintenance.sh", standalone_bin / "codex_memory_maintenance.sh")
    shutil.copy2(ROOT / "scripts" / "codex_run_maintenance.sh", codex_standalone_home / "run_maintenance.sh")
    for standalone_path in (
        standalone_bin / "codex_memory.py",
        standalone_bin / "codex_memory_maintenance.sh",
        codex_standalone_home / "run_maintenance.sh",
    ):
        standalone_path.chmod(0o755)

    standalone_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("HERMES_")
    }
    standalone_env.update({
        "HOME": str(home),
        "CODEX_HOME": str(codex_home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    })
    removed_hermes = home / ".hermes-removed-by-test"
    if removed_hermes.exists():
        shutil.rmtree(removed_hermes)
    hermes.rename(removed_hermes)
    try:
        check(not hermes.exists(), "隔离测试已模拟 ~/.hermes 不存在")
        standalone = subprocess.run(
            ["/bin/bash", str(codex_standalone_home / "run_maintenance.sh")],
            env=standalone_env, capture_output=True, text=True, cwd=base
        )
        check(standalone.returncode == 0,
              f"~/.hermes 不存在时独立 Codex wrapper 仍退出 0: {standalone.stderr}")
        maintenance_lines = [
            line for line in (codex_standalone_home / "maintenance.log").read_text().splitlines()
            if line.strip()
        ]
        check(maintenance_lines[-1].endswith("OK codex structured memory maintenance"),
              "独立 Codex wrapper 写入成功标记")
        check(str(standalone_bin / "codex_memory.py") in codex_log.read_text(),
              "独立维护使用 codex/bin 下的脚本，而不是 ~/.hermes")
    finally:
        removed_hermes.rename(hermes)

print("运行态仿真全部通过")
