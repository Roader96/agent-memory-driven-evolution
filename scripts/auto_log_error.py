#!/usr/bin/env python3
"""
auto_log_error.py - 全局错误自动记录
任何 python 脚本/agent 调一行就能记录错误到 errors.json
下次 vault_postprocess 自动汇总到 ERRORS.md
"""
import sys
import json
import traceback
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / "skill_evolution"))
import paths
from datetime import datetime

VAULT = paths.VAULT
ERROR_LOG = VAULT / ".checkpoints" / "errors.json"


def log_error(category: str, message: str, detail: str = ""):
    """记录一条错误"""
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    if ERROR_LOG.exists():
        try:
            errors = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
        except Exception:
            errors = []

    errors.append({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "category": category,
        "message": message,
        "detail": detail[:300] if detail else "",
    })

    errors = errors[-100:]  # 保留最近 100 条
    ERROR_LOG.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(errors)


def log_exception(category: str, prefix: str = ""):
    """捕获当前异常并记录"""
    exc_type, exc_value, exc_tb = sys.exc_info()
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    msg = f"{prefix}{exc_type.__name__}: {exc_value}" if prefix else f"{exc_type.__name__}: {exc_value}"
    return log_error(category, msg, tb)


# ============ CLI 模式 ============
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法:")
        print("  auto_log_error.py <category> <message> [detail]")
        print("  echo 'detail' | auto_log_error.py <category> <message>")
        sys.exit(1)

    cat = sys.argv[1]
    msg = sys.argv[2]
    detail = sys.stdin.read().strip() if not sys.stdin.isatty() else (sys.argv[3] if len(sys.argv) > 3 else "")

    n = log_error(cat, msg, detail)
    print(f"✅ 错误已记录（共 {n} 条）")
