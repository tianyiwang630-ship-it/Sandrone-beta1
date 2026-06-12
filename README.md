# agent-alpha

[中文](#中文) | [English](#english)

<a id="top"></a>

---

<a id="中文"></a>

## 中文

<a id="zh-contents"></a>

### 目录

- [项目定位](#zh-positioning)
- [第一部分：现有设计](#zh-current-design)
- [环境管理层](#zh-environment)
- [Skill 安装与加载机制](#zh-skills)
- [浏览器自动化设计](#zh-browser)
- [沙盒设计](#zh-sandbox)
- [其他现有设计](#zh-other)
- [第二部分：未来方向](#zh-future)
- [Agent 实例化](#zh-instantiation)
- [新的 Subagent 工具设计](#zh-subagent)
- [持续运行模式](#zh-continuous)
- [自动审查机制](#zh-auto-review)
- [自我模块与记忆](#zh-self)
- [当前状态与近期目标](#zh-status)

agent-alpha 是一个面向可编排场景的 agent 运行时。

它关心的不只是“调用模型并返回答案”，而是把 agent 真正长期运行所需要的底座收拢起来：环境管理、skill 安装与加载、浏览器自动化、沙盒边界、循环执行、上下文压缩和会话状态。

当前重点不是继续堆更多能力，而是先把运行时底座做得更稳定、更清晰，也更适合以后成为多 agent 系统里的一个标准实例。

<a id="zh-positioning"></a>

### 项目定位

[返回目录](#zh-contents)

可以把 agent-alpha 理解成一个正在持续收束的 agent 内核。

它不是单纯的聊天壳子，也不只是一个“会调工具”的脚本，而是试图把下面这些东西放进同一个运行时里：

- agent 的循环执行
- 上下文压缩与会话延续
- tool / skill / MCP 的接入
- 运行环境的项目内收口
- 浏览器状态管理
- 文件系统与命令执行边界

当前目标是先把单个 agent 实例打磨清楚，让它以后可以自然长成多 agent 平台中的标准实例。

<a id="zh-current-design"></a>

### 第一部分：现有设计

[返回目录](#zh-contents)

这一部分讲 agent-alpha 现在已经存在、并且最值得优先理解的运行时设计。

<a id="zh-environment"></a>

#### 环境管理层

[返回目录](#zh-contents)

环境管理是 agent-alpha 最核心的设计之一。

普通脚本通常直接继承宿主机环境，初期看起来很省事，但很快就会出现缓存散落、配置混杂、状态难复现、多实例难并行的问题。

agent-alpha 的做法是尽量把运行时状态收口到项目内部。

像 `HOME`、`USERPROFILE`、`APPDATA`、`LOCALAPPDATA`、`TMP`、`TEMP`、缓存路径、浏览器缓存路径等关键变量，都会尽量重定向到项目内。详细映射可以看 [路径管理说明.md](/D:/files/demo/0312-newagent/agent-alpha/路径管理说明.md)。

运行时也会优先使用这些项目内目录：

- `home/`
- `config/`
- `cache/`
- `data/`
- `state/`
- `temp/`
- `workspace/`
- `bin/`

长期服务配置，例如 token、cookie、API key、auth header、proxy，会放到：

`agent-alpha/config/runtime_env.local.json`

这个文件用于保存服务配置，不用于覆盖核心路径策略。

Python 运行环境和 Python CLI 安装会优先收敛到：

`agent-alpha/.venv`

也就是说，alpha 希望把自己的 Python 运行、Python 包和 Python CLI 都尽量汇到一个本地虚拟环境里，而不是散到用户级 Python 目录。

对 agent-alpha 来说，环境管理不是附属能力，而是运行时设计本身的一部分。

<a id="zh-skills"></a>

#### Skill 安装与加载机制

[返回目录](#zh-contents)

这里最关键的不是“怎么读一个 `SKILL.md`”，而是 agent-alpha 怎样把一个第三方 skill 仓库真正安装进自己的运行时。

agent-alpha 把 skill 看成复合能力单元，而不是几段静态 prompt。也正因为这样，它可以顺着 skill 仓库里的安装说明，把依赖、脚本和参考资料一起接进 alpha 的本地运行时。

##### 安装链路

当前安装型 skill 的基本流程大致是：

1. 识别来源：本地目录、GitHub 仓库、GitHub 子路径
2. 如果来源在 GitHub，就先把仓库拉到 `agent-alpha/temp/skill-install/...`
3. 先读安装文档，例如 `README.md`、`INSTALL.md` 和 README 明确引用的本地文档
4. 找出 `SKILL.md` 候选
5. 决定 skill 名称
6. 把 skill 本体复制到 `agent-alpha/home/.agents/skills/<skill-name>`
7. 按 alpha 的运行时规则改写第三方 README 里的路径和依赖命令

关键点在于：agent-alpha 安装 skill 时，不是只复制一个目录，而是会顺着 skill 仓库的说明，理解这个 skill 还依赖什么，然后把这些依赖翻译到 alpha 自己的运行时体系里。

##### 为什么可以顺便安装 skill 依赖

因为 skill 安装流程本来就会先读 skill 仓库的安装文档，而不是盲目复制目录。

这意味着安装器在复制 skill 本体之前，就可以先解析：

- 这个 skill 需要哪些 Python 包
- 是否依赖 Python CLI
- 是否依赖 npm 全局工具
- 是否依赖 Go 工具
- 是否需要额外脚本、模板或参考文档

然后再把这些依赖命令翻译成 alpha 能接受的形式。

例如：

- Python 依赖和 Python CLI 优先安装到 `agent-alpha/.venv`
- npm / pnpm / yarn / Go 的全局工具继续保留宿主机全局语义
- 原 README 里如果写的是 `~/.claude/skills/...`、`C:\Users\<user>\...`、用户目录配置文件等路径，会被改写成 alpha 自己的路径体系，而不是直接照抄

所以 agent-alpha 能装“复杂 skill”，不是因为它支持某种神奇格式，而是因为它把 skill 安装当成一条完整工作流：先读文档，再翻译路径和依赖命令，最后再安装。

##### 两层 skill 路径

当前 skill loader 会读取两层目录：

- 主路径：`agent-alpha/skills/<skill-name>`
- 安装路径：`agent-alpha/home/.agents/skills/<skill-name>`

当两个地方存在同名 skill 时，主路径优先。

这意味着：

- `skills/` 更适合内置 skill、覆盖版本、项目正式能力
- `home/.agents/skills/` 更适合安装型 skill、第三方 skill、实验性 skill

##### `load_skill` 的作用

skill 的完整正文不会在一开始全部塞进提示词，而是先只暴露摘要信息；真正需要时，再通过 `load_skill` 按需读取全文。

这有两个直接好处：

- 减少常驻提示词体积
- 允许 skill 本体保持更完整、更复杂，因为只有真正需要时才会展开

它和安装链路是配套的：

- 安装时允许 skill 仓库保留比较真实的说明、脚本和资源结构
- 运行时再用 `load_skill` 按需展开，而不是一开始把所有 skill 全量压进系统提示词

##### 为什么能支持复杂、非标准化 skill

在 agent-alpha 里，一个 skill 不一定只有 `SKILL.md`。它还可以带：

- `scripts/`
- `references/`
- `assets/`
- 其他配套文件

这使得一个 skill 可以表达更完整的工作流：安装第三方工具、调用脚本、读取参考资料、使用模板，而不需要强迫所有能力都先被压扁成一种统一 API 形状。

<a id="zh-browser"></a>

#### 浏览器自动化设计

[返回目录](#zh-contents)

在 agent-alpha 里，浏览器能力不是一个普通工具，而是运行时中的一个有状态子系统。

这里真正重要的点是：profile 怎样进入 alpha、三种模式怎样共享或隔离状态，以及这套设计怎样支持以后多 agent 并行。

##### 主 profile 的来源

当前浏览器体系里有一个默认主 profile，也就是 `default`。

这个 `default` 不是凭空创建的空目录，而是可以通过下面这个脚本，把宿主机现有 Chrome profile 同步进来：

`agent-alpha/sync-chrome-profile5-to-alpha.ps1`

这个脚本会把宿主机 Chrome 的 `Profile 5` 和对应的 `Local State` 复制到：

`agent-alpha/state/browser/profiles/default/user-data`

并把元数据映射成 alpha 内部使用的 `Default`。

这意味着，alpha 的默认主 profile 可以直接承接用户电脑上已经存在的真实登录态和浏览器环境，而不是从一个全新的空 profile 开始。

##### 可视模式

可视模式直接使用这个持久 profile。

它更适合：

- 首次登录
- 人工观察
- 调试页面行为
- 明确需要“看到浏览器在做什么”的场景

关键行为是：

- 有头模式直接使用持久 profile
- 运行期间会给这个 profile 加锁，避免另一个有头会话同时占用
- 关闭时 profile 会保留，不会被删掉

所以有头模式本质上是在“直接使用并持续维护主 profile”。

##### 无头模式

无头模式不是直接在主 profile 上跑，而是先复制一份持久 profile 到临时 runtime 目录，再基于这份副本执行。

运行结束后，临时副本会被删除。

这有几个直接好处：

- 主 profile 不会被后台任务直接污染
- 多个无头会话可以并行存在
- 后续多 agent 模式下，可以并行跑多个浏览器任务

换句话说，无头模式采用的是“复制主 profile -> 运行 -> 删除副本”的策略，重点是隔离和并行能力。

##### CDP 接管模式

CDP 模式和上面这套本地 profile 生命周期不是一回事。

它的职责是直接连接用户自己管理的浏览器，通过 CDP 端口、HTTP URL 或 WebSocket URL 接管现有浏览器上下文。

所以：

- CDP 不依赖 alpha 的主 profile 副本机制
- CDP 不要求走 `state/browser/profiles/...` 这套生命周期
- 它更像“接入外部用户浏览器”，而不是“在 alpha 的本地 profile 体系里启动一个浏览器”

这点需要明确写清楚，否则很容易误会成 CDP 也是本地 profile 持久化机制的一种。

##### 浏览器状态布局

当前浏览器状态集中落在 `state/browser/` 下，包含：

- `profiles/`
- `sessions/`
- `sockets/`
- `downloads/`
- `runtime/`
- `profiles.json`

大致分工是：

- `profiles/`：持久 profile
- `runtime/`：无头模式的临时副本
- `sessions/`、`sockets/`、`downloads/`：每次浏览器运行过程中的会话状态

这套拆分是有意的：

- 有头模式保留持久 profile
- 无头模式消耗临时副本
- CDP 模式直接接用户浏览器，不进入这套本地副本生命周期

<a id="zh-sandbox"></a>

#### 沙盒设计

[返回目录](#zh-contents)

沙盒的目标不是让 agent 什么都不能做，而是让它在可用和可控之间保持边界。

当前规则大致可以理解为：

- `workspace` 内：为了完成任务，允许读写
- `agent-alpha` 项目内：允许运行时所需的大多数读写
- 项目内受保护路径：修改需要更明确的用户意图
- 项目外：允许读取，也允许执行外部 CLI，但不允许普通文件随意写入或删除

当前明确受保护的路径包括运行时核心代码，例如：

- `agent/core`
- `agent/tools`

运行时还必须处理一个现实问题：很多第三方工具并不装在项目内，而是在 npm 全局目录、Go 全局目录，或者宿主机 PATH 的其他位置。

所以 alpha 的策略是：

- 允许执行外部 CLI
- 但继续阻止下面这些越界写入行为：
  - 把输出显式写到允许边界之外
  - 重定向到项目外文件
  - 在项目外执行 copy、move、overwrite、delete

本质上，这套设计追求的是平衡：

- 让 agent 能调用真实外部能力
- 同时限制它越界改写运行时之外的普通文件

<a id="zh-other"></a>

#### 其他现有设计

[返回目录](#zh-contents)

除了上面四块，agent-alpha 当前还已经具备一些运行时底座：

- `AgentLoop`：多步循环执行
- `ContextManager`：token 统计与历史压缩
- session snapshot 和日志：用于 CLI 恢复
- 内置工具、skill、MCP 的统一加载
- `cron`、message bus、session kind 等早期基础设施

这些不是 README 的主标题，但它们已经是运行时地基的一部分。

<a id="zh-future"></a>

### 第二部分：未来方向

[返回目录](#zh-contents)

这一部分讲的是：为什么现在要这样设计，以及接下来准备往哪里长。

<a id="zh-instantiation"></a>

#### Agent 实例化

[返回目录](#zh-contents)

未来的 agent-alpha 不应该只是一份项目代码，而应该能被抽象成一个 agent 实例。

一个实例理想上应当拥有自己的：

- 工作路径
- 人格文档
- skill 集
- 环境变量
- 会话状态
- 安全边界
- 浏览器资源

这也是为什么现在这么强调本地路径、状态隔离和显式边界。它们本质上都是在为未来的实例化编排铺路。

<a id="zh-subagent"></a>

#### 新的 Subagent 工具设计

[返回目录](#zh-contents)

未来的 subagent 不应只是“再调用一次模型”，而应该是“把另一个 agent 当成能力来调用”。

这意味着需要更清楚地处理：

- 继承哪些上下文
- 裁掉哪些上下文
- 使用哪个 workspace
- 继承哪些权限
- 如何回传执行结果

当这一层成熟后，编排会从“一个 agent 调很多工具”转向“一个 agent 协调其他 agent”。

<a id="zh-continuous"></a>

#### 持续运行模式

[返回目录](#zh-contents)

未来希望增加一种目标驱动的持续运行模式，它的输入不是一句普通请求，而是一组更明确的约束：

- 目标
- 成功标准
- 约束条件
- 最大轮数

理想中的循环是：

1. 执行 agent 负责推进任务
2. 监督 agent 负责对照当前现状、成功标准和约束做检查
3. 如果没达标且轮数没用完，就继续推进
4. 达标或触发停止条件后结束

这个方向的意义，是让 agent 从“一次响应”走向“在明确目标下持续推进任务”。

<a id="zh-auto-review"></a>

#### 自动审查机制

[返回目录](#zh-contents)

未来的 sandbox 不希望只靠硬编码规则来拒绝命令。

更理想的方向是混合机制：

- 如果命中明确红线黑名单，直接拒绝
- 如果不是红线命令，就进入 LLM 二次审查

二次审查关注的不是“这个命令看起来危险不危险”，而是：

- 是否会在允许目录外修改文件
- 是否包含越界写入、覆盖、移动、删除
- 是否只是执行外部 CLI 而没有写出边界

`npm` 和 `go` 的全局安装路径可以继续作为特殊例外，其它普通外部写入默认保持更严格。

目标是把拒绝理由结构化返回给 agent，让它知道“为什么不行、差在哪、要怎么改”。

<a id="zh-self"></a>

#### 自我模块与记忆

[返回目录](#zh-contents)

未来的“自我模块”希望成为一个明确的运行时层，而不是一个模糊的人格概念。

当前设想主要有三层：

- 初始化身份定义
- 离线总结层
- 实时自评层

离线总结层会整理：

- alpha 和用户之间的关系状态
- 当前项目所处阶段
- 长期偏好与约定

实时自评层会判断类似问题：

- 我现在有没有偏离目标
- 我有没有误解用户意图
- 我是不是过于激进或过于保守
- 当前动作是否还符合既定角色和边界

这里追求的不是抽象的“意识”，而是连续性、自我修正能力和更好的长期协作表现。

<a id="zh-status"></a>

#### 当前状态与近期目标

[返回目录](#zh-contents)

当前阶段，agent-alpha 的重点仍然是继续把运行时底座收紧，而不是一下把所有未来能力都做完。

近期目标主要包括：

- 继续完善 agent 实例化
- 把 skill 安装和加载体验做得更稳
- 补强 subagent、cron、持续运行模式的基础
- 在不增加无谓复杂度的前提下继续简化运行时结构

---

<a id="english"></a>

## English

<a id="en-contents"></a>

### Contents

- [Positioning](#en-positioning)
- [Part I: Current Design](#en-current-design)
- [Environment Management](#en-environment)
- [Skill Installation and Loading](#en-skills)
- [Browser Automation](#en-browser)
- [Sandbox Design](#en-sandbox)
- [Other Existing Runtime Pieces](#en-other)
- [Part II: Future Directions](#en-future)
- [Agent Instantiation](#en-instantiation)
- [New Subagent Tooling](#en-subagent)
- [Goal-Driven Continuous Execution](#en-continuous)
- [Automatic Review for Rejected Commands](#en-auto-review)
- [Self Module and Memory](#en-self)
- [Current Status and Near-Term Goals](#en-status)

agent-alpha is an agent runtime for orchestrated work.

It is not just a chat shell that calls a model and returns text. It tries to unify the parts an agent needs to run for real: environment management, skill installation and loading, browser automation, sandbox boundaries, execution loops, context compression, and session state.

The current goal is not to keep adding more surface area. The goal is to make the runtime more stable, clearer to reason about, and ready to become one reusable agent instance inside a future multi-agent system.

<a id="en-positioning"></a>

### Positioning

[Back to Contents](#en-contents)

You can think of agent-alpha as an agent core that is still being tightened and simplified.

It tries to bring these concerns into one runtime:

- agent execution loops
- context compression and session continuity
- tool / skill / MCP integration
- project-local environment isolation
- browser state management
- file and command boundaries

The near-term direction is to make a single agent instance solid enough that it can later become a standard instance in a larger multi-agent platform.

<a id="en-current-design"></a>

### Part I: Current Design

[Back to Contents](#en-contents)

This part focuses on the runtime pieces that already exist and matter most today.

<a id="en-environment"></a>

#### Environment Management

[Back to Contents](#en-contents)

Environment management is one of the core design choices in agent-alpha.

Most scripts inherit the host machine environment directly. That feels easy at first, but it quickly creates scattered caches, mixed config, hard-to-reproduce state, and awkward migration problems when you want multiple agent instances later.

agent-alpha instead tries to pull runtime state into the project itself.

Key runtime variables such as `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TMP`, `TEMP`, cache paths, and browser cache paths are redirected into project-local directories. The detailed mapping is documented in [路径管理说明.md](/D:/files/demo/0312-newagent/agent-alpha/路径管理说明.md).

The runtime also keeps project-local folders for:

- `home/`
- `config/`
- `cache/`
- `data/`
- `state/`
- `temp/`
- `workspace/`
- `bin/`

Persistent service configuration such as tokens, cookies, API keys, auth headers, and proxies lives in:

`agent-alpha/config/runtime_env.local.json`

That file is for service variables, not for overriding core path policy.

Python runtime and Python CLI installation are intentionally pulled into:

`agent-alpha/.venv`

That means the runtime, Python packages, and Python CLI tools are meant to converge on one local Python environment rather than spreading across user-level Python locations.

In short: for agent-alpha, environment management is part of the runtime design, not an afterthought.

<a id="en-skills"></a>

#### Skill Installation and Loading

[Back to Contents](#en-contents)

The key point here is not just how to read `SKILL.md`, but how agent-alpha installs a third-party skill repository into its own runtime.

agent-alpha treats a skill as a compound capability unit rather than a few static prompt snippets. Because of that, it can follow the skill repository's installation docs and bring dependencies, scripts, and reference material into the alpha runtime along with the skill itself.

##### Installation Flow

The installation flow is roughly:

1. Identify the source: local directory, GitHub repo, or GitHub subpath
2. If the source is on GitHub, pull it into `agent-alpha/temp/skill-install/...`
3. Read installation docs first, such as `README.md`, `INSTALL.md`, and locally linked docs
4. Find `SKILL.md` candidates
5. Decide the skill name
6. Copy the skill body into `agent-alpha/home/.agents/skills/<skill-name>`
7. Rewrite third-party paths and dependency commands into alpha-compatible runtime paths and commands

That last part is the reason complex skills can be installed at all: alpha does not merely copy a folder. It interprets how that skill is supposed to be installed and adapts the instructions into alpha's runtime model.

##### Why skill dependencies can be installed as part of skill installation

Because the installer reads the skill repository's docs before copying the skill, it can also inspect:

- required Python packages
- Python CLI dependencies
- npm global tools
- Go tools
- extra scripts, templates, or reference docs

It can then translate those dependency steps into alpha's runtime rules.

For example:

- Python packages and Python CLI tools are meant to install into `agent-alpha/.venv`
- npm / pnpm / yarn / Go global tools keep their host-global behavior
- README paths such as `~/.claude/skills/...`, `C:\Users\<user>\...`, or shell-profile edits are translated into alpha-local paths or alpha-local config when possible

So agent-alpha supports complex, non-standardized skills not because of a magical format, but because installation is treated as a workflow: read docs, translate paths, translate dependency commands, then install.

##### Two skill paths

The current loader reads two layers:

- primary path: `agent-alpha/skills/<skill-name>`
- install path: `agent-alpha/home/.agents/skills/<skill-name>`

If the same skill exists in both places, the primary path wins.

That gives two useful roles:

- `skills/` for built-in or project-owned skills
- `home/.agents/skills/` for installed third-party or experimental skills

##### What `load_skill` does

Skill bodies are not all stuffed into the prompt up front. The runtime first exposes summaries, and only loads the full body on demand through `load_skill`.

This helps in two ways:

- it keeps prompt overhead smaller
- it allows skills themselves to stay richer and more detailed because they are expanded only when needed

That fits naturally with the installation model: installation can preserve a realistic skill structure, while runtime disclosure can stay lightweight until a skill is actually needed.

##### Why complex, non-standardized skills fit here

In agent-alpha, a skill may include more than `SKILL.md`. It can also carry:

- `scripts/`
- `references/`
- `assets/`
- other supporting files

That means a skill can describe a fuller workflow: install a third-party tool, call scripts, consult reference docs, and use templates, all within one capability unit.

<a id="en-browser"></a>

#### Browser Automation

[Back to Contents](#en-contents)

Browser support in agent-alpha is not just one tool call. It is a stateful subsystem.

The important part is how profiles enter alpha, how the three modes share or isolate state, and how this design prepares the runtime for later parallel browser work.

##### The main profile

The browser system has a default persistent profile: `default`.

That profile is not meant to start empty. It can be synced from an existing host Chrome profile through:

`agent-alpha/sync-chrome-profile5-to-alpha.ps1`

That script copies the host machine's Chrome `Profile 5` plus its `Local State` into:

`agent-alpha/state/browser/profiles/default/user-data`

and remaps the metadata so alpha uses it as `Default`.

This matters because alpha can start from a real user browser state with real login sessions instead of a blank browser profile.

##### Headed mode

Headed mode directly uses the persistent profile.

It is the best fit for:

- first-time login
- manual observation
- debugging page behavior
- any situation where the user needs to see the browser

Key behavior:

- it uses the persistent profile directly
- it locks the profile while the headed session is active
- the profile is preserved when the session closes

So headed mode is really "use and maintain the main persistent profile directly."

##### Headless mode

Headless mode does not run on the persistent profile directly.

Instead it:

1. copies the persistent profile into a temporary runtime directory
2. runs the browser session on that copy
3. deletes the temporary copy after the run

This gives three important benefits:

- the main profile is not directly polluted by background runs
- multiple headless sessions can exist in parallel
- later multi-agent usage can run multiple browser tasks side by side

So headless mode is intentionally "copy profile -> run -> remove copy."

##### CDP mode

CDP mode is outside that local profile lifecycle.

Its job is to connect directly to a browser that the user already manages, through a CDP port, HTTP URL, or WebSocket URL.

That means:

- it does not depend on alpha's persistent-profile-copy model
- it does not need to participate in `state/browser/profiles/...` lifecycle rules
- it is better understood as "attach to the user's browser" rather than "launch a browser inside alpha's local profile system"

This distinction matters. CDP is not just another flavor of local profile persistence.

##### Browser state layout

Browser state is organized under `state/browser/`, including:

- `profiles/`
- `sessions/`
- `sockets/`
- `downloads/`
- `runtime/`
- `profiles.json`

The rough split is:

- `profiles/` for persistent profiles
- `runtime/` for temporary headless copies
- `sessions/`, `sockets/`, and `downloads/` for per-run browser state

That split is deliberate:

- headed mode preserves persistent profiles
- headless mode consumes temporary copies
- CDP works directly with the user's browser outside this copy lifecycle

<a id="en-sandbox"></a>

#### Sandbox Design

[Back to Contents](#en-contents)

The point of the sandbox is not to make the agent unable to work. The point is to keep it useful while preserving boundaries.

The current model is roughly:

- inside `workspace`: read and write are allowed for task work
- inside `agent-alpha`: most runtime reads and writes are allowed
- protected runtime paths: modifications should require clearer user intent
- outside the project: reading and executing external CLI tools may be allowed, but ordinary writes and deletes are not

Current protected paths include core runtime code such as:

- `agent/core`
- `agent/tools`

The runtime also needs to handle the practical case where third-party tools live outside the project, for example in npm global directories or Go global directories.

So the sandbox allows execution of external CLI tools, but still blocks things like:

- explicit output paths written outside allowed boundaries
- redirection to external files
- copy, move, overwrite, or delete operations outside the allowed runtime area

The design goal is a balance:

- let the agent use real external tools
- stop it from casually mutating files outside the runtime and workspace

<a id="en-other"></a>

#### Other Existing Runtime Pieces

[Back to Contents](#en-contents)

Besides the four major designs above, agent-alpha already has several other runtime pieces in place:

- `AgentLoop` for multi-step execution
- `ContextManager` for token counting and history compression
- session snapshots and logs for CLI recovery
- unified loading for built-in tools, skills, and MCP integrations
- early runtime infrastructure such as `cron`, message bus, and session kinds

These are not the headline design topics, but they are already part of the runtime foundation.

<a id="en-future"></a>

### Part II: Future Directions

[Back to Contents](#en-contents)

This part explains why the runtime is being shaped this way now, and what it is trying to become.

<a id="en-instantiation"></a>

#### Agent Instantiation

[Back to Contents](#en-contents)

In the future, agent-alpha should not just be a project folder. It should be abstractable as an agent instance.

An instance should be able to carry its own:

- workspace
- persona docs
- skill set
- environment variables
- session state
- safety boundaries
- browser resources

That is why so much effort goes into runtime-local paths, isolated state, and explicit boundaries now. Those are the foundations for instance-based orchestration later.

<a id="en-subagent"></a>

#### New Subagent Tooling

[Back to Contents](#en-contents)

The long-term idea is that a subagent should not just mean "call the model again."

It should mean "call another agent as a capability."

That requires clearer handling for:

- which context is inherited
- which context is cut away
- which workspace is used
- which permissions carry over
- how results are returned

Once that exists, orchestration moves from "one agent with many tools" toward "one agent coordinating other agents."

<a id="en-continuous"></a>

#### Goal-Driven Continuous Execution

[Back to Contents](#en-contents)

Another future direction is a continuous execution mode driven by:

- a goal
- success criteria
- constraints
- a maximum number of rounds

The intended loop is:

1. an execution agent pushes the work forward
2. a supervisory agent checks the current state against success criteria and constraints
3. if the work is not good enough and rounds remain, the execution agent continues
4. the loop stops when success is reached or the stop condition is hit

This would move the runtime from one-shot responses toward sustained goal-directed execution.

<a id="en-auto-review"></a>

#### Automatic Review for Rejected Commands

[Back to Contents](#en-contents)

The future sandbox model is not meant to be only hard-coded blocking rules.

The intended direction is a hybrid:

- if a command hits a clear red-line blacklist, reject it immediately
- if it is not a red-line command, let an LLM perform a second-stage review

That review should not guess whether a command "feels dangerous." It should check:

- whether it would modify files outside allowed directories
- whether it performs overwrite, move, delete, or write operations outside the boundary
- whether it only runs an external CLI without writing out of bounds

`npm` and `go` global installation paths may remain special cases, while most other external writes stay strict.

The result should be a structured explanation of why a command was blocked or what would need to change.

<a id="en-self"></a>

#### Self Module and Memory

[Back to Contents](#en-contents)

The future self module is intended as an explicit runtime layer, not just a vague personality concept.

The current idea has three parts:

- initial identity definition
- an offline summary layer that reviews logs and long-term history
- a real-time self-evaluation layer

The offline layer would summarize things like:

- the relationship between alpha and the user
- the current project state
- long-term preferences and standing agreements

The real-time layer would evaluate questions like:

- am I drifting away from the goal
- did I misunderstand the user
- am I being too aggressive or too hesitant
- does this action still fit my role and boundaries

The aim is not abstract "consciousness." The aim is continuity, self-correction, and better long-term collaboration behavior.

<a id="en-status"></a>

#### Current Status and Near-Term Goals

[Back to Contents](#en-contents)

Right now the main focus is still tightening the runtime instead of rushing every future idea into implementation.

Near-term goals include:

- improving agent instantiation
- making skill installation and loading more solid
- strengthening the groundwork for subagents, cron, and continuous execution
- simplifying the runtime without adding unnecessary complexity
