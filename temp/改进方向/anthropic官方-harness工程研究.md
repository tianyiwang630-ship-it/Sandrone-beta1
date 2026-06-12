# Anthropic 官方材料里的 Harness Engineering 研究

## 研究范围

这份笔记只看 `Anthropic` 官方来源，重点是：

- 官方文档里的 `Claude Code`
- 官方产品页 / 官方博客里对 `Claude Code` 的描述

这次不研究第三方解读，不研究社区二手总结。

我要回答的问题是：

> 如果把 `Claude Code` 看成一套 harness engineering 实践，Anthropic 官方到底强调了哪些工程层？  
> 这些东西映射到 `agent-alpha`，哪些必须学，哪些暂时不要学？

---

## 一句话结论

如果用最直白的话说，Anthropic 官方对 harness 的理解不是：

- “先做一个很复杂的多 agent 平台”

而更像是：

- “先做一个在本地终端运行、边界清楚、权限可控、上下文可管理、可被自动化扩展的 agent 系统”

然后才在这个系统上继续加：

- subagents
- hooks
- permissions
- memory
- output styles
- MCP
- automation
- telemetry

所以对 `agent-alpha` 的最大启发不是“赶紧做群体智能”，而是：

> 先把单 agent harness 的基础分层做扎实。

---

## Anthropic 官方资料清单

### 核心文档

1. Claude Code overview  
   https://docs.anthropic.com/en/docs/claude-code/overview

2. Claude Code settings  
   https://docs.anthropic.com/en/docs/claude-code/settings

3. Identity and Access Management  
   https://docs.anthropic.com/en/docs/claude-code/team

4. Security  
   https://docs.anthropic.com/en/docs/claude-code/security

5. Manage Claude's memory  
   https://docs.anthropic.com/en/docs/claude-code/memory

6. Slash commands  
   https://docs.anthropic.com/en/docs/claude-code/slash-commands

7. Subagents  
   https://docs.anthropic.com/en/docs/claude-code/sub-agents

8. Hooks guide  
   https://docs.anthropic.com/en/docs/claude-code/hooks-guide

9. Hooks reference  
   https://docs.anthropic.com/en/docs/claude-code/hooks

10. CLI reference  
    https://docs.anthropic.com/en/docs/claude-code/cli-reference

11. Common workflows  
    https://docs.anthropic.com/en/docs/claude-code/tutorials

12. Development containers  
    https://docs.anthropic.com/en/docs/claude-code/devcontainer

13. Monitoring  
    https://docs.anthropic.com/en/docs/claude-code/monitoring-usage

14. Output styles  
    https://docs.anthropic.com/en/docs/claude-code/output-styles

### 官方产品 / 博客页

1. Claude Code product page  
   https://www.anthropic.com/product/claude-code

2. Claude Code landing page  
   https://www.anthropic.com/claude-code/

3. Introducing Code with Claude  
   https://www.anthropic.com/news/Introducing-code-with-claude  
   发布日期：2025-04-03

说明：

- Anthropic 官方并没有一篇标题直接叫 “harness engineering” 的博客。
- 这里的 “harness engineering” 是我根据官方文档体系做的工程归纳。

---

## Anthropic 官方实际上强调了什么

## 补充重点：`Managed agents` 这篇文章到底说了什么

重点文章：

- `Scaling Managed Agents: Decoupling the brain from the hands`
- https://www.anthropic.com/engineering/managed-agents

这是本轮最关键的一篇。

因为它不是在讲使用技巧，而是在讲：

> Anthropic 自己是怎么重构 agent 基础设施的。

### 这篇文章的一句话结论

Anthropic 的核心主张是：

> 不要把 harness、session、sandbox 绑死在一起。  
> 要把它们抽成稳定接口，让底层实现可以不断换，而上层系统不用跟着重写。

也就是文章标题里的：

- 把 `brain` 和 `hands` 解耦

更完整一点说，是把 3 个东西分开：

- `session`
- `harness`
- `sandbox`

### Anthropic 为什么要这样做

文章开头有个特别关键的判断：

- harness 里编码了很多“模型现在还做不到什么”的假设
- 但这些假设会随着模型进步而过时

他们举的例子是：

- 某一代模型会因为上下文快满而“提前收尾”
- 于是 harness 加了 context reset
- 但下一代模型这个问题没了
- 原来的 reset 反而成了负担

这句话对你特别重要。

它说明：

> 如果你把太多策略硬编码进 harness，本质上是在赌“模型未来不会变”。

Anthropic 的应对方式不是“别做 harness”，而是：

> 做接口稳定、实现可替换的 harness。

### Anthropic 最关键的结构抽象

文章里把 agent 系统拆成了 3 个稳定接口：

#### 1. `session`

它不是 Claude 的上下文窗口。  
它是：

- append-only event log
- 持久化记录
- 可恢复上下文对象

文章明确强调：

- 长任务一定会超过 context window
- 所以 context 不能只活在模型窗口里
- `session` 应该作为窗口外的、可查询的、可恢复的上下文对象存在

#### 2. `harness`

它是：

- 调 Claude
- 路由 Claude 的工具调用
- 管理上下文装配

但关键是：

- harness 不该和 sandbox 共生死
- harness 崩了可以重启
- 只要 session 还在，就能 `wake(sessionId)` 然后从事件继续

#### 3. `sandbox`

它是：

- 执行代码
- 编辑文件
- 跑命令

但它只是 “hands”，不是系统中心。

Anthropic 的意思非常明确：

- sandbox 可以死
- 死了就当一次 tool error
- 需要的话再重新 provision

### 这篇文章对 `agent-alpha` 的最大启发

如果只抓最关键的 4 条，我会这么总结：

#### 启发 1：`session` 必须升级成真正的系统核心

你现在的 `session_store` 更像“恢复快照”。  
Anthropic 这篇文章给出的方向更强：

- session 不是恢复辅助件
- session 是系统事实来源

也就是说，未来更好的形态应该是：

- 所有运行事件都写进 session/event log
- harness 崩了也能从 session 恢复
- subagent / cron / main agent 都围绕 session 工作

这意味着你的 `session` 后面不该只是：

- history
- workspaces

而要逐步变成：

- event stream
- run state
- lineage
- tool events
- context checkpoints

#### 启发 2：`harness` 不要和执行环境绑死

Anthropic 一开始把 harness 和 sandbox 放在一个容器里，后来发现这会把整个系统做成“宠物机”。

对 `agent-alpha` 来说，对应的警告就是：

> 不要让 runtime 默认假设“工作目录、权限、工具实例、状态目录、人格装配”都必须跟着一个具体进程对象绑死。

更好的方向是：

- runtime 可以被重建
- 配置和状态在外部
- 工作目录和执行资源是可替换的

#### 启发 3：安全边界应该靠结构，不靠模型自觉

文章里一段特别关键：

- 不可信代码不能和凭证待在同一个地方

Anthropic 的解决方式不是“缩 prompt”，而是：

- 让 sandbox 永远碰不到真正凭证
- token 放在资源初始化过程或 vault / proxy 里

这对应到 `agent-alpha`，意思非常明确：

> 将来如果你做 capability install、MCP、外部工具，安全边界不能只靠“不要泄漏密钥”的提示词。

应该优先考虑：

- 凭证外置
- proxy 调用
- session-bound token
- sandbox 无法直接触碰核心凭证

#### 启发 4：多 agent 的本质不是“多人格”，而是“many brains, many hands”

Anthropic 在文中最后明确写了：

- many brains
- many hands

这特别像你未来想做的复杂编排，但它的落点不是“社会学协作”，而是：

- 多个 brain 可以并发
- 多个 hand 可以被分配
- hand 不属于某个固定 brain
- brain 和 hand 都能替换

这对 `agent-alpha` 的真正启发是：

> 未来的多 agent 编排，不该以“几个人格实例互相聊天”为中心。  
> 更好的架构中心应该是：  
> `session / task / tool-execution-environment / routing`

### 这篇文章直接改变了我对 `agent-alpha` 顺序的判断

在读完这篇之前，我的排序是：

- 实例化
- 上下文分层
- 权限边界
- hooks
- subagent
- 状态台账

现在我会进一步强调：

> `session/event architecture` 的优先级应该更高。

也就是更合理的顺序变成：

1. `agent 实例化`
2. `session / event log 架构`
3. `上下文分层`
4. `权限与工作区边界`
5. `hooks`
6. `simple subagent`
7. `能力安装基础设施`
8. `cron`
9. `复杂编排`

原因很简单：

- 没有 durable session
- 没有可恢复 event stream
- 你后面做的 cron / subagent / swarm 都会变脆

### 对你现在最重要的判断

如果只把这篇文章压成一句建议给 `agent-alpha`：

> 你现在不只是要做 “agent instance”，而是要尽快决定  
> **`agent runtime` 到底围绕什么持久对象组织。**

Anthropic 给出的答案是：

- 不是围绕进程
- 不是围绕容器
- 不是围绕上下文窗口
- **而是围绕 session**

我认为这对你非常重要。

## 1. 先是“agentic coding system”，不是“聊天壳”

从 `overview`、`product page`、`landing page` 看，Anthropic 对 `Claude Code` 的定义很稳定：

- 读代码库
- 跨文件改代码
- 跑命令
- 跑测试
- 迭代修复
- 在终端里工作

这件事非常重要。

因为它说明官方心里的核心不是：

- prompt 工程
- 角色扮演
- 聊天 UI

而是：

- **一个可以在真实开发环境里执行工作的 agent loop**

对 `agent-alpha` 的启发：

- 你后面不管做多少层包装，核心都应该是“能稳定完成真实任务的 runtime”
- 不要把重心放到“人格层”而忽略执行层

---

## 2. Anthropic 把“指令、配置、权限、风格”拆成了不同层

这是最值得你学的地方之一。

从官方文档看，至少有这几层：

### 2.1 `CLAUDE.md` = 记忆 / 项目约束 / 长期上下文

见：

- `memory`

官方把 `CLAUDE.md` 当成：

- 项目约束
- 团队规范
- 常用命令
- 架构背景
- 个人偏好

而不是把这些都硬塞进代码里。

### 2.2 `settings.json` = 行为配置

见：

- `settings`

这里放的是：

- permissions
- hooks
- env
- model
- additionalDirectories

### 2.3 slash commands = 工作流命令

见：

- `slash-commands`

也就是“高频流程模板化”。

### 2.4 output styles = 主 agent 的系统提示变体

见：

- `output-styles`

官方甚至专门区分了：

- output style
- CLAUDE.md
- agents
- slash commands

这点很关键，说明他们非常在意“不要把不同职责的东西混到一层”。

对 `agent-alpha` 的启发：

> 你以后一定要把“人格文档、运行配置、工作流模板、子 agent 定义”拆开。  
> 不能再让 `AGENTS.md` 一层兼任太多职责。

---

## 3. 权限体系不是附属品，而是 harness 主体

从 `settings`、`team`、`security` 看，Anthropic 官方把 permission system 放得很重。

核心思想很明确：

- 默认谨慎
- 读写分层
- 命令要审批
- 可以项目级 allow/ask/deny
- 可以扩展额外工作目录
- 可以有不同 permission mode

官方强调的模式包括：

- `default`
- `acceptEdits`
- `plan`
- `bypassPermissions`

同时又强调：

- 默认是保守的
- `bypassPermissions` 只适合安全环境

还有几个细节很值得注意：

- 写权限默认只在启动目录及其子目录
- 额外目录要显式配置
- 网络请求默认要审批
- hook 可以在工具调用前后再做一次硬控制

这说明 Anthropic 的思路不是：

- 让模型自由发挥，再靠提示词约束

而是：

- **先把执行边界做成系统能力**

对 `agent-alpha` 的启发：

> 权限系统不能只是工具层里的一个小判断；它应该是 runtime 架构的一部分。

---

## 4. subagent 是“专长 worker”，不是“群体智能社会”

从 `subagents` 文档看，Anthropic 官方对子 agent 的定位非常清楚：

- 专门用途
- 独立上下文窗口
- 可单独配置工具
- 靠描述触发自动委派
- 也可以显式点名调用

它更像：

- 专长工种
- 可复用 worker

而不是你说的那种未来“群体智能编排”。

也就是说，官方现在强调的 subagent 本质是：

- **主 agent 的任务分流机制**

不是：

- 自主协商的 agent society

这对你很重要。

因为它说明在 Anthropic 官方路线里：

1. 先把主 agent 做强
2. 再把常见子工种做成 subagent
3. 先解决 context preservation 和 delegation
4. 并没有把 swarm 当第一优先级

对 `agent-alpha` 的启发：

> 你现在做的 simple subagent，方向应当先对齐“专长 worker + 独立上下文 + 限制工具”，而不是直接朝群体智能靠。

---

## 5. hooks 是 Anthropic 官方给出的“确定性工程层”

这是特别值得你注意的一点。

从 `hooks-guide` 和 `hooks` 看，Anthropic 明确承认：

- 有些事情不能靠模型“想起来要做”
- 需要 deterministic control

所以他们给了 hooks：

- `PreToolUse`
- `PostToolUse`
- `UserPromptSubmit`
- `Stop`
- `SubagentStop`
- `SessionStart`
- `SessionEnd`
- `PreCompact`

这其实就是在说：

> harness 里必须有一层“非模型自治”的工程控制面。

这层可以做：

- 自动格式化
- 敏感路径拦截
- prompt 校验
- session 启动时自动补上下文
- 结束时收尾
- subagent 结束后控制后续行为

对 `agent-alpha` 的启发非常直接：

> 你后面别只做 `cron`。  
> 还应该有一层事件驱动的 hook / interceptor 机制。  
> 因为很多基础设施问题，本质上不是定时任务，而是生命周期事件。

---

## 6. 自动化存在，但官方强调“安全环境下的 unattended”

从 `CLI reference`、`security`、`devcontainer`、`common workflows` 看，Anthropic 官方支持自动化，而且支持得不轻：

- `claude -p`
- 非交互脚本调用
- JSON 输出
- CI 场景
- 工作流串联
- devcontainer 下 unattended operation

但官方强调得也很清楚：

- 默认不是无脑放开
- 真正 unattended 的场景，要在更安全的容器环境里做
- `dangerously-skip-permissions` 有明确警告

所以 Anthropic 的自动化哲学是：

- **可以自动化**
- **但自动化要建立在受限环境和清晰边界上**

对 `agent-alpha` 的启发：

> 你以后要做 cron、自动安装、后台任务，但前提是：  
> 先把 workspace / state dir / permission / sandbox 这几件事立住。

---

## 7. 记忆系统的重点是“层级化加载”，不是“人格神秘化”

从 `memory` 文档看，Anthropic 官方对 memory 的处理很工程化：

- enterprise memory
- project memory
- user memory
- local memory

而且支持：

- 递归查找
- import
- 分层覆盖

这说明他们对记忆文件的理解是：

- 这是上下文基础设施
- 不是“世界观设定文本”

对 `agent-alpha` 的启发：

> 你现在说的“自动识别人格 md 文档”，未来最好别只停在人格。  
> 更好的方向是：做成“分层上下文装配系统”。

可以包含：

- agent identity
- project instructions
- user preferences
- workflow hints
- local overrides

---

## 8. Anthropic 官方非常强调“可运维性”

从 `monitoring`、`settings`、`team` 文档能看出来，Claude Code 不是被当成一个个人玩具。

官方已经给了：

- managed settings
- enterprise policy
- telemetry
- OpenTelemetry
- session/cost/tool events

这说明在 Anthropic 视角里，agent harness 不只是“能运行”，还要：

- 可观察
- 可审计
- 可治理

对 `agent-alpha` 的启发：

> 你后面想做多 agent 编排，必须先有 run/session/event 的统一记录层。  
> 不然复杂度一上来，你根本不知道系统在干什么。

---

## Anthropic 官方路线，映射到 `agent-alpha` 后的关键判断

下面这部分最重要。

## 判断 1：`agent-alpha` 的定位，先不要变成“大平台”

Anthropic 官方路线的核心不是“先做平台”，而是“先把一个 agentic coding system 做强”。

所以 `agent-alpha` 现在更合适的定位应该是：

- **标准化单 agent harness**

而不是：

- 大一统多 agent 平台

如果你现在把重心过早放到群体智能，会跳过最关键的单体基础层。

---

## 判断 2：必须把“上下文层”拆开

我建议你至少拆成 4 层：

1. `memory / project instructions`
2. `runtime settings`
3. `workflow commands`
4. `subagent definitions`

映射到你的项目，可以理解成：

1. `AGENTS.md / SOUL.md / 未来更多上下文文档`
2. `role_config / tool policy / permissions / paths`
3. `slash-like command templates`
4. `subagent spec files`

如果不拆，后面每加一个能力都要去改 `AGENTS.md` 语义，系统会越来越乱。

---

## 判断 3：必须决定权限哲学

这是 `agent-alpha` 眼下最该做的关键判断之一。

你要先选清楚：

- 是不是默认保守
- 写文件和跑命令是否分开审批
- 包安装是否单独一类
- 网络访问是否单独一类
- subagent 是否继承父权限
- cron 是否能绕过人工确认

Anthropic 官方给出的答案很明确：

- 默认保守
- 权限分层
- 自动化需要更安全环境

我建议 `agent-alpha` 也走这条线。

---

## 判断 4：必须决定“工作区”到底是什么

Anthropic 官方对 working directory 的处理非常清楚：

- 默认只在当前工作目录内写
- 可显式加额外目录
- 记忆文件是递归加载的

所以你也要尽快定下来：

- `workspace` 是执行边界，还是只是一个默认目录？
- 多 workspace 是平级，还是主从？
- 人格文档是只从主 workspace 读，还是支持分层？
- session/log/state 是不是继续跟 workspace 混放？

这件事不定，后面 subagent、cron、能力安装都会拧。

---

## 判断 5：simple subagent 应该先做成“专长 agent”

这点 Anthropic 官方给了很强的方向性。

我建议你现在的 simple subagent 先满足这 4 条：

- 有独立上下文
- 有自己的说明文件
- 有自己的工具边界
- 可以被主 agent 自动或显式调用

先不要追求：

- 子 agent 自治协商
- 子 agent 之间互发任务
- 群体级策略演化

那是后一阶段的事情。

---

## 判断 6：cron 之前，要先有 lifecycle hooks

这是我从 Anthropic 文档里得到的一个很强的结论。

因为很多真正需要的自动化不是“定时发生”，而是“在某个事件点发生”：

- 工具调用前拦截
- 工具调用后校验
- session 开始时补充上下文
- session 结束时落盘
- subagent 结束时回传
- compact 前做摘要准备

所以对 `agent-alpha` 更合理的顺序是：

1. 先做 lifecycle hooks
2. 再做 cron

cron 很重要，但它不是第一种自动化。

---

## 判断 7：能力安装必须做成“受控宿主能力”

Anthropic 官方文档虽然没有直接讲 `Agent-Reach` 或 `CLI-Anything`，但它对整个 harness 的态度已经很清楚：

- 工具边界清晰
- 权限清晰
- 配置清晰
- 自动化可控

所以你如果真想支持：

- 给一个仓库链接就自动安装能力

那就必须先做：

- 托管能力目录
- 安装计划
- 依赖检查
- 安装状态
- 卸载 / 更新
- 审批策略

这个不是 skill loader 小修小补能解决的。

---

## 判断 8：正式做群体智能前，必须先有“可观察运行台账”

Anthropic 官方的 `monitoring`、`permissions`、`session` 思维都在说明一件事：

> 系统复杂了以后，最先不够用的不是模型，而是观测能力。

所以在你做群体智能之前，`agent-alpha` 至少应该先有：

- session record
- task record
- run record
- event log
- tool decision log
- subagent lineage

没有这层，你后面排查问题会非常痛苦。

---

## 我对 `agent-alpha` 的最终建议

如果完全按 Anthropic 官方材料来倒推，我会建议你这样排顺序：

1. `agent 实例化`
2. `上下文分层系统`
3. `权限与工作区边界`
4. `lifecycle hooks`
5. `simple subagent（专长 worker）`
6. `状态台账 / 可观察性`
7. `能力安装基础设施`
8. `cron`
9. `更复杂的编排`
10. `群体智能`

注意这里有两个和你原来直觉不太一样的地方：

- `hooks` 应该比 `cron` 更早
- `状态台账` 应该比复杂编排更早

这两点我认为非常关键。

---

## 最后的判断

如果把 Anthropic 官方路线压成一句话：

> 真正成熟的 harness，不是“很多 agent”，而是“一个 agent 的执行边界、上下文边界、权限边界、生命周期边界都很清楚”。

所以对现在的 `agent-alpha` 来说，最值得学的不是表面的 `Claude Code` 交互，而是它背后的分层：

- memory
- settings
- permissions
- subagents
- hooks
- automation
- observability

你后面做群体智能当然可以，但在那之前，这几层地基要先补齐。

---

## 给下一轮讨论的 4 个焦点

如果你要继续和我收束 `agent-alpha`，我建议下一轮重点讨论这 4 个问题：

1. `AGENTS.md / SOUL.md` 未来要不要升级成更明确的上下文分层体系？
2. `subagent` 先做“专长 worker”还是先做“会话级子实例”？
3. `hooks` 要不要提前到 `cron` 前面？
4. `能力安装` 是放进 skill 体系扩展，还是单独做 capability/package 体系？

这 4 个问题一旦定下来，后面的路线会清楚很多。
