# Agent Alpha

[中文](#中文) | [English](#english)

Agent Alpha 是一个面向本地工作流、多智能体协作与长期记忆的 Agent Runtime / Harness。

---

<a id="中文"></a>

## 中文

[English](#english)

### 项目定位

Agent Alpha 不只是一个聊天界面，也不把 Agent 简化成一次模型调用。它把模型、会话、上下文、工具、Skill、权限、工作区和运行状态组织成一个可持续运行的本地系统。

CLI、Web 和 Electron 桌面端只是不同的入口。它们共用同一套 FastAPI 控制面、会话编排和 Agent Runtime，因此界面可以从浏览器迁移到桌面容器，而不用重写核心能力。

项目主要面向三类场景：

- 在本地工作区中持续完成真实任务；
- 让多个 Agent 分工、通信并共同交付结果；
- 从长期协作记录中维护可修订、可追溯的记忆。

### 整体框架

```text
CLI / Web / Electron
        ↓
FastAPI Gateway
        ↓
消息与会话编排
        ↓
Context / Prompt 组装
        ↓
Agent Runtime → Agent Loop
        ↓
Tool / Skill / MCP / Browser
        ↓
权限与沙箱 → Workspace / Memory / State
```

| 层 | 主要职责 |
| --- | --- |
| 入口层 / Channel Layer | CLI、Web、Electron 的输入与展示 |
| Gateway 控制平面层 | FastAPI 接口、运行状态、配置与生命周期 |
| 消息与会话编排层 | 会话、消息投递、排队、中断、恢复与多 Agent 协作 |
| Context / Prompt 组装层 | 系统提示词、工作区文档、历史与上下文压缩 |
| Agent Runtime / Harness 层 | 组装模型、工具、角色、工作区和运行状态 |
| Agent Loop 执行层 | 驱动“模型 → 工具 → 结果 → 模型”的循环 |
| Tool / Skill / Plugin 能力层 | 本地工具、Skill、MCP 和浏览器能力 |
| 权限 / 沙箱 / 安全层 | 路径边界、危险操作检查和用户授权 |
| Workspace / Memory / State 层 | 项目文件、会话快照、日志、记忆和运行状态 |

详细分层说明见 [harness设计.md](harness设计.md)。

### 依赖

当前运行环境以 Windows 为主：

- PowerShell；
- [uv](https://docs.astral.sh/uv/)；
- Python 3.12，由 uv 管理在 `agent-alpha/.venv`；
- Node.js 与 npm，用于 Web 和 Electron 前端；
- 一个可用的模型服务及对应 API Key。

主要技术组件包括 FastAPI、Uvicorn、OpenAI SDK、FastMCP、React、Vite、Electron 和 tiktoken，以及文档、PDF 与浏览器工具所需的辅助库。确切版本以 `agent-alpha/pyproject.toml`、`agent-alpha/uv.lock` 和 `agent-alpha/frontend/package-lock.json` 为准。

### 安装与使用

以下命令均在 `agent-alpha` 目录中执行。

#### 1. 初始化环境

```powershell
cd agent-alpha
powershell -ExecutionPolicy Bypass -File .\setup-agent-alpha.ps1
```

脚本会创建 Python 3.12 虚拟环境、安装后端依赖和 Agent Alpha，并准备独立的 Browser Harness 工具环境。

#### 2. 配置模型

模型列表与默认模型位于 `agent-alpha/config/llm_profiles.json`。API Key 等本地服务配置放在 `agent-alpha/config/runtime_env.local.json`，配置项名称应与所选模型的 `api_key_env` 一致。例如：

```json
{
  "DEEPSEEK_API_KEY": "your-api-key"
}
```

该文件用于本机配置，不应提交凭据。

#### 3. 启动

CLI：

```powershell
.\start-agent-alpha.ps1
```

Web 开发入口：

```powershell
.\start-alpha-web.bat
```

Electron 桌面容器：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\scripts\prepare-desktop.ps1
```

桌面准备脚本会安装前端依赖、构建页面并创建本地启动快捷方式。Web 和 Electron 共用后端能力；正式打包时，前端容器不依赖浏览器作为产品界面。

## 核心设计

### 多智能体协作

多智能体不是在一个对话里模拟多个名字，而是创建彼此独立、可以持续通信的 Agent 实例。

每个 Agent 都有自己的身份、上下文、会话历史、运行检查点和执行进程；它们共享用户指定的项目工作区，因此可以直接协作同一批文件。主 Agent 可以创建、引导、等待、重命名和停止子 Agent，子 Agent 之间也可以按稳定 ID 互相通信。

消息系统同时处理用户输入和 Agent 间消息：

- Agent 运行中，消息会在安全的输入边界进入当前循环；
- Agent 空闲时，新的任务或协作消息可以重新唤醒它；
- 等待不会阻塞其他 Agent 工作，完成、失败或提问都能被接回；
- 同一个 Agent 始终只运行一个执行循环，避免上下文和文件操作互相覆盖。

实例关系没有被写死成单一形态，因此同一套底座可以表达单 Agent、平等多 Agent、领导 Agent 与多个执行 Agent，以及负责记忆整理、审核或代替用户沟通的专用 Agent。

权限不会因为委托而自动放大。每个 Agent 的本地进程都受独立生命周期管理，停止一个 Agent 时不会顺带结束其他 Agent；应用退出时则统一回收自身管理的执行资源。

### 自进化记忆

自进化记忆的目标不是无限积累聊天记录，而是让长期记忆能够根据新证据主动整理、修订和淘汰。

记忆分为三个相互约束的对象：

- `user.md`：用户明确表达、长期有用的背景、偏好和协作要求；
- `memory.md`：经过确认的环境事实、通用经验和跨任务知识；
- Skill references：与具体能力直接相关的方法、限制和验证经验。

整理流程由两个职责分离的 Agent 完成：

```text
对话与运行日志
    ↓
整理 Agent：读取证据并提出修改
    ↓
审核 Agent：回到原始记录逐项核对
    ↓
受限记忆工具：新增、修订、合并或删除失效内容
```

这套机制强调：记忆必须有证据；新结论保留适用范围；重复内容合并；错误或过时内容及时修订或删除。记忆是可更新的外部资料，不是不可质疑的指令，也不修改模型参数。

记忆更新支持自动整理和用户手动触发，并保留有限历史版本。新建或恢复的 Agent 实例读取最新记忆，Skill references 仍按需加载，不把所有资料长期塞进上下文。

设计细节见 [自进化记忆草稿.md](自进化记忆草稿.md)。

## Harness 与运行机制

### Runtime 与 Agent Loop

`AgentRuntime` 是单个 Agent 实例的运行边界。它在创建时组装模型配置、角色、工作区、Skill、工具、提示词、上下文管理器和中断信号，再把每轮输入交给 `AgentLoop`。

```text
接收输入 → 调用模型 → 执行工具 → 写入结果 → 再次调用模型 → 输出结果
```

循环会保存检查点，处理工具异常、模型响应异常、中断和消息插入，并修复不完整的工具调用历史。长会话接近上下文阈值时，由 `ContextManager` 压缩较早历史，同时保留最近对话和关键状态。

### Session 与消息

Session 保存用户可见历史、模型运行历史、工作区、运行检查点、事件和元数据。CLI、Web 与多 Agent 共用同一套会话结构。

Web 由 `AgentManager` 负责调度：它创建 Agent 实例、保存实时检查点、处理中断与恢复，并协调子 Agent 消息。执行过程位于受管理的工作进程中，使 Agent 可以被独立停止，并在应用退出时统一清理。

### Tool、Skill 与 MCP

所有能力通过统一的 `ToolLoader` 进入 Agent Loop：

- 内置工具提供命令执行、文件读写、搜索和内容获取；
- Skill 以 `SKILL.md` 为入口，可以携带脚本、参考资料和资源；
- MCP 用于接入外部工具服务；
- Browser Harness 提供有状态的浏览器操作，并使用 Alpha 自己的浏览器资料目录。

系统提示词只放 Skill 摘要，正文在真正需要时按需加载。这样既能保留复杂工作流，又不会让所有能力长期占用上下文。

### 环境与路径

Agent Alpha 不依赖启动目录猜测路径。Harness 根目录由代码位置确定，当前 Agent 的 `workspace_root` 则来自 Web 项目或 CLI 会话。

| 路径 | 用途 |
| --- | --- |
| `agent-alpha/.venv` | uv 管理的 Python 3.12 环境 |
| `agent-alpha/workspace` | CLI 默认工作区 |
| `agent-alpha/config` | 模型、服务和运行配置 |
| `agent-alpha/home` | Agent 本地主目录与第三方 Skill |
| `agent-alpha/cache` | Python、uv、npm、浏览器等缓存 |
| `agent-alpha/state` | Web、浏览器和其他持久运行状态 |
| `agent-alpha/temp` | 可清理的中间产物与临时运行文件 |
| `agent-alpha/session-log` | 会话快照、事件与实时日志 |

`HOME`、`APPDATA`、`TEMP`、Python、npm 和常用缓存路径会尽量收口到 Harness 内，减少宿主机污染，也为多实例隔离和桌面打包提供稳定边界。完整映射见 [路径管理说明.md](agent-alpha/路径管理说明.md)。

### 后端、会话与日志

本地 FastAPI Gateway 提供项目、会话、聊天、设置、文件和运行时接口。前端只通过这些接口交互，不直接拥有 Agent Runtime，因此入口可以替换而不改变执行核心。

运行数据主要保存在：

- `session-log/sessions/*.json`：可恢复的会话快照；
- `session-log/events/*.jsonl`：供界面读取的执行事件；
- `session-log/logs/*.jsonl`：追加写入的模型、工具和运行日志；
- `state/web/app_state.json`：Web 项目与应用状态。

日志采用 UTF-8 和逐行追加写入；会话快照通过临时文件替换，减少异常退出时留下半份状态的风险。日志和界面事件分开保存：前者用于追踪真实执行，后者用于稳定呈现进度。

### 权限与沙箱

安全边界围绕“工作区可用、运行时受保护、外部路径谨慎处理”展开：工作区内允许完成任务所需的读写；Harness 核心代码和日志目录受到额外保护；Harness 外允许读取，但普通写入、覆盖、移动和删除会被拒绝或要求授权；子 Agent 不因委托而获得额外权限。

沙箱会在工具执行前统一检查路径和命令，权限询问由 Gateway 返回到当前入口，因此 Web、CLI 和桌面端可以共用同一套安全规则。

### 项目结构

```text
agent-alpha/
├─ agent/
│  ├─ cli/            # CLI 入口
│  ├─ core/           # Runtime、Loop、会话、上下文、权限与协作
│  ├─ server/         # FastAPI Gateway
│  ├─ runtime/        # 消息总线与定时任务基础设施
│  └─ tools/          # 内置工具与浏览器适配
├─ frontend/          # React / Vite / Electron
├─ skills/            # 内置 Skill
├─ mcp-servers/       # MCP 服务与注册表
├─ config/            # 模型与本地运行配置
├─ workspace/         # CLI 默认工作区
├─ session-log/       # 会话、事件与日志
├─ state/             # 持久运行状态
└─ temp/              # 中间产物
```

---

<a id="english"></a>

## English

[中文](#中文)

### Positioning

Agent Alpha is a local Agent Runtime / Harness for real work, multi-agent collaboration, and evolving long-term memory.

It is more than a chat UI or a single model call. It organizes models, sessions, context, tools, skills, permissions, workspaces, and runtime state into one persistent local system.

CLI, Web, and Electron are channel adapters over the same FastAPI control plane, session orchestration, and Agent Runtime. The UI can therefore move from browser-based development to a desktop container without rebuilding the execution core.

Agent Alpha focuses on completing real work in local workspaces, coordinating multiple agents, and maintaining revisable, traceable memory from long-term collaboration.

### Architecture at a Glance

```text
CLI / Web / Electron
        ↓
FastAPI Gateway
        ↓
Message and Session Orchestration
        ↓
Context / Prompt Assembly
        ↓
Agent Runtime → Agent Loop
        ↓
Tool / Skill / MCP / Browser
        ↓
Permissions and Sandbox → Workspace / Memory / State
```

| Layer | Responsibility |
| --- | --- |
| Channel Layer | CLI, Web, and Electron input and presentation |
| Gateway Control Plane | FastAPI APIs, runtime state, configuration, and lifecycle |
| Message and Session Orchestration | Delivery, queues, interruption, recovery, and collaboration |
| Context / Prompt Assembly | System prompts, workspace documents, history, and compression |
| Agent Runtime / Harness | Models, roles, tools, workspaces, and runtime state |
| Agent Loop | The model → tool → result → model execution cycle |
| Tool / Skill / Plugin Layer | Local tools, skills, MCP, and browser capabilities |
| Permissions / Sandbox / Security | Path boundaries, command checks, and user approval |
| Workspace / Memory / State | Files, snapshots, logs, memory, and persistent state |

See [harness设计.md](harness设计.md) for the detailed layer model.

### Requirements

The current runtime is Windows-oriented and requires PowerShell, [uv](https://docs.astral.sh/uv/), Python 3.12, Node.js and npm, plus a supported model service and API key.

Core components include FastAPI, Uvicorn, the OpenAI SDK, FastMCP, React, Vite, Electron, and tiktoken. Exact versions are defined by `agent-alpha/pyproject.toml`, `agent-alpha/uv.lock`, and `agent-alpha/frontend/package-lock.json`.

### Installation and Usage

Run the following commands from `agent-alpha`.

#### 1. Prepare the environment

```powershell
cd agent-alpha
powershell -ExecutionPolicy Bypass -File .\setup-agent-alpha.ps1
```

This creates the Python 3.12 environment, installs Agent Alpha and its backend dependencies, and prepares the isolated Browser Harness tool environment.

#### 2. Configure a model

Model profiles and the default profile live in `agent-alpha/config/llm_profiles.json`. Local API keys and service settings live in `agent-alpha/config/runtime_env.local.json`. The key name must match the selected profile's `api_key_env`:

```json
{
  "DEEPSEEK_API_KEY": "your-api-key"
}
```

Keep credentials local and out of version control.

#### 3. Start Agent Alpha

CLI:

```powershell
.\start-agent-alpha.ps1
```

Web development entry:

```powershell
.\start-alpha-web.bat
```

Electron desktop container:

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\scripts\prepare-desktop.ps1
```

The desktop preparation script installs frontend dependencies, builds the UI, and creates a local launcher. Web and Electron share the same backend; the packaged desktop direction does not depend on a browser as the product UI.

## Core Designs

### Multi-Agent Collaboration

Multi-agent collaboration creates independent, persistent agent instances rather than simulating several names in one conversation.

Each agent has its own identity, context, history, checkpoint, and execution process. Agents share the selected project workspace, so they can collaborate on the same files. A lead agent can create, guide, wait for, rename, and stop subagents, while peer agents communicate through stable IDs.

Messages enter a running agent at safe input boundaries and can wake an idle agent. Waiting does not block other agents, and results, failures, or questions can resume the lead agent. Each agent has only one active execution loop, preventing overlapping context and file operations.

The same runtime can represent a single agent, peer collaboration, a lead agent with several workers, or specialized agents for memory organization, review, and user-proxy communication.

Delegation does not expand permissions automatically. Each agent has an independently managed local process lifecycle, while application shutdown can reclaim all managed resources.

### Evolving Memory

Evolving memory is not an ever-growing chat archive. It revises, consolidates, and retires long-term memory as new evidence appears.

Memory has three constrained targets:

- `user.md` for explicit, durable user context, preferences, and collaboration requirements;
- `memory.md` for verified environment facts, reusable experience, and cross-task knowledge;
- Skill references for methods, limitations, and validated experience tied to a capability.

```text
Conversation and Runtime Logs
    ↓
Organizer Agent: reads evidence and proposes changes
    ↓
Reviewer Agent: verifies every item against original records
    ↓
Restricted Memory Tool: adds, revises, merges, or removes content
```

Memory requires evidence, preserves the scope of each conclusion, merges duplicates, and revises or removes outdated content. It is revisable external material, not an unquestionable instruction or a model-weight update.

Updates can run automatically or be triggered by the user, with a limited version history. New or restored agents read the latest memory, while Skill references remain available on demand instead of permanently occupying context.

See [自进化记忆草稿.md](自进化记忆草稿.md) for details.

## Harness and Runtime Mechanics

### Runtime and Agent Loop

`AgentRuntime` is the execution boundary of one agent. It assembles the model profile, role, workspace, skills, tools, prompt, context manager, and interrupt signal, then delegates each request to `AgentLoop`.

```text
receive input → call model → execute tools → record results → call model again → return
```

The loop persists checkpoints, handles tool and model failures, accepts interruptions and inserted messages, and repairs incomplete tool-call history. `ContextManager` compresses older history near the context threshold while preserving recent turns and essential state.

### Sessions and Messages

A session stores user-facing history, model runtime history, workspace, checkpoints, events, and metadata. CLI, Web, and multi-agent execution share the same session model.

`AgentManager` schedules Web and desktop work, creates agents, persists live checkpoints, handles interruption and recovery, and coordinates subagent messages. Managed worker processes allow one agent to stop independently and let the application clean up its own resources on exit.

### Tools, Skills, and MCP

All capabilities enter the Agent Loop through `ToolLoader`. Built-in tools provide commands, files, search, and fetching; Skills may include instructions, scripts, references, and assets; MCP connects external services; Browser Harness provides stateful browser work in an Alpha-owned browser profile.

Only Skill summaries stay in the system prompt. Full instructions load on demand, preserving complex workflows without permanently consuming context.

### Environment and Paths

The Harness root comes from the code location rather than the current working directory. An agent's `workspace_root` comes from its Web project or CLI session.

| Path | Purpose |
| --- | --- |
| `agent-alpha/.venv` | uv-managed Python 3.12 environment |
| `agent-alpha/workspace` | default CLI workspace |
| `agent-alpha/config` | model, service, and runtime configuration |
| `agent-alpha/home` | local agent home and third-party Skills |
| `agent-alpha/cache` | Python, uv, npm, and browser caches |
| `agent-alpha/state` | persistent Web, browser, and runtime state |
| `agent-alpha/temp` | disposable artifacts and temporary files |
| `agent-alpha/session-log` | snapshots, events, and realtime logs |

`HOME`, `APPDATA`, `TEMP`, Python, npm, and common cache paths are redirected into the Harness where possible. This reduces host pollution and provides stable boundaries for multiple instances and desktop packaging. See [路径管理说明.md](agent-alpha/路径管理说明.md) for the full mapping.

### Backend, Sessions, and Logs

The local FastAPI Gateway exposes project, session, chat, settings, file, and runtime APIs. Frontends use these APIs rather than owning the Agent Runtime, so channels can change without changing the execution core.

Runtime data is primarily stored in:

- `session-log/sessions/*.json` for recoverable snapshots;
- `session-log/events/*.jsonl` for UI-facing events;
- `session-log/logs/*.jsonl` for append-only model, tool, and runtime logs;
- `state/web/app_state.json` for Web project and application state.

Logs use UTF-8 JSON Lines. Session snapshots use temporary-file replacement to reduce partial state after an abnormal exit. Diagnostic logs and UI events remain separate so execution evidence and progress presentation can evolve independently.

### Permissions and Sandbox

Work required by a task is allowed inside the workspace. Core Harness code and logs receive additional protection. External paths may be read, but ordinary writes, overwrites, moves, and deletes are rejected or require approval. Subagents do not gain extra permission merely because a lead agent delegated work.

The sandbox checks paths and commands before execution, while approval requests travel through the Gateway to the active channel. Web, CLI, and desktop therefore share one security policy.

### Repository Layout

```text
agent-alpha/
├─ agent/
│  ├─ cli/            # CLI channel
│  ├─ core/           # Runtime, loop, sessions, context, security, collaboration
│  ├─ server/         # FastAPI Gateway
│  ├─ runtime/        # message bus and cron foundations
│  └─ tools/          # built-in tools and browser integration
├─ frontend/          # React / Vite / Electron
├─ skills/            # built-in Skills
├─ mcp-servers/       # MCP services and registry
├─ config/            # model and local runtime configuration
├─ workspace/         # default CLI workspace
├─ session-log/       # sessions, events, and logs
├─ state/             # persistent runtime state
└─ temp/              # temporary artifacts
```
