# agent-alpha harness 设计

日期：2026-06-23

## 0. 阅读规则

本文只记录 `agent-alpha` 已经落地的 harness 设计和实现现状。

这里的“设计”指源码、配置、测试或项目文档中已经存在的机制，不包含未来规划。`开发日志.md` 只作为线索来源；写入本文前必须回到当前源码、配置或测试中验证。

更新本文的固定流程：

1. 先看该 harness 模块对应源码。
2. 再查 `开发日志.md` 找历史线索。
3. 回到源码、配置或测试验证。
4. 只写已落地内容；未验证、已删除、仅规划的内容不写。

## 目录

- [1. 入口层 / Channel Layer](#m01)
- [2. Gateway 控制平面层](#m02)
- [3. 消息与会话编排层](#m03)
- [4. Context / Prompt 组装层](#m04)
- [5. Agent Runtime / Harness 层](#m05)
- [6. Agent Loop 执行层](#m06)
- [7. Tool / Skill / Plugin 能力层](#m07)
- [8. 权限 / 沙箱 / 安全层](#m08)
- [9. Workspace / Memory / State 持久化层](#m09)
- [10. 输出交付 / UI / Side-effect 层](#m10)
- [11. Ops / Debug / Eval 层](#m11)
- [12. 当前未落地或不纳入本文的内容](#m12)

<a id="m01"></a>

## 1. 入口层 / Channel Layer

### 实时定位

```powershell
rg -n "def run_single_agent_cli|project.scripts|agent-alpha|channels|input\\(\"You:\"\\)" agent-alpha\pyproject.toml agent-alpha\agent
```

### 已落地设计

当前真正落地的入口是 CLI。

入口定义在：

```text
agent-alpha/pyproject.toml
agent-alpha/agent/cli/main.py
```

`pyproject.toml` 里注册了命令：

```text
agent-alpha = "agent.cli.main:run_single_agent_cli"
```

CLI 启动后做这些事：

- 计算 `PROJECT_ROOT`。
- 调用 `apply_runtime_env(project_root)` 注入 alpha 本地运行环境。
- 创建 session id。
- 创建 session 目录、log 目录和默认 workspace。
- 创建 `SessionStore`。
- 创建 `AgentRuntime`。
- 进入 `while True` 交互循环，读取 `You:` 输入。

当前 `agent-alpha/agent/channels` 基本是占位目录，没有独立 channel 实现。也就是说，当前 Channel Layer 不是多入口体系，而是 CLI 单入口。

### 实现现状

CLI 同时承担了两类职责：

- 用户交互入口：接收普通消息、打印 Agent 回复。
- 控制命令入口：处理 `reset`、`/resume`、`/workspace`、`/compact`、`/admin`、`save`、`save-log` 等命令。

这说明当前入口层和控制面还没有完全拆开。

<a id="m02"></a>

## 2. Gateway 控制平面层

### 实时定位

```powershell
rg -n "_handle_admin|_handle_workspace_command|_restore_session_interactive|_handle_compact_command|load_llm_profile|RoleConfig|resolve_tools|apply_runtime_env" agent-alpha\agent agent-alpha\config
```

### 已落地设计

当前没有独立 Gateway 服务，也没有 FastAPI 控制面。已经落地的是“内嵌控制面”：控制逻辑分散在 CLI、Runtime、ToolLoader、LLM profile 和 runtime env 中。

控制面能力包括：

- `/admin`：切换权限模式。
- `/workspace`：查看或切换当前 workspace。
- `/resume`：恢复历史 interactive session。
- `/compact`：手动压缩上下文。
- LLM profile：从 `config/llm_profiles.json` 选择模型供应商、base_url、model、max_tokens 和 API key env。
- RoleConfig：按角色过滤工具组、允许工具和拒绝工具。
- Runtime env：通过 `runtime_paths.py` 统一注入 HOME、TEMP、PATH、缓存目录、凭据配置等运行环境。

### 实现现状

控制平面不是一层独立模块，而是由这些文件共同组成：

```text
agent-alpha/agent/cli/main.py
agent-alpha/agent/api/llm_profiles.py
agent-alpha/config/llm_profiles.json
agent-alpha/agent/core/role_config.py
agent-alpha/agent/core/tool_loader.py
agent-alpha/agent/core/runtime_paths.py
agent-alpha/agent/core/permission_manager.py
```

当前设计好处是简单，CLI 就能完成主要控制。代价是控制面和入口层耦合较强，未来如果增加 HTTP/API 入口，需要把这些控制命令抽出来复用。

<a id="m03"></a>

## 3. 消息与会话编排层

### 实时定位

```powershell
rg -n "class SessionKind|class SessionRecord|class SessionStore|def save|def load|def list_recent|def update_workspace|def append_event|SessionEventWriter|MessageBus|InboundMessage|OutboundMessage|CronTrigger|CronService" agent-alpha\agent
```

### 已落地设计

当前会话编排分成两部分：主链路和脚手架。

主链路是 CLI 直接驱动：

```text
CLI input
  -> AgentRuntime.handle(RuntimeRequest)
  -> AgentLoop.run()
  -> RuntimeResponse
  -> CLI print
  -> SessionStore save
```

会话持久化由 `SessionStore` 负责：

```text
agent-alpha/session-log/sessions/<session_id>.json
```

实时事件由 `SessionEventWriter` 负责：

```text
agent-alpha/session-log/events/<session_id>.jsonl
```

最终归档日志由 CLI 在退出或 `save-log` 时写入：

```text
agent-alpha/session-log/logs/<timestamp>_session_<session_id>.json
```

### SessionStore 现状

`SessionRecord` 当前记录：

- `session_id`
- `kind`
- `workspace`
- `history`
- `metadata`
- `events`
- `created_at`
- `updated_at`

`SessionKind` 已经定义：

- `interactive`
- `cron`
- `subagent`
- `system`

但当前主链路使用的是 `interactive`。

### MessageBus / Cron 脚手架

`agent-alpha/agent/runtime/bus` 和 `agent-alpha/agent/runtime/cron` 已经存在：

- `InboundMessage`
- `OutboundMessage`
- `CronTrigger`
- `MessageBus`
- `CronJob`
- `CronService`

当前这些是轻量脚手架：bus 有 inbound/outbound 两个 async queue，cron service 能把 cron job 转成 inbound trigger。它们尚未成为 CLI 主执行链路。

### 实现现状

当前“消息与会话编排层”并不是完整异步编排平台。真实主链路仍是同步 CLI 调 `AgentRuntime.handle()`。bus/cron 表示方向已经落地为代码骨架，但还不是主路径。

<a id="m04"></a>

## 4. Context / Prompt 组装层

### 实时定位

```powershell
rg -n "def build_system_prompt|load_workspace_prompt_documents|PROMPT_DOC_NAMES|class ContextManager|ContextCompressionResult|should_compress|compress_history_with_result|sanitize_tool_history|collect_recent_complete_groups|SkillLoader|get_summaries" agent-alpha\agent
```

### 已落地设计

这一层负责把“运行时信息、workspace 文档、skill 摘要、工具定义、历史消息”变成模型可用上下文。

主要文件：

```text
agent-alpha/agent/core/system_prompt_builder.py
agent-alpha/agent/core/prompt_docs_loader.py
agent-alpha/agent/core/context_manager.py
agent-alpha/agent/core/message_history.py
agent-alpha/agent/core/skill_loader.py
```

### System Prompt 组装

`build_system_prompt()` 会注入：

- task id。
- workspace root。
- skills directory。
- recommended skill install directory。
- MCP servers directory。
- MCP registry path。
- logs directory。
- agent-alpha runtime directories。
- bash runtime 规则。
- workspace rules。
- skill 摘要列表。
- session documents。
- large file strategy。

这里的 prompt 不是纯人格提示，而是运行时契约。它告诉模型 alpha 的路径边界、skill 安装位置、bash cwd、runtime env profile、MCP 资源位置和 workspace 文档规则。

### Workspace Prompt Documents

`prompt_docs_loader.py` 只从当前 workspace 根目录读取：

```text
AGENTS.md
SOUL.md
```

不扫描嵌套目录。

这和当前“一个 agent 实例绑定一个 workspace_root”的设计一致。

### ContextManager

`ContextManager` 负责：

- token 计数。
- system prompt token 成本计算。
- tool definitions token 成本计算。
- history 可用 token 计算。
- 是否触发压缩。
- 压缩旧历史。
- 压缩失败时 fallback 到最近短上下文。

压缩结果由 `ContextCompressionResult` 表示，包含：

- trigger。
- before/after message count。
- before/after token。
- summary。
- success。
- fallback。
- error。

压缩摘要目前是 Markdown / 文本，不再要求 JSON。

### Message History 合法化

`message_history.py` 负责维护 tool-call 历史合法性。

已落地能力：

- 丢弃孤立 tool result。
- 收集最近完整消息组，避免压缩时把 `assistant tool_calls` 和对应 `tool` 结果切散。

这解决的是 OpenAI tool 消息约束：`tool` 消息必须跟在带 `tool_calls` 的 assistant 消息后。

### 实现现状

Context / Prompt 层已经不是简单拼 prompt，而是同时承担：

- 路径契约注入。
- workspace 文档注入。
- skill 摘要注入。
- token 预算管理。
- 历史压缩。
- tool-call 历史合法化。

<a id="m05"></a>

## 5. Agent Runtime / Harness 层

### 实时定位

```powershell
rg -n "class AgentRuntime|def __init__|def handle|def compact_history|def _build_system_prompt|def close|LLMClient|ToolLoader|SkillLoader|ContextManager|apply_runtime_env" agent-alpha\agent\core\agent_runtime.py
```

### 已落地设计

`AgentRuntime` 是单 agent 实例的运行时边界。

它负责把以下组件组装成一个可运行的 agent：

- workspace root。
- logs dir。
- events dir。
- task id。
- LLM profile。
- role config。
- LLMClient。
- SkillLoader。
- ToolLoader。
- tools。
- prompt documents。
- system prompt。
- ContextManager。
- interrupt event。

构造时关键动作：

1. 解析 workspace root。
2. 调用 `apply_runtime_env(PROJECT_ROOT)`。
3. 创建 workspace 目录。
4. 创建 `LLMClient.from_profile()`。
5. 创建 `SkillLoader`，扫描 `skills` 和 `home/.agents/skills`。
6. 创建 `ToolLoader`。
7. 绑定 interrupt event 给 ToolLoader。
8. `tool_loader.load_all()`。
9. 按 `RoleConfig` 过滤工具。
10. 将 workspace runtime 配置给工具。
11. 加载 workspace prompt documents。
12. 构建 system prompt。
13. 创建 ContextManager。

### handle() 链路

`AgentRuntime.handle()` 做这些事：

- 接收字符串或 `RuntimeRequest`。
- 创建 session event writer。
- 判断是否需要自动压缩。
- 自动压缩后记录压缩事件。
- 创建 `AgentLoop`。
- 将 llm、tools、tool_loader、history、system_prompt、event_writer、interrupt_event 传给 loop。
- 返回 `RuntimeResponse`。

### 实现现状

`AgentRuntime` 是当前真正的 harness 核心：它不直接写 CLI 交互，但它把模型、工具、上下文、workspace 和中断连接起来。

它目前仍是同步执行边界。bus/worker 还没有接管 `handle()`。

<a id="m06"></a>

## 6. Agent Loop 执行层

### 实时定位

```powershell
rg -n "class AgentLoop|def run|def _call_llm_interruptible|def _handle_tool_calls|def _execute_single_tool|def _execute_single_tool_interruptible|def _build_messages|def _fill_missing_tool_results|def _drop_orphan_tool_results|llm_output_truncated|finish_reason" agent-alpha\agent\core\agent_loop.py
```

### 已落地设计

`AgentLoop` 是一轮用户输入内部的模型-工具循环。

主流程：

```text
append user message
  -> build messages
  -> call LLM
  -> if tool_calls: execute tools and append tool results
  -> call LLM again
  -> if final assistant content: return
```

### LLM 调用与中断

LLM 调用通过线程包装：

- 主线程轮询 interrupt event。
- 如果 ESC 中断，放弃等待并返回。
- LLM 请求线程是 daemon。

这让用户在等待模型时可以通过 ESC 返回 CLI。

### Tool Call 处理

`_handle_tool_calls()` 会：

- 把 assistant tool_calls 写入 history。
- 逐个执行 tool call。
- 工具结果写入 history。
- 工具输出去除 ANSI 颜色码。
- 工具输出进入 `truncate_tool_result()`，避免过长。
- 如果某个工具返回 `retry_with_context`，会把补充说明作为新的 user message 追加。

### 残缺 Tool 参数拦截

如果模型响应 `finish_reason=length`，并且某个 tool call 参数 JSON 解析失败：

- 不执行工具。
- 不进入 sandbox。
- 写入同一个 tool_call_id 对应的 tool result。
- 记录 `llm_output_truncated` 实时事件。

这避免“模型参数截断”被误判成路径错误或工具错误。

### 工具异常包装

工具执行抛异常时，`AgentLoop` 不让异常打穿整个循环，而是包装成：

```text
success: false
error: <message>
error_type: <ExceptionType>
tool: <tool_name>
```

然后作为 tool result 返回给模型。

### Tool History 修复

`AgentLoop` 在新用户输入前和发给 LLM 前会维护历史合法性：

- `_fill_missing_tool_results()`：补齐 assistant 声明但缺失的 tool result。
- `_drop_orphan_tool_results()`：丢弃孤立 tool result。

ESC 中断多个工具调用时，已完成的保留，未执行的补“用户中断”工具结果。

### 实现现状

Agent Loop 层是当前 harness 的稳定性关键点：它处理 LLM 等待中断、工具等待中断、残缺参数、工具异常和历史合法性。

<a id="m07"></a>

## 7. Tool / Skill / Plugin 能力层

### 实时定位

```powershell
rg -n "class ToolLoader|BUILTIN_TOOLS|TOOL_GROUPS|def load_all|def resolve_tools|def execute_tool|class SkillLoader|class MCPManager|class BrowserManager|class BashTool|class .*Tool" agent-alpha\agent agent-alpha\mcp-servers agent-alpha\skills
```

### 总体链路

能力层主链路：

```text
AgentLoop
  -> ToolLoader.execute_tool()
  -> SandboxGuard / PermissionManager
  -> 内置工具 / load_skill / MCP tool
  -> tool result
```

`ToolLoader` 有三类能力来源：

1. MCP 工具。
2. Skill 工具。
3. 内置本地工具。

### 内置工具

内置工具包括：

- `bash`
- `read`
- `write`
- `append`
- `edit`
- `glob`
- `grep`
- `fetch`
- browser 系列工具
- profile 系列工具
- CDP 系列工具

所有内置工具继承 `BaseTool`，统一实现：

```text
name
get_tool_definition()
execute(**kwargs)
```

文件工具现状：

- `read`：带行号读取，支持 offset/limit。
- `write`：原子覆盖写。
- `append`：追加写。
- `edit`：精确字符串替换，默认要求唯一匹配。

搜索与抓取工具现状：

- `glob`：Python glob/rglob，按修改时间倒序。
- `grep`：调用 `rg`。
- `fetch`：urllib 抓取 URL，清洗 HTML/XML/JSON，长内容保存到 `fetch_results`。

### Bash 工具

`bash` 是 CLI 型 skill 的受控运行底座。

已落地设计：

- 默认 cwd 是 `agent-alpha`。
- 支持 `working_dir`。
- 简单 `cd 目录 && 命令` 自动拆分。
- 复杂 `cd` 返回指导。
- 拦截错误的 `agent-alpha/temp`、`agent-alpha/home` 等相对路径。
- 注入 alpha runtime env。
- PATH 优先 `.venv`、`agent-alpha/bin`、`home/.local/Python*/Scripts`。
- Python 命令必须用 alpha `.venv`。
- stdout/stderr 后台线程持续读取。
- timeout 和 ESC 中断会终止进程树。

### 浏览器工具

浏览器工具由两层组成：

- `browser_tool.py`：模型可见工具定义。
- `browser_manager.py`：实际状态机。

模型可见工具：

- `browser_navigate`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_scroll`
- `browser_press`
- `browser_close`
- `profile_list`
- `profile_create`
- `profile_login_headed`
- `profile_save_headed`
- `profile_close_headed`
- `browser_connect_cdp`
- `browser_disconnect_cdp`
- `browser_cdp_status`

三种浏览器模式：

- `local-headless`
- `local-headed-login`
- `external-cdp`

无头模式：

- 使用临时 runtime profile。
- 不直接写 default profile。
- 关闭时清理自己的 runtime。
- 有头/CDP 被其他 alpha 占用时仍可启动。

有头登录模式：

- 用户可见。
- 用于人工登录、验证码、2FA。
- 占用跨 alpha `interactive.lock`。
- `browser_close` 拒绝关闭有头。
- 关闭必须用 `profile_close_headed`，且需要显式确认。
- 可用 `profile_save_headed` 保存状态。

CDP 模式：

- 连接外部浏览器。
- 占用交互锁。
- 不写 alpha profile。
- `browser_disconnect_cdp` 只断开控制，不关闭真实浏览器。

浏览器状态落点：

```text
agent-alpha/state/browser/profiles
agent-alpha/state/browser/profiles.json
agent-alpha/state/browser/runtime
agent-alpha/state/browser/sessions
agent-alpha/state/browser/sockets
agent-alpha/state/browser/downloads
agent-alpha/state/browser/locks
```

多 alpha 锁语义：

- 有头/CDP 使用跨 alpha 全局 `interactive.lock`。
- 无头不被这个锁阻塞。
- 如果锁属于其他 alpha，返回 `interactive_owner=other_alpha`、`recommended_next_tool=browser_navigate` 和 `do_not_call`。

快照策略：

- `browser_navigate` 只返回导航摘要，不自动带 snapshot。
- `browser_snapshot` 默认只返回可行动元素。
- `save_full=true` 时完整快照写入 `agent-alpha/temp/browser_snapshots`，history 只保留文件路径和统计。

Profile 5 同步脚本：

```text
agent-alpha/sync-chrome-profile5-to-alpha.ps1
```

已落地能力：

- 从宿主 Chrome `Profile 5` 单向同步到 alpha default profile。
- 使用 `profile-copy-default.lock`。
- 通过 `user-data.importing` staging 后再替换。
- 校验 `Local State` 和 `Default/Preferences`。

### Skill

Skill 运行时加载：

- 扫描 `agent-alpha/skills`。
- 扫描 `agent-alpha/home/.agents/skills`。
- 系统 prompt 只注入摘要。
- 正文通过 `load_skill(name)` 按需加载。
- 找不到 skill 时先 reload，再返回 Unknown。
- 同名冲突时 `agent-alpha/skills` 优先。

Skill 安装适配：

```text
agent-alpha/skills/install-alpha-skill/SKILL.md
```

已落地规则：

- GitHub 或外部来源先放到 `temp/skill-install/<source-name>`。
- 安装前读 README / INSTALL / README 链接的本地文档。
- 复制 skill body 到 `home/.agents/skills/<skill-name>`。
- 第三方路径翻译成 alpha 内部路径。
- Python 依赖和 Python CLI 优先装进 `.venv`。
- npm / Go 全局安装保留宿主语义。
- token/cookie/API key/proxy 等写入 `config/runtime_env.local.json`，不覆盖路径策略变量。

### MCP / Plugin

当前没有独立 plugin marketplace。已落地的 plugin 形态主要是 MCP server 接入。

MCP 链路：

```text
MCPScanner
  -> mcp-servers 扫描
  -> MCPManager FastMCP 持久连接
  -> ToolLoader 注入 MCP tool definitions
  -> mcp__server__tool_name
  -> MCPManager.call_tool()
```

`stdio_wrapper.py` 用于过滤 STDIO server 的非 JSON-RPC stdout，把调试日志转 stderr。

当前已验证存在的 MCP server：

```text
agent-alpha/mcp-servers/open-websearch
```

当前配置：

- `open-websearch@2.1.11`
- registry 中为 `core`
- `ALLOWED_SEARCH_ENGINES` 白名单
- 明确 Google 不支持
- `FAKE_IP_CIDRS=198.18.0.0/16`

当前白名单：

```text
baidu,bing,linuxdo,csdn,duckduckgo,exa,brave,juejin,startpage,sogou
```

<a id="m08"></a>

## 8. 权限 / 沙箱 / 安全层

### 实时定位

```powershell
rg -n "class SandboxGuard|def check_tool_call|def _check_bash_command|PROTECTED_PROJECT_PATHS|decide_path_access|classify_bash_command|extract_general_write_paths|is_external_executable_invocation|class PermissionManager|ask_user" agent-alpha\agent\core
```

### 已落地设计

安全层分成三块：

- `path_policy.py`：路径分类与访问决策。
- `sandbox_guard.py`：按工具类型调度检查。
- `permission_manager.py`：ask 场景下询问用户。

### 路径策略

当前路径分区：

- `workspace`
- `project`
- `outside`
- `unknown`

当前访问规则：

- workspace 内读写允许。
- agent-alpha 项目内读取允许。
- agent-alpha 项目内写入大多允许，但核心目录需要 ask。
- 外部路径读取允许。
- 外部路径写入拒绝。

当前保护目录：

```text
agent/core
agent/tools
```

### Bash 沙箱

Bash 会先通过 `command_path_extractor.py` 做静态分类。

当前分类包括：

- dangerous。
- package_install。
- project_command。
- script_run。
- read_only。
- path_mutation。
- general / unknown。

已落地安全点：

- 拒绝危险系统命令。
- 拒绝外部 Python 和宿主 Python 污染。
- 允许普通 CLI 执行。
- 允许外部已安装 CLI / exe 执行。
- 禁止通过参数、重定向、复制、移动、删除等方式写到 alpha/workspace 外。
- 对外部写路径给出诊断，包括原始路径、解析路径、cwd、允许写入根目录和推荐写法。

### PermissionManager

当 sandbox 决策是 ask，并且权限模式不是 auto 时，会提示用户：

- `[A]` 允许一次。
- `[N]` 拒绝。
- `[E]` 追加指令后重试。

如果用户选择追加指令，ToolLoader 会返回 `retry_with_context`，AgentLoop 会把补充说明作为新的 user message 交给模型。

### 实现现状

安全层已经覆盖文件工具和 bash 主路径。MCP、浏览器、fetch 等工具目前不是逐参数深度沙箱，而是通过工具自身设计和整体运行边界控制。

<a id="m09"></a>

## 9. Workspace / Memory / State 持久化层

### 实时定位

```powershell
rg -n "workspace_root|get_default_workspace_root|create_cli_session_paths|ensure_runtime_directories|build_runtime_env|runtime_env.local.json|state/browser|profiles.json|SessionStore|SessionEventWriter|AGENTS.md|SOUL.md" agent-alpha\agent agent-alpha\路径管理说明.md
```

### 已落地设计

当前持久化层包括四类状态：

1. workspace。
2. session logs。
3. runtime env / config / cache / temp。
4. browser state。

### Workspace

默认 workspace：

```text
agent-alpha/workspace
```

CLI 支持：

```text
/workspace
/workspace show
/workspace set <path>
```

当前设计是一个 agent 实例只绑定一个 `workspace_root`。额外目录不通过运行时配置输入，如果用户需要访问其他路径，需要在对话中明确给路径。

### Session State

会话状态落点：

```text
agent-alpha/session-log/sessions
agent-alpha/session-log/events
agent-alpha/session-log/logs
```

三者职责不同：

- `sessions/*.json`：可恢复会话快照。
- `events/*.jsonl`：实时 append-only history/event 记录。
- `logs/*.json`：退出或保存时的归档日志。

### Runtime Env

`runtime_paths.py` 会创建并重定向：

- `home`
- `home/.agents/skills`
- `home/.local`
- `bin`
- `userfile`
- `skills`
- `temp`
- `cache`
- `tools/uv`
- `config/appdata`
- `data/localappdata`
- `state`
- `state/browser/*`

核心环境变量会指向 alpha 内部：

- `AGENT_ALPHA_ROOT`
- `HOME`
- `USERPROFILE`
- `XDG_CONFIG_HOME`
- `XDG_CACHE_HOME`
- `XDG_DATA_HOME`
- `XDG_STATE_HOME`
- `APPDATA`
- `LOCALAPPDATA`
- `TMP`
- `TEMP`
- `PIP_CACHE_DIR`
- `UV_CACHE_DIR`
- `PYTHONUSERBASE`
- `PYTHONPYCACHEPREFIX`
- `PLAYWRIGHT_BROWSERS_PATH`
- `VIRTUAL_ENV`
- `PYTHONNOUSERSITE`

持久服务配置文件：

```text
agent-alpha/config/runtime_env.local.json
```

这个文件用于 token、cookie、API key、auth header、proxy 等服务配置，不允许覆盖路径策略变量。

### Browser State

浏览器状态集中在：

```text
agent-alpha/state/browser
```

包括 profile、session、socket、download、runtime 和 lock。

### Memory

当前 `agent-alpha` 源码中没有独立记忆模块。已有的“记忆/状态”主要是 session history、runtime events、workspace 文档、skill 内容和浏览器 profile 状态。

<a id="m10"></a>

## 10. 输出交付 / UI / Side-effect 层

### 实时定位

```powershell
rg -n "print\\(|save_session_log|save_context|write_text|append_session_index|execute\\(|_run_cli|urlopen|Path\\(|browser_snapshots|fetch_results|subprocess.Popen" agent-alpha\agent
```

### 已落地设计

当前输出和副作用不是独立 UI 层，而是分布在 CLI、工具和日志系统中。

### CLI UI

CLI 输出包括：

- 启动 banner。
- 命令说明。
- `You:` 输入提示。
- `Agent:` 回复。
- 权限询问。
- 压缩结果提示。
- workspace 当前路径提示。
- resume session 列表。

### 文件副作用

文件副作用来自：

- `write`
- `append`
- `edit`
- `fetch` 长内容落地
- `browser_snapshot save_full`
- session/log 写入
- context save

### 命令副作用

命令副作用来自：

- `bash`
- `browser_manager` 调 `agent-browser`
- MCP server 子进程或 HTTP 调用
- sync Chrome Profile 5 脚本

### 浏览器副作用

浏览器副作用包括：

- 创建 runtime profile。
- 写 profile registry。
- 写 session metadata。
- 写 socket stdout/stderr。
- 写 downloads。
- 写 browser snapshots。
- 写 headed state。
- 写 interactive/profile-copy locks。

### 实现现状

当前没有独立前端 UI。交付和副作用控制主要靠：

- CLI 文本交互。
- 工具返回结构。
- session events。
- sandbox / permission。
- runtime path 收口。

<a id="m11"></a>

## 11. Ops / Debug / Eval 层

### 实时定位

```powershell
rg -n "runtime_error|SessionEventWriter|truncate_tool_result|context_compacted|context_compaction_failed|llm_output_truncated|pytest|test_|DEBUG_AGENT|last_llm_response|Session Index" agent-alpha\agent agent-alpha\tests 开发日志.md
```

### 已落地设计

Ops / Debug / Eval 由三部分组成：

1. 实时日志。
2. 会话快照和归档日志。
3. 测试集。

### 实时事件日志

`SessionEventWriter` 写入：

```text
agent-alpha/session-log/events/<session_id>.jsonl
```

虽然扩展名是 `.jsonl`，当前实际格式是多行格式化 JSON 块，块间空行，更方便人工阅读。

记录内容包括：

- user message。
- assistant message。
- tool result。
- context compacted。
- context compaction failed。
- runtime error。
- llm output truncated。

工具结果有统一截断：

- 默认最多 200 行。
- 仍受字符上限控制。
- 浏览器工具有更小字符上限。
- 文档读取类工具有更大字符上限。

### Session 快照和归档

快照：

```text
agent-alpha/session-log/sessions/<session_id>.json
```

归档：

```text
agent-alpha/session-log/logs/<timestamp>_session_<session_id>.json
```

`index.md` 记录 session 概览。

### Runtime Error

CLI 通用异常分支会写 `runtime_error` 实时事件，但不把错误时的脏 history 覆盖进可恢复 session 快照。

### Debug 文件

`AgentLoop` 在 `DEBUG_AGENT=1` 时，会把最近一次 LLM tool_calls 调试信息写到：

```text
workspace/temp/last_llm_response.json
```

### Eval / Test

当前没有独立评测系统，但测试覆盖较多 harness 边界。

测试目录：

```text
agent-alpha/tests/core
```

已覆盖方向包括：

- agent loop。
- bash interrupt。
- bash output streaming。
- bash sandbox。
- bash working_dir。
- browser tools。
- bus。
- context manager。
- cron。
- LLM。
- LLM profiles。
- main CLI。
- package layout。
- prompt docs loader。
- role config。
- runtime paths。
- sandbox guard。
- session events。
- session paths。
- session store。
- skill loader。
- tool loader policy / sandbox / skills。
- system prompt builder。

### 实现现状

Ops 层当前更偏“可追溯运行记录 + 回归测试”，还不是独立观测平台或自动 eval 平台。

<a id="m12"></a>

## 12. 当前未落地或不纳入本文的内容

以下内容不写成当前实现现状：

- 独立 FastAPI Gateway。用户规范要求后端接口使用 FastAPI，但当前 agent-alpha 没有落地后端接口。
- 独立 plugin marketplace。
- 独立 tool service。
- 独立前端 UI。
- 独立记忆模块。
- bus/cron 作为主执行链路。
- 当前目录中未验证到的历史 Playwright MCP 运行实现。
- 未来多 agent / subagent 规划。

本文以后更新时，仍按“源码 -> 开发日志 -> 源码验证 -> 写入”的流程维护。
