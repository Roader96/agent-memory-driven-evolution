#!/usr/bin/env python3
"""agent_adapter.py — Agent 适配层（跨 agent 兼容）

目标：让本项目的自进化系统不绑定任何单一 agent。
当前官方实现：Hermes（hermes-agent）。
其他 agent（Claude Code / Codex / Cursor / 自定义）通过此适配层使用。

使用方式（环境变量）：
  AGENT_TYPE=auto|hermes|generic     # 默认 auto 自动检测
  AGENT_LLM=<command>                # generic 模式的 LLM 调用命令（默认 llm-cli）
  HERMES_BIN=<path>                  # 显式指定 hermes 可执行文件
  HERMES_HOME=<dir>                  # hermes 主目录（默认 ~/.hermes）
  MEMORY_DIR=<dir>                   # 记忆目录（默认 <HERMES_HOME>/memories 或 ~/.hermes/memories）

适配层提供的三大能力：
  1. detect()      — 检测当前 agent 环境
  2. state_db()    — 对话/技能使用历史数据源（Hermes: state.db；其他: 通用 JSON/文件降级）
  3. llm()         — LLM 调用（Hermes: hermes chat --source；其他: 外部命令/降级）
  4. archive()     — 会话归档（Hermes: hermes sessions archive；其他: 文件移动）

降级原则：任何依赖失败时优雅降级到通用模式，绝不因缺 Hermes 就崩溃。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

# HOME 优先读 $HOME 环境变量（门禁/测试隔离需要）；否则 fallback Path.home()
HOME = Path(os.environ.get("HOME", str(Path.home())))

# ─── 环境检测 ────────────────────────────────────────────────

def detect() -> str:
    """返回 'hermes' | 'generic'。auto 模式按环境变量/文件系统推断。"""
    t = os.environ.get("AGENT_TYPE", "auto").lower()
    if t in ("hermes", "generic"):
        return t

    # 自动检测：以"有没有 Hermes 的记忆数据"为准（state.db / HERMES_HOME 目录）
    # 仅 PATH 里有 hermes 二进制不算——其他 agent 用户可能也装了 hermes CLI。
    h = _hermes_home()
    if (h / "state.db").exists():
        return "hermes"
    if os.environ.get("HERMES_HOME") and h.exists():
        return "hermes"
    return "generic"


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(HOME / ".hermes")))


def _hermes_bin() -> str:
    """候选 hermes 可执行文件路径（按优先级）。"""
    if os.environ.get("HERMES_BIN"):
        return os.environ["HERMES_BIN"]
    candidates = [
        _hermes_home() / "hermes-agent" / "venv" / "bin" / "hermes",
        _hermes_home() / "bin" / "hermes",
        Path(HOME) / ".local" / "bin" / "hermes",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("hermes") or ""


def hermes_bin() -> str:
    return os.environ.get("HERMES_BIN") or _hermes_bin()


# ─── 数据源 ──────────────────────────────────────────────────

def state_db_path() -> Path:
    """Hermes 的会话/技能统计数据库。"""
    p = Path(os.environ.get("STATE_DB", str(_hermes_home() / "state.db")))
    return p if p.exists() else (_hermes_home() / "state.db")


def connect_state_db() -> sqlite3.Connection | None:
    """只读打开 Hermes state.db；不存在/打不开返回 None（调用方降级）。"""
    if detect() != "hermes":
        return None
    try:
        return sqlite3.connect(f"file:{state_db_path()}?mode=ro", uri=True)
    except Exception:
        return None


def memories_dir() -> Path:
    """记忆目录（USER.md/MEMORY.md 所在）。"""
    d = os.environ.get("MEMORY_DIR", str(_hermes_home() / "memories"))
    return Path(d)


# ─── LLM ─────────────────────────────────────────────────────

def llm_call(prompt: str, *, source: str = "adapter", timeout: int = 120,
             query_file: bool = False) -> str:
    """单次 LLM 调用。

    Hermes 环境：hermes chat --source=<source> -p "<prompt>"（query_file=True 时用
    --query-file，避免会话污染，适合批量/提取类调用）
    其他环境：执行 AGENT_LLM 环境变量指定的命令（默认 llm-cli），stdin 传 prompt，stdout 取结果。
    失败/未配置：返回空串（调用方应降级处理）。
    """
    agent = detect()
    if agent == "hermes":
        return _llm_hermes(prompt, source=source, timeout=timeout, query_file=query_file)
    return _llm_generic(prompt, timeout=timeout)


def _llm_hermes(prompt: str, *, source: str, timeout: int, query_file: bool = False) -> str:
    bin_ = hermes_bin()
    if not bin_ or not Path(bin_).exists():
        return ""
    try:
        if query_file:
            import tempfile
            qf = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            qf.write(prompt); qf.close()
            try:
                p = subprocess.run(
                    [bin_, "chat", "-Q", "--oneshot", "--cli",
                     "--source", source, "--query-file", qf.name],
                    capture_output=True, text=True, timeout=timeout,
                )
                if p.returncode == 0:
                    return "\n".join(
                        ln for ln in p.stdout.splitlines()
                        if not ln.strip().startswith(("session_id:", "Warning:"))
                    ).strip()
                return ""
            finally:
                try: os.unlink(qf.name)
                except OSError: pass
        p = subprocess.run(
            [bin_, "chat", "--source", source, "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
        )
        if p.returncode == 0:
            return p.stdout.strip()
        return ""
    except Exception:
        return ""


def _llm_generic(prompt: str, *, timeout: int) -> str:
    cmd = os.environ.get("AGENT_LLM", "llm-cli")
    # 安全：默认 shlex.split + shell=False（环境变量内容不得决定是否过 shell，
    # 防意外展开/参数注入）；显式 AGENT_LLM_SHELL=1 才允许 shell 风格命令
    use_shell = os.environ.get("AGENT_LLM_SHELL") == "1"
    argv = cmd if use_shell else __import__("shlex").split(cmd)
    if not argv:
        return ""
    try:
        p = subprocess.run(
            argv,
            input=prompt, capture_output=True, text=True, timeout=timeout,
            shell=use_shell,
        )
        if p.returncode == 0:
            # 输出大小限制 4MB（防恶意/失控输出撑爆内存）
            return p.stdout[:4 * 1024 * 1024].strip()
        return ""
    except Exception:
        return ""


# ─── 会话归档 ────────────────────────────────────────────────

def archive_session(source: str, session_id: str | None = None) -> bool:
    """归档一个会话（或按 source 归档）。

    Hermes：hermes sessions archive --source <source> [--session <id>] --yes
    其他：把源会话目录的内容移到归档目录（幂等）。
    """
    agent = detect()
    if agent == "hermes":
        return _archive_hermes(source, session_id)
    return _archive_generic(source, session_id)


def _archive_hermes(source: str, session_id: str | None) -> bool:
    bin_ = hermes_bin()
    if not bin_ or not Path(bin_).exists():
        return False
    cmd = [bin_, "sessions", "archive", "--source", source]
    if session_id:
        cmd += ["--session", session_id]
    cmd.append("--yes")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.returncode == 0
    except Exception:
        return False


def _archive_generic(source: str, session_id: str | None) -> bool:
    """无 hermes 时：把 ~/.hermes/sessions/<source> 下会话移到 archived/（幂等）。"""
    sess_dir = _hermes_home() / "sessions"
    dst_dir = _hermes_home() / "archived_sessions"
    if not sess_dir.exists():
        return False
    try:
        target = sess_dir if not session_id else sess_dir / session_id
        if not target.exists():
            return False
        dst_dir.mkdir(parents=True, exist_ok=True)
        # 移动整个 source 目录或单个会话
        if (sess_dir / source).exists():
            shutil.move(str(sess_dir / source), str(dst_dir / source))
        elif target.is_file():
            shutil.move(str(target), str(dst_dir / target.name))
        else:
            shutil.move(str(target), str(dst_dir / target.name))
        return True
    except Exception:
        return False


# ─── 便捷查询 ────────────────────────────────────────────────

def generic_skill_facts() -> list:
    """通用技能统计（无 state.db 时）：从 skills 目录推断基本事实（名字/修改时间/大小）。

    注意：Hermes 模式下的精确统计（load_sessions 等）在 metrics.py 里实现
    （从 messages.tool_calls 解析 skill_view 调用），不属于适配层职责——
    适配层只提供连接/LLM/归档原语，业务统计留在业务模块。
    """
    skills_dir = _hermes_home() / "skills"
    out = []
    if not skills_dir.exists():
        return out
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir() or not (d / "SKILL.md").exists():
            continue
        mtime = d.stat().st_mtime
        age = (__import__("time").time() - mtime) / 86400
        out.append({
            "name": d.name,
            "load_sessions": 0,
            "self_errors": 0,
            "reload_sessions": 0,
            "edits": 0,
            # 关键：无真实使用数据时标 unknown，而不是"零使用"——
            # cap_enforcer/curator 必须据此禁止自动动作（伪零≠未使用）
            "usage_quality": "unknown",
            "age_days": age,
            "size_bytes": sum(f.stat().st_size for f in d.rglob("*") if f.is_file()),
            "disabled": False,
            "installed": True,
        })
    return out


def which_agent() -> str:
    """AGENT_TYPE 显式值 + 实际检测值。"""
    explicit = os.environ.get("AGENT_TYPE", "auto")
    detected = detect()
    return f"{explicit or 'auto'}→{detected}"


if __name__ == "__main__":
    print(f"agent={which_agent()} hermes_bin={hermes_bin()!r} state_db={state_db_path()}")