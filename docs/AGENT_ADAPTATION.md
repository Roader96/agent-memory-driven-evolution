# 其他 Agent 适配指南

本项目提供通用 agent 兼容层；**Hermes agent** 具备最完整的原生集成（`state.db` 会话库 + `hermes chat` LLM 调用 + `hermes sessions archive` 归档）。

**Claude Code / Codex / Cursor / 自定义 agent 均可无需改核心代码使用**，通过 `scripts/adapters/agent_adapter.py` 适配层自动选择通用模式；Codex 可使用 `codex/` 独立记忆命名空间。

## 一、快速开始（3 分钟）

```bash
# 1. 按 install.sh 正常安装（脚本/技能/定时任务都会装好）
./install.sh

# 2. 确认适配层检测到你的环境
python3 ~/.hermes/scripts/skill_evolution/../../adapters/agent_adapter.py
# 输出 agent=auto→generic 即为通用模式

# 3. 指定你的 LLM 调用命令（必做，否则 LLM 类功能降级为空）
export AGENT_LLM="your-llm-cli"   # 例如 claude、codex exec、llm 等
```

## 二、需要配置的环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_TYPE` | `auto` | `hermes`（强制 Hermes 模式）/ `generic`（强制通用模式）/ `auto`（自动检测） |
| `AGENT_LLM` | `llm-cli` | 通用模式的 LLM 调用命令；stdin 收 prompt、stdout 出结果 |
| `HERMES_HOME` | `~/.hermes` | 记忆/技能/状态数据主目录（其他 agent 可指向自己的目录） |
| `HERMES_BIN` | 自动探测 | 显式指定 hermes 可执行文件（一般不用设） |
| `STATE_DB` | `<HERMES_HOME>/state.db` | 覆盖会话数据库路径 |
| `MEMORY_DIR` | `<HERMES_HOME>/memories` | 记忆目录（USER.md/MEMORY.md） |

## 三、适配层做了什么

```
┌─────────────────────────────────────────────────┐
│           你的 agent（Claude Code / Codex / …）  │
└──────────────┬──────────────────────────────────┘
               │
        scripts/adapters/agent_adapter.py
        (detect / skill_facts / llm_call / archive_session)
               │
   ┌───────────┴────────────┐
   ▼                        ▼
 Hermes 模式            通用模式（降级）
 · state.db SQLite      · skills 目录扫描（名字/修改时间/体积）
 · hermes chat          · AGENT_LLM 命令 / stdin-prompt
 · sessions archive     · 文件移动归档（幂等）
```

**降级行为**（缺 Hermes 时全自动）：
- `skill_facts()` → 扫描 `~/.hermes/skills/` 目录，统计 = 0 但结构完整
- `llm_call()` → 执行 `AGENT_LLM`；未配置则返回空串（调用方优雅降级，不崩）
- `archive_session()` → 文件移动；失败返回 `False`
- 任何异常 → 捕获返回空/False，**绝不抛出打断主流程**

## 四、各 agent 接入示例

### Claude Code
```bash
export AGENT_TYPE=auto                # 无 state.db 自动归 generic
export AGENT_LLM="claude -p"          # Claude Code CLI 非交互模式
export HERMES_HOME=~/.claude          # 记忆放 claude 主目录（可选）
./install.sh
```

### Codex（OpenAI）
```bash
export AGENT_TYPE=auto
export AGENT_LLM="codex exec --json"
export HERMES_HOME=~/.codex
./install.sh
```

### 自定义 agent / 脚本
```bash
export AGENT_TYPE=generic             # 强制通用模式
export AGENT_LLM="python3 my_llm_wrapper.py"   # 你的 LLM 封装（stdin prompt → stdout 结果）
export HERMES_HOME="$HOME/.my-agent"
./install.sh
```

## 五、数据源说明（重要）

- **Hermes 用户**：会话历史自动从 `state.db` 读取 → 技能度量/失败分析/偏好挖掘全量可用
- **其他 agent 用户**：目前**无会话数据库** → 技能度量统计为 0，但以下仍然工作：
  - ✅ 每周技能进化（curator 规则提案 + 文件系统扫描）
  - ✅ 技能退役/保护
  - ✅ 硬 cap 控制
  - ✅ 偏好挖掘框架（需接入自己的会话数据）
- 接入会话数据：把你的 agent 的会话历史导出成 SQLite（表结构含 `messages(session_id, role, content, tool_calls, timestamp)`），再 `export STATE_DB=/path/to/your.db`，即可启用全量分析。

## 五-bis、集成边界契约（想让其他 agent 全量跑起来必读）

本项目与 Hermes 运行时的耦合点**全部在这三处**，按契约实现即可全量接入：

### 1. `state.db` schema（会话历史数据源）

SQLite 数据库，默认 `<HERMES_HOME>/state.db`。系统只读（`mode=ro`），用到的表（以下为实测 schema 的核心字段，完整字段更多）：

```sql
-- sessions：会话元信息
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,      -- 会话 ID
    source TEXT NOT NULL,     -- 来源标识（cron/cli/...，用于排除系统自身会话）
    started_at REAL NOT NULL, -- 开始时间（Unix 秒）
    ended_at REAL,            -- 结束时间
    ...
);

-- messages：会话消息（核心）
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,   -- 全局自增（注意：不是会话内序号）
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,       -- 'user' | 'assistant' | 'tool'
    content TEXT,             -- 消息文本
    tool_calls TEXT,          -- assistant 消息的工具调用 JSON 数组字符串，可空
    timestamp REAL NOT NULL,  -- Unix 时间戳（秒）
    ...
);
```

**技能加载统计的真实来源**：解析 `messages.tool_calls` 中的 `skill_view` 调用（不是独立的 skills 表——**state.db 里没有 skills 表**，技能清单以 `~/.hermes/skills/` 目录 + frontmatter name 为准）：

```json
[{"name": "skill_view", "arguments": {"name": "some-skill"}}]
```

### 2. `hermes chat` CLI 契约（LLM 调用）

周审/偏好归纳调用形式：
```bash
hermes chat -Q --oneshot --cli --source <调用方标识> --query-file <prompt 文件路径>
# stdout 为模型输出；前几行可能有 "session_id:" / "Warning:" 前缀行需过滤
```

实现替代 LLM 时只需满足：**stdin/文件收 prompt → stdout 出结果**。可用 `AGENT_LLM` 环境变量注入。

### 3. `config.yaml` 结构（技能禁用写入点）

```yaml
skills:
  disabled:            # approve.py 退役执行写这里（软禁用，可逆）
    - some-skill-name
```

其他 agent 若无此配置文件，approve 的退役执行会失败但不崩（try/except 兜底）——建议提供等价物或修改 `approve.py` 的 `set_disabled()` 函数。

## 六、验证

```bash
bash tests/test_adapter.sh     # 适配层门禁（7 断言，3 场景）
python3 scripts/skill_evolution/verify_evolution_pipeline.py   # 通用验证器（36 断言）
```

两者都应全绿。

## 七、常见问题

**Q: 我设了 AGENT_LLM 但 LLM 功能还是降级？**
A: 确认命令能在 shell 直接执行（如 `claude -p "hi"`），且从 stdin 读 prompt、stdout 出结果。调试：`echo "hi" | $AGENT_LLM`

**Q: 我用了别的 agent 目录（如 ~/.claude），怎么让它找到脚本？**
A: 安装时 install.sh 会把脚本装到 `$HERMES_HOME/scripts/`，所以先 `export HERMES_HOME` 再 `./install.sh`。

**Q: 为什么技能统计全 0？**
A: 因为没有会话数据库，`skill_facts()` 走目录降级。接入你的会话数据后即有真实统计（见第五节）。
