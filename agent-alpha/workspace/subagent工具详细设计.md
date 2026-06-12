# subagent 工具详细设计

日期：2026-06-06

## 1. 目标

给 `agent-alpha` 增加一个 Hermes 风格的同步 subagent 工具。

主 agent 在需要拆分任务时，调用 `subagent` 工具。这个工具会创建一个或多个子 `AgentRuntime`，让它们在同一个 workspace 中完成任务，最后把每个子任务的结果结构化返回给主 agent。

第一版只做同步委托，不做后台长期运行的 subagent。

## 2. 不做什么

第一版暂不做这些能力：

- 不做后台 detached subagent。
- 不做 agent registry。
- 不做 agent profile 系统。
- 不做独立 workspace 分配。
- 不做文件锁。
- 不允许 subagent 再调用 `subagent` 创建孙 agent。

这些都不是当前最小可用版本必须解决的问题。

## 3. 核心原则

### 3.1 继续使用 AgentRuntime 作为 agent 实例

不新增 `SubAgentRuntime` 类。

主 agent 和 subagent 都是 `AgentRuntime` 实例。区别只在实例化参数、工具集、提示词来源、session 类型。

这样可以复用现有代码：

- `AgentRuntime`
- `AgentLoop`
- `ToolLoader`
- `RoleConfig`
- `SessionStore`
- `SessionKind.SUBAGENT`
- `build_system_prompt`

### 3.2 workspace 和人格文档解耦

主 agent 和 subagent 可以共享同一个 workspace。

但是 subagent 默认不读取 workspace 根目录里的 `AGENTS.md` 和 `SOUL.md`，避免把主 agent 的人格和工作规范错误套到子 agent 身上。

子 agent 的职责、人设、边界由主 agent 调用工具时传入 `instruction`。

## 4. AgentRuntime 需要增加的参数

给 `AgentRuntime` 增加一个可选参数：

```python
include_workspace_prompt_docs: bool = True
```

默认值是 `True`，保持当前主 agent 行为不变。

含义：

- `True`：读取 workspace 根目录的 `AGENTS.md` 和 `SOUL.md`，加入系统提示词。
- `False`：不读取 workspace 的 `AGENTS.md` 和 `SOUL.md`。

主 agent 使用默认值。

subagent 工具创建子 agent 时传：

```python
AgentRuntime(
    workspace_root=str(parent_workspace),
    logs_dir=str(logs_dir),
    role_config=subagent_role,
    include_workspace_prompt_docs=False,
)
```

## 5. subagent 工具

工具名固定为：

```text
subagent
```

原因：用户更容易理解 subagent 这个概念。

## 6. 工具参数设计

第一版参数：

```json
{
  "tasks": [
    {
      "task": "检查刚才改动有没有明显问题",
      "instruction": "你是代码审查 subagent，只检查 bug、风险和遗漏测试，不要修改文件。"
    }
  ],
  "timeout_seconds": 300
}
```

字段说明：

- `tasks`：子任务数组。即使只有一个任务，也放进数组。
- `tasks[].task`：具体要子 agent 完成的任务。
- `tasks[].instruction`：主 agent 给子 agent 的职责说明、身份说明、边界说明。
- `timeout_seconds`：每个子任务的最长运行时间。默认 300 秒，最大 600 秒。

`timeout_seconds` 规则：

- 不传时默认 300 秒。
- 超过 600 秒时自动封顶为 600 秒。
- 超时按每个子任务单独计算。
- 某个子任务超时，不影响其他子任务继续执行。

## 7. subagent 实例化规则

每个子任务创建一个新的 `AgentRuntime`。

子 agent 实例化时：

- 复用主 agent 当前 workspace。
- 不读取 workspace 的 `AGENTS.md` / `SOUL.md`。
- 不继承主 agent 的 history。
- 使用主 agent 传入的 `instruction` 作为子 agent 的任务角色说明。
- 工具集基本和主 agent 一样，但移除 `subagent` 工具。
- 可以使用 `bash`。

## 8. 子 agent 的输入内容

子 agent 的第一条用户输入由工具内部拼接，建议格式：

```text
# Subagent Instruction
{instruction}

# Task
{task}

# Output Requirement
Return a concise, structured result that the parent agent can use directly.
```

这里不加入父 agent 的完整历史。

如果主 agent 认为子 agent 需要上下文，必须自己把上下文写进 `task` 或 `instruction`。

## 9. 工具集处理

subagent 的工具集规则：

```text
subagent tools = parent tools - subagent
```

也就是说，子 agent 除了不能继续调用 `subagent`，其他工具和主 agent 保持一致。

这样做的目的：

- 子 agent 可以正常读写文件、运行 bash、加载 skill、使用 MCP。
- 避免递归创建子 agent，防止失控。

## 10. 执行方式

第一版是同步执行。

主 agent 调用 `subagent` 工具后，需要等待所有子任务结束，才能拿到返回结果。

如果传入多个任务，可以并发执行。内部可以设置一个默认并发上限，例如 3。这个值第一版不需要暴露给主 agent。

文件锁暂不处理。主 agent 负责合理拆任务：检查类任务可以并发，写文件类任务应谨慎并发。

## 11. 返回结构

工具返回 JSON 结构。

示例：

```json
{
  "ok": true,
  "results": [
    {
      "task_id": "subagent-1",
      "status": "success",
      "summary": "发现 2 个潜在问题。",
      "result": "详细结果文本",
      "session_id": "subagent-abc123",
      "workspace": "D:/files/demo/0312-newagent/agent-alpha/workspace"
    }
  ]
}
```

字段说明：

- `ok`：表示 subagent 工具本身是否正常执行。
- `results`：每个子任务一个结果。
- `task_id`：工具内部生成的子任务 ID。
- `status`：子任务状态。
- `summary`：给主 agent 快速阅读的一句话摘要。
- `result`：子 agent 的完整结果。
- `session_id`：子 agent 的 session ID。
- `workspace`：子 agent 使用的 workspace。
- `error`：失败或超时时才返回。

## 12. status 取值

第一版支持这些状态：

```text
success
timeout
error
max_turns
```

含义：

- `success`：子任务正常完成。
- `timeout`：子任务超过 `timeout_seconds`。
- `error`：子任务执行时出现异常。
- `max_turns`：子 agent 达到最大处理轮次。

只要 subagent 工具本身正常返回，外层 `ok` 仍然可以是 `true`。

只有工具整体崩溃，`ok` 才是 `false`。

## 13. 超时返回示例

```json
{
  "ok": true,
  "results": [
    {
      "task_id": "subagent-1",
      "status": "timeout",
      "summary": "子任务超过 300 秒，已停止。",
      "result": "",
      "session_id": "subagent-abc123",
      "workspace": "D:/files/demo/0312-newagent/agent-alpha/workspace",
      "error": "timeout after 300 seconds"
    }
  ]
}
```

## 14. session 记录

每个子 agent 保存为 `SessionKind.SUBAGENT`。

metadata 建议记录：

```json
{
  "parent_session_id": "父 session id",
  "task_id": "subagent-1",
  "instruction": "主 agent 传入的 instruction",
  "timeout_seconds": 300,
  "status": "success"
}
```

这样后续可以追踪：

- 子 agent 是谁创建的。
- 它做了什么任务。
- 用了哪个 workspace。
- 最后成功、失败还是超时。

## 15. 需要改动的模块

预计涉及这些文件：

- `agent/core/agent_runtime.py`
  - 增加 `include_workspace_prompt_docs` 参数。
  - 控制是否调用 `load_workspace_prompt_documents`。

- `agent/core/tool_loader.py`
  - 注册新的 `subagent` 工具。
  - 支持给子 agent 过滤掉 `subagent` 工具。

- `agent/tools/subagent_tool.py`
  - 新增 subagent 工具实现。
  - 创建子 `AgentRuntime`。
  - 执行多个任务。
  - 处理 timeout、error、结构化返回。

- `agent/core/session_store.py`
  - 已经有 `SessionKind.SUBAGENT`，优先复用。

- `tests/core/...`
  - 增加或扩展测试。

## 16. 测试重点

至少需要覆盖：

1. `AgentRuntime(include_workspace_prompt_docs=False)` 不加载 workspace 的 `AGENTS.md` / `SOUL.md`。
2. 主 agent 默认仍然加载 workspace 的 `AGENTS.md` / `SOUL.md`。
3. `subagent` 工具会创建子 `AgentRuntime`。
4. 子 agent 不继承父 agent history。
5. 子 agent 工具集中没有 `subagent`。
6. 子 agent 可以使用其他工具，包括 `bash`。
7. `timeout_seconds` 默认 300 秒。
8. `timeout_seconds` 最大封顶 600 秒。
9. 单个子任务超时返回 `status = "timeout"`。
10. 单个子任务异常返回 `status = "error"`，不影响其他任务结果。
11. 返回结构是稳定 JSON。

## 17. 第一版验收标准

第一版完成后，应达到：

- 主 agent 可以调用 `subagent` 工具。
- `subagent` 工具可以一次接收一个或多个任务。
- 每个任务创建独立子 `AgentRuntime`。
- 子 agent 和主 agent 共用 workspace。
- 子 agent 不读取 workspace 的 `AGENTS.md` / `SOUL.md`。
- 子 agent 使用主 agent 传入的 `instruction`。
- 子 agent 可以用 `bash`。
- 子 agent 不能再调用 `subagent`。
- 每个子任务独立返回结构化结果。
- 每个子任务有失败和超时兜底。

## 18. 后续可选方向

第一版稳定后，再考虑：

- agent profile 目录。
- 后台长期 subagent。
- cron 触发 subagent。
- subagent session 可视化。
- OpenClaw 风格的 parent-child session 索引。
- 更细的工具权限模板。

这些不进入第一版。
