# OpenClaw 与 nanobot 的 agent 实例化机制分析

## 研究问题

这份笔记只回答一个问题：

> 在 “agent 实例化” 这件事上，`nanobot` 和 `openclaw` 分别是怎么落地的？

这里说的“实例化”，不是只看“怎么 new 一个对象”，而是看一个 agent 在系统里到底由哪些东西组成：

- 它怎么被选中或创建
- 它的工作目录怎么确定
- 它的人格和提示文件怎么装配
- 它的运行时状态放在哪
- 它的子 agent 是复用父实例，还是生成新的实例边界

---

## 一句话结论

如果用最直白的话说：

- `nanobot` 的解法更像：**“用配置文件选一个运行实例，再把 workspace 直接塞进 AgentLoop。”**
- `openclaw` 的解法更像：**“先把 agent 变成一个有身份的配置实体，再给它独立 workspace、agentDir、sessions、identity，然后再做调度。”**

所以两者不是简单的轻重差别，而是两种不同阶段的解法：

- `nanobot` 解决的是：**单实例怎么快速落地、怎么隔离 workspace**
- `openclaw` 解决的是：**多 agent 场景下，实例怎么长期稳定存在**

---

## 先给判断

如果你的目标是 `agent-alpha` 继续演进，并且以后要支持：

1. 输入工作路径
2. 自动识别人格文档
3. 多 agent 编排
4. 更强隔离和鲁棒性

那最适合借鉴的路线不是二选一，而是：

- **第一阶段学 `nanobot`**：先把“实例 = 配置 + workspace + bootstrap 文档 + session”这条线做干净
- **第二阶段学 `openclaw`**：再把“实例 = 具名 agent 实体 + 独立状态目录 + 子 agent 生命周期”补上

换句话说：

- `nanobot` 适合学“先把单实例做标准”
- `openclaw` 适合学“怎么把实例做成系统里的正式对象”

---

## 1. `nanobot` 是怎么做 agent 实例化的

## 1.1 它的实例入口，本质是“配置文件 + workspace”

`nanobot` 的实例不是一个显式的 `AgentSpec` 对象，而是由运行时配置决定的。

关键位置：

- `learning proj/nanobot/nanobot/config/schema.py:30-56`
- `learning proj/nanobot/nanobot/cli/commands.py:359-375`
- `learning proj/nanobot/nanobot/cli/commands.py:414-444`
- `learning proj/nanobot/README.md:1155-1254`

核心点：

1. `agents.defaults.workspace` 是实例最重要的空间边界
2. CLI 可以用 `--config` 切换实例
3. CLI 还可以用 `--workspace` 临时覆盖实例工作目录

也就是说，`nanobot` 的实例不是“先定义 agent，再运行”，而是：

> 先选配置，再把配置里的 workspace 灌进运行时。

这是一种很轻的做法，但也很直接。

---

## 1.2 它把“实例运行数据”和“workspace”做了半分离

关键位置：

- `learning proj/nanobot/nanobot/config/paths.py:11-40`
- `learning proj/nanobot/README.md:1172-1194`

`nanobot` 的路径模型是：

- runtime data 目录来自 `config.json` 所在目录
- workspace 来自 `agents.defaults.workspace` 或 `--workspace`

这意味着：

- `cron/`
- `media/`
- `logs/`

更偏“实例运行数据”

而：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`
- `memory/`
- `skills/`
- `sessions/`

更偏“workspace 内容”

注意这里有一个很重要的特点：

`SessionManager` 仍然把会话记录写到 `workspace/sessions` 下面，而不是配置目录下。  
见：

- `learning proj/nanobot/nanobot/session/manager.py:80-90`

所以它不是“完全状态分离”，而是：

> 一部分状态跟实例配置走，一部分状态仍然跟 workspace 走。

这很轻，但后期做复杂多 agent 时会有点拧。

---

## 1.3 它会自动把人格/约束文件同步到 workspace

关键位置：

- `learning proj/nanobot/nanobot/utils/helpers.py:173-203`
- `learning proj/nanobot/nanobot/templates/AGENTS.md`
- `learning proj/nanobot/nanobot/templates/SOUL.md`
- `learning proj/nanobot/nanobot/templates/USER.md`

`sync_workspace_templates()` 会自动往 workspace 里补这些文件：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`
- `memory/MEMORY.md`
- `memory/HISTORY.md`
- `skills/`

这件事非常关键。

因为它说明 `nanobot` 的实例化不是只有路径切换，而是：

> 只要实例选定了 workspace，它就会把这套 agent 生存所需的上下文骨架补进去。

这比“只是传一个 workdir”更完整。

---

## 1.4 它的人格装配是“workspace bootstrap 文件整体注入”

关键位置：

- `learning proj/nanobot/nanobot/agent/context.py:19-54`
- `learning proj/nanobot/nanobot/agent/context.py:109-145`

`ContextBuilder` 会从 workspace 根目录读取：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`

然后直接拼进 system prompt。

另外它还会：

- 读 `memory/MEMORY.md`
- 汇总 workspace skills 和 builtin skills

这说明 `nanobot` 对 agent 实例的理解是：

> 实例的人格和约束，不靠代码里硬编码，而靠 workspace 根目录里的几份 bootstrap 文档。

这和你现在想做的“输入工作路径、自动识别人格 md”非常接近。

---

## 1.5 它的子 agent 不是新实例，只是“共享 workspace 的后台执行体”

关键位置：

- `learning proj/nanobot/nanobot/agent/loop.py:82-94`
- `learning proj/nanobot/nanobot/agent/subagent.py:22-79`
- `learning proj/nanobot/nanobot/agent/subagent.py:91-218`

`SubagentManager` 的特点很鲜明：

1. 子 agent 直接继承父级 `workspace`
2. 子 agent 自己重新组一套 tool registry
3. 但它没有自己的独立 workspace
4. 也没有显式的“agent 身份配置实体”
5. 它更像后台任务执行器

而且它的 prompt 也只是强调：

- 你是 subagent
- 你的 workspace 是什么
- 你有哪些技能摘要

这就意味着：

`nanobot` 的 subagent 更接近：

> “从主 agent 分叉出去的一次性 worker”

而不是：

> “系统里正式存在的另一个 agent 实例”

这也是它轻量的原因。

---

## 1.6 对 `nanobot` 的收束判断

`nanobot` 在 agent 实例化上的核心解法，可以收成四句话：

1. 用 `config + workspace override` 选实例
2. 用 `sync_workspace_templates()` 保证实例 workspace 有完整 bootstrap 文档
3. 用 `ContextBuilder` 自动读取 workspace 根目录人格文件
4. 子 agent 复用同一个 workspace，不是独立实例

所以它的强项是：

- 轻
- 直观
- 很适合单实例和轻量多实例

它的弱项是：

- agent 身份不够正式
- 子 agent 边界不够强
- 实例状态分布还不算完全整齐

---

## 2. `openclaw` 是怎么做 agent 实例化的

## 2.1 它先把 agent 变成配置里的正式实体

关键位置：

- `learning proj/openclaw/src/config/types.agents.ts:61-95`
- `learning proj/openclaw/src/config/zod-schema.agents.ts:6-12`
- `learning proj/openclaw/src/config/zod-schema.agent-defaults.ts:17-197`

在 `openclaw` 里，agent 不是“顺手传个 workspace 就跑”，而是配置里的正式对象：

- `id`
- `name`
- `workspace`
- `agentDir`
- `model`
- `skills`
- `identity`
- `subagents`
- `sandbox`
- `tools`
- `runtime`

这一步特别重要。

因为这意味着：

> `openclaw` 不是先有 runtime 再想办法区分 agent，而是一开始就把 agent 当成一级配置实体。

这和 `nanobot` 的“默认实例 + 配置覆盖”差别非常大。

---

## 2.2 它有明确的 agent 选择规则

关键位置：

- `learning proj/openclaw/src/agents/agent-scope.ts:46-84`
- `learning proj/openclaw/src/agents/agent-scope.ts:86-145`
- `learning proj/openclaw/src/gateway/server-methods/agent.ts:316-376`

`openclaw` 会通过下面这些信息确定当前 agent：

- 显式 `agentId`
- `sessionKey`
- bindings / routes
- 默认 agent

也就是说，在 `openclaw` 里：

- session 不是悬空的
- session 会归属某个 agent
- 工具调用、身份、workspace、session 存储都会跟着 agent 走

这使得 agent 真正变成了“系统内的命名节点”。

---

## 2.3 它把 `workspace` 和 `agentDir` 分开了

关键位置：

- `learning proj/openclaw/src/agents/agent-scope.ts:256-342`
- `learning proj/openclaw/src/config/agent-dirs.ts:59-110`

这是 `openclaw` 很值得借的地方。

它至少区分了两类东西：

1. `workspace`
这是 agent 面向任务和用户上下文的工作区

2. `agentDir`
这是 agent 自己的状态目录

而且它还专门检查：

> 多个 agent 不能共享同一个 `agentDir`

原因写得很直白：

- 共享会导致 auth/session state 冲突
- 会造成 token 失效和状态碰撞

这其实就是在回答一个很实际的问题：

> 一个 agent 的“脑子”和“办公桌”不能混在一起。

对于你现在的项目，这个思想非常关键。

---

## 2.4 它会为每个 agent 准备更完整的 workspace bootstrap

关键位置：

- `learning proj/openclaw/src/agents/workspace.ts:12-33`
- `learning proj/openclaw/src/agents/workspace.ts:327-465`
- `learning proj/openclaw/src/agents/workspace.ts:487-547`

`openclaw` 的 bootstrap 文件比 `nanobot` 更完整：

- `AGENTS.md`
- `SOUL.md`
- `TOOLS.md`
- `IDENTITY.md`
- `USER.md`
- `HEARTBEAT.md`
- `BOOTSTRAP.md`
- `MEMORY.md`

而且 `ensureAgentWorkspace()` 不只是“缺文件就补”。

它还做了几件更工程化的事：

1. 记录 workspace setup state
2. 判断 bootstrap 是否已经完成
3. 维护 `BOOTSTRAP.md` 生命周期
4. brand new workspace 时尝试 `git init`

这说明 `openclaw` 对 agent workspace 的理解不是“随便一个目录”，而是：

> 一个有生命周期的 agent 工作空间。

---

## 2.5 它把 identity 单独抬成正式层

关键位置：

- `learning proj/openclaw/src/agents/identity-file.ts:5-107`
- `learning proj/openclaw/src/agents/identity.ts:6-170`
- `learning proj/openclaw/src/gateway/server-methods/agents.ts:532-546`

`openclaw` 比 `nanobot` 更进一步的一点是：

它不只依赖 `SOUL.md` 这种泛人格文本，还把 `IDENTITY.md` 做成结构化身份文件。

里面可以解析：

- `Name`
- `Emoji`
- `Theme`
- `Creature`
- `Vibe`
- `Avatar`

而且 agent 创建时，服务端会主动往 `IDENTITY.md` 里写入 `Name`，可选写 `Emoji`、`Avatar`。

这说明在 `openclaw` 里，agent 的“人格”不是一坨模糊 prompt，而是拆成了两层：

1. `SOUL.md` 负责气质和行为方式
2. `IDENTITY.md` 负责身份标识和外显形象

这套思路很适合你以后做多 agent 编排时的人格管理。

---

## 2.6 它的 system prompt 明确认这些 workspace 文件

关键位置：

- `learning proj/openclaw/src/agents/system-prompt.ts:498-626`
- `learning proj/openclaw/src/agents/pi-embedded-runner/system-prompt.ts:11-85`

`openclaw` 在 system prompt 里明确写了：

- 当前 working directory 是哪个 workspace
- 哪些 workspace files 会被注入
- 如果有 `SOUL.md`，就要体现它的人格

也就是说，workspace 文件不是“顺手读一下”，而是 runtime 里正式承认的一部分。

这比单纯“检测几个 md 文件然后拼 prompt”更成熟，因为它把规则写进了系统级提示结构。

---

## 2.7 它的 session 存储是按 agent 隔离的

关键位置：

- `learning proj/openclaw/src/config/sessions/paths.ts:8-35`
- `learning proj/openclaw/src/config/sessions/paths.ts:281-296`

`openclaw` 默认把会话存到：

- `.../agents/<agentId>/sessions/`
- store 文件是 `sessions.json`

而且 session store 路径还支持用 `{agentId}` 模板展开。

这意味着：

> session 从设计上就是 agent-scoped，而不是全局混放。

相比之下，`nanobot` 更像“一个 workspace 对应一套 sessions”。  
`openclaw` 更像“一个 agent 对应一套 sessions”。

这就是为什么它更适合做正式多 agent。

---

## 2.8 它的子 agent 真的是“新会话实例”

关键位置：

- `learning proj/openclaw/src/agents/tools/sessions-spawn-tool.ts:23-212`
- `learning proj/openclaw/src/agents/spawned-context.ts:59-83`
- `learning proj/openclaw/src/config/sessions/types.ts:76-102`
- `learning proj/openclaw/src/gateway/server-methods/agent.ts:693-706`

`openclaw` 的子 agent 和 `nanobot` 最大的区别在这里：

它不是简单起个后台任务，而是会生成一条新的 session run。

并且这条子会话会带上这些元数据：

- `spawnedBy`
- `spawnedWorkspaceDir`
- `spawnDepth`
- `subagentRole`
- `subagentControlScope`
- `status`
- `startedAt / endedAt / runtimeMs`

再加上 `sessions_spawn` 工具里允许指定：

- `runtime`
- `agentId`
- `model`
- `thinking`
- `cwd`
- `sandbox`
- `mode`

你就能看出来，`openclaw` 的子 agent 更接近：

> 一个被系统编排出来的正式子实例

而不是一次普通委派。

---

## 2.9 对 `openclaw` 的收束判断

`openclaw` 在 agent 实例化上的核心解法，可以收成六句话：

1. 先把 agent 做成配置里的一级实体
2. 每个 agent 有自己的 `agentId`
3. 每个 agent 有自己的 `workspace`
4. 每个 agent 还有自己的 `agentDir`
5. 每个 agent 的 session 默认也是独立存储
6. 子 agent 是新的 session 实例，不只是后台任务

所以它的强项是：

- 边界清楚
- 可多 agent 编排
- 生命周期完整
- 长期运行时更稳

它的代价是：

- 设计更重
- 配置和控制面更复杂
- 不适合一开始就全量照搬

---

## 3. 两者的核心差异

| 维度 | `nanobot` | `openclaw` | 判断 |
|---|---|---|---|
| 实例入口 | `config + --workspace` | `agentId + config registry + session routing` | `openclaw` 更正式 |
| 实例定义方式 | 默认实例为主，运行时覆盖 | agent 是配置一级对象 | `openclaw` 更强 |
| workspace | 很重要，是主要边界 | 很重要，但不是唯一边界 | `openclaw` 更完整 |
| 人格文件 | `AGENTS/SOUL/USER/TOOLS` | `AGENTS/SOUL/TOOLS/IDENTITY/USER/HEARTBEAT/BOOTSTRAP` | `openclaw` 更体系化 |
| identity | 没有单独抬出来 | `IDENTITY.md` + config.identity | `openclaw` 更适合多 agent |
| session 隔离 | 主要按 workspace | 主要按 agentId | `openclaw` 更适合编排 |
| 子 agent | 共享 workspace 的后台执行体 | 独立子 session / 子实例 | `openclaw` 明显更强 |
| 实现复杂度 | 低 | 高 | `nanobot` 更适合先借 |

---

## 4. 对 `agent-alpha` 最值得借的具体解法

## 4.1 第一优先级，借 `nanobot`

最值得先学的是这三件事：

1. **实例入口标准化**
让实例至少由：
`config/profile + workspace`
来明确确定

2. **workspace bootstrap 自动补齐**
像 `nanobot` 一样，在实例创建时自动补：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- 你自己需要的其他文档

3. **启动时自动装配 workspace 人格文件**
这点你现在已经做了一部分，但还不够“实例化”。

为什么先借它？

因为这三件事改动不大，但立刻能把你的 agent 从“能跑”推进到“实例边界清楚”。

---

## 4.2 第二优先级，借 `openclaw`

等第一阶段稳了，下一步最值得借的是：

1. **引入正式的 `agentId`**
让 agent 不再只是“某次运行”，而是有稳定身份

2. **拆开 `workspace` 和 `agentDir`**
前者放任务文件，后者放 agent 自己状态

3. **按 agent 隔离 sessions**
不要再把所有状态都跟某个共享工作目录绑死

4. **给子 agent 落正式元数据**
至少要有：

- `parent_agent_id`
- `parent_session_id`
- `spawned_workspace`
- `spawn_depth`
- `status`

这些做了以后，你的多 agent 编排才会真正稳下来。

---

## 5. 我的建议：你现在该怎么借

如果只围绕“agent 实例化”这个主题，我建议你的落地顺序是：

### 第 1 步：做 `nanobot` 风格实例壳

先让一个实例最少有：

- `agent_id`
- `workspace`
- `persona docs`
- `tool policy`
- `session scope`

这一步先别急着做复杂控制面。

### 第 2 步：补 `openclaw` 风格的 identity 与 state dir

把：

- `workspace`
- `agent state dir`
- `identity`
- `session store`

四者拆开。

### 第 3 步：再做 `openclaw` 风格子实例编排

也就是让子 agent 不再只是“共享父 workspace 的任务线程”，而是：

- 有自己的 session
- 有自己的运行状态
- 有清晰的父子关系

---

## 最终收束

关于“agent 实例化”这个主题，`nanobot` 和 `openclaw` 的具体解法可以收成一句话：

- `nanobot`：**先把 workspace 驱动的实例跑顺**
- `openclaw`：**再把 agent 变成系统里的正式实体**

如果把这套结论翻译成你现在的下一步：

> `agent-alpha` 现在最该做的，不是马上学 `openclaw` 搭一个很大的控制面，而是先把 `nanobot` 式的实例壳做扎实，然后分阶段引入 `openclaw` 式的 `agentId / agentDir / per-agent sessions / spawned session metadata`。 

