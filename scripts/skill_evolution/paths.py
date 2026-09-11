#!/usr/bin/env python3
"""paths.py — 路径配置单一来源（全项目唯一）

所有脚本的路径定义必须从这里取，禁止各自重复定义
（评价 P1-1：run_weekly.py 曾写死 Path.home()/"HermesMemory"，
 自定义 HERMES_VAULT 的用户周报会写错目录）。

环境变量优先级：
  HERMES_HOME  → 默认 ~/.hermes（agent 数据目录）
  HERMES_VAULT → 默认 ~/HermesMemory（记忆 vault）
  HOME         → 默认 Path.home()
"""
import os
from pathlib import Path

HOME = Path(os.environ.get("HOME", str(Path.home())))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(HOME / ".hermes")))
VAULT = Path(os.environ.get("HERMES_VAULT", str(HOME / "HermesMemory")))

# 常用子路径
SKILLS_DIR = HERMES_HOME / "skills"
STATE_DB = HERMES_HOME / "state.db"
MEMORIES_DIR = HERMES_HOME / "memories"
CHECKPOINTS = VAULT / ".checkpoints"


def self_prefixes() -> tuple:
    """自建技能保护前缀（可配置）：环境变量 SELF_SKILL_PREFIXES="user,myteam"（逗号分隔）。
    默认只保护 user- 前缀（本项目自建技能约定）；本地有个人前缀时自行追加。
    approve/curator/cap_enforcer/librarian 四处统一从这里取。"""
    return tuple(x.strip() for x in os.environ.get("SELF_SKILL_PREFIXES", "user").split(",") if x.strip())
