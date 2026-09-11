# 错误记录使用指南

## Python 脚本里记录

```python
import sys
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from auto_log_error import log_error, log_exception

# 方式 1: 手动记
log_error("类别", "简短消息", "详细堆栈/上下文")

# 方式 2: 自动捕获当前异常
try:
    risky_operation()
except Exception:
    log_exception("类别", "前缀: ")
```

## CLI 记录

```bash
~/.hermes/scripts/auto_log_error.py "类别" "消息" "详情"
echo "详情" | ~/.hermes/scripts/auto_log_error.py "类别" "消息"
```

## 自动汇总

- 下次 `vault_postprocess.py` 跑时自动生成 `ERRORS.md` 报告
- 不用手动触发

## 错误类别建议

| 类别 | 用于 |
|------|------|
| `smart_archive` | 归档脚本异常 |
| `vault_postprocess` | 后处理异常 |
| `hook` | hook 异常 |
| `cron` | 定时任务异常 |
| `tool_failure` | 工具调用失败 |
| `test` | 测试用 |
