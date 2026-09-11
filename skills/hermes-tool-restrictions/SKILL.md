---
name: hermes-tool-restrictions
description: Hermes 工具限制速查。后台 review 模式下 patch/read_file/search_files/write_file 被拒绝（只允许 memory/skill 工具）；前台 terminal 不要用 '&' 后台化（要用 terminal(background=true)）。基于 Hermes 自带 errors.log 高频统计提炼。
---

# Hermes 工具限制速查

> **数据源**：`~/.hermes/logs/errors.log`
> **触发频率**：≥10 次/类

## 1. 后台 review 模式限制 ⚠️

**报错**：`Background review denied non-whitelisted tool`

**白名单**：memory / skill 工具
**被拒**：patch (16次) / read_file (10次) / search_files / write_file

**解决**：在主对话里用这些工具。

## 2. Terminal 后台化错误

**报错**：`Foreground command uses '&' backgrounding`

**解决**：
```python
terminal("python3 server.py", background=True, notify_on_complete=True)
```

## 3. execute_code 超时

**报错**：`BLOCKED: execute_code script timed out`

**解决**：长任务拆小 / 用 terminal(background=true)

## 4. memory 字符超限

**报错**：`Memory at X/Y chars. Adding this entry would exceed the limit.`

**解决**：写之前先 read，>80% 时先迁移再写。

## 5. skill_manage 已知坑

**常见报错**：`Skill 'XXX' not found in active profile`

**3 个原因**：
1. skill 名拼错（用 `skills_list()` 先查）
2. skill 在别的 profile
3. `action=create` 假成功（已确认 bug）—— 用 `write_file` 兜底

## 6. terminal 误报

**常见**：`exit_code=1` 不一定是错（grep 无匹配、test 假条件）。

## 7. 安全阻断

**硬拦截**：shutdown / reboot / halt / poweroff

---
_由 hermes-self-improving 从 logs/errors.log 高频统计提炼_
