# 从 Harness Engineering 角度，对比 OpenClaw、nanobot 与 agent-alpha

## 结论摘要

如果只从 harness engineering 的角度看，也就是不比较“模型聪不聪明”，只比较“这个 agent 外壳工程能不能稳定运行、能不能扩展、能不能维护”，整体判断是：

1. OpenClaw 最强，但它强在“平台级外壳”，不适合当前阶段整体照搬。
2. nanobot 最适合拿来借鉴，因为它是“轻量但闭环的 agent harness”。
3. agent-alpha 已经有不错的 coding-agent 内核，但目前更像“可运行 runtime”，还没有完全长成“可长期演进的工程外壳”。

一句话收束：

- OpenClaw 适合学“做大以后怎么不失控”。
- nanobot 适合学“做小以后怎么不散”。
- agent-alpha 现在最需要的是从“能跑”走到“能稳、能隔离、能编排”。

## 这份对比在比什么

这里的 harness engineering，主要看的是下面三类问题：

1. 运行编排  
看入口是否清楚，主循环是否稳定，工具与子 agent 的调度是不是围绕明确的运行时来组织。

2. 工程支撑  
看配置、路径、日志、权限、会话、恢复、健康检查、部署入口这些外围工程是否成体系。

3. 可演进性  
看未来做多 agent、按工作目录运行、自动识别人设文档、扩展更多能力时，是否容易落地而不失控。

更直白一点，这份对比看的不是“它现在能做多少事”，而是“它后面继续做事时，会不会越来越乱”。

## 三个项目各自像什么

### OpenClaw

OpenClaw 更像一个完整平台，而不是一个单纯的 agent 项目。

它已经有：

- CLI 命令树
- onboarding
- gateway
- daemon 生命周期
- agents 管理
- 插件与 channel 体系
- 运维和诊断入口

所以它的强项不在“代码少”，而在“控制面完整”。

从 harness engineering 角度看，OpenClaw 更像“平台级外壳”。

### nanobot

nanobot 更像从 OpenClaw 中提炼出来的一套轻量骨架。

它保留了很多真正有价值的外壳要件：

- CLI
- session
- config
- paths
- channels
- cron
- subagent
- workspace 文档装配

但整体仍然保持较轻量。

从 harness engineering 角度看，nanobot 更像“轻量但闭环的 agent harness”。

### agent-alpha

agent-alpha 更像一个已经具备 coding-agent 实战能力的运行时核心。

它已经有：

- tool loader
- MCP 自动发现
- skills
- permission
- session snapshot
- workspace 雏形

这说明它的核心并不弱。

但它目前的问题是：外围外壳还没有完全整理清楚。  
所以它更像“可运行 runtime”，还不是“成熟的工程外壳”。

## 核心对比矩阵

| 维度 | OpenClaw | nanobot | agent-alpha | 判断 |
|---|---|---|---|---|
| 入口与命令面 | 命令树完整，分层清楚 | CLI 轻量但成体系 | 目前更偏单 CLI 运行 | OpenClaw 最成熟，agent-alpha 还需拆层 |
| 配置与路径模型 | 偏平台配置与实例化管理 | 围绕实例目录和 workspace 组织 | 仍有不少项目根目录绑定 | nanobot 最适合当前阶段借鉴 |
| 工作区与人格文档 | 支持隔离，但体系较重 | AGENTS.md、SOUL.md、USER.md、TOOLS.md 装配自然 | 已支持部分工作区文档读取，但还不够实例化 | nanobot 对你的目标更直接 |
| 会话与状态管理 | 平台级治理能力强 | 轻量但闭环 | 有 snapshot，但状态体系还偏薄 | nanobot 是最容易借到手的范本 |
| 生命周期与运维 | 很强，包含 restart/drain 等 | 中等，够用但不平台化 | 偏弱，更多是可运行而不是可治理 | 这里要向 OpenClaw 选学，不要全学 |
| 工具与扩展模型 | 插件契约强，边界清楚 | 动态注册够轻 | loader 基础不错，但还偏项目级组织 | agent-alpha 已有基础，关键是继续解耦 |
| 测试护栏 | 覆盖很广 | 围绕 loop、config、channel、cron 做了实用护栏 | 已有核心模块测试，但还缺 harness 级闭环测试 | agent-alpha 应该学 nanobot 的测试组织方式 |

## 逐项分析

### 1. 入口与主控层

OpenClaw 在这方面最成熟。

它不是把几个脚本拼起来，而是有明显的命令层分工，例如：

- setup
- onboard
- gateway
- agent
- agents
- doctor
- backup

这说明它把“怎么进入系统”“怎么运维系统”“怎么切换模式”都设计成正式外壳的一部分。

nanobot 的 CLI 也已经成体系，但没有 OpenClaw 那么平台化。  
agent-alpha 目前则更偏“直接跑 agent”，CLI 中混入了不少会话恢复和工作区管理逻辑。

这在早期项目里很常见，但一旦后面要接更多运行模式，最先吃力的通常不是模型，而是入口层。

### 2. 配置与路径组织

这一项是 nanobot 最值得借的地方之一。

nanobot 的很多运行时目录是从当前配置上下文推导出来的，例如：

- data
- logs
- cron
- workspace

这种做法的好处是：

- 更容易支持多实例
- 更容易支持独立工作区
- 不需要把很多路径硬绑在项目根目录

这和你的目标是高度一致的，因为你明确希望：

- 每个 agent 类可以输入工作路径
- 自动识别人格文档
- 便于后续多 agent 编排

而 agent-alpha 目前虽然已经引入 workspaces，但仍有明显的“项目根目录中心化”痕迹。  
这在单实例阶段问题不大，但到了多 agent 编排阶段，就会暴露边界不清的问题。

### 3. 工作区与人格装配

nanobot 的工作区装配方式，对你很有参考价值。

它会把工作区中的这些文件视为系统提示的重要组成部分：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`

这意味着“人格、规则、习惯、工具说明”是围绕工作区存在的，而不是只围绕整个项目存在的。

这和你提出的目标非常一致：  
希望每个 agent 类都能输入工作路径，并自动识别 agent 人格 md 文档。

agent-alpha 目前已经开始支持读取工作区里的 `AGENTS.md` 和 `SOUL.md`，这说明方向是对的。  
但它现在还只是“把文件读进来”，还没有进一步形成一个明确的 agent 实例边界，例如：

- identity
- skills
- memory
- tool scope
- private config
- session
- logs

也就是说，它已经起步，但还没真正完成“实例化”。

### 4. 会话、记忆与状态

OpenClaw 强在治理能力，nanobot 强在轻量闭环。

OpenClaw 的 session 与 routing，更偏平台级状态管理。  
nanobot 则用较小的实现，把下面这些事情串成了闭环：

- 会话保存
- 历史裁剪
- memory / consolidation
- 长时运行下的状态维护

这种“够用且好改”的状态模型，其实比“非常完整但非常重”的模型更适合你当前阶段。

agent-alpha 现在已经有 session snapshot 和 CLI 恢复，这当然是好事。  
但整体上更像“为了恢复当前对话而保存”，而不是围绕长时间运行、隔离和演进建立完整状态体系。

换句话说，它现在更像恢复功能，不完全像状态架构。

## 为什么 nanobot 最值得借

不是因为 nanobot 最强，而是因为 nanobot 最贴近你当前阶段要解决的问题。

你现在的目标是：

1. 减少冗余代码
2. 优化代码架构
3. 提高配置灵活性和模块化
4. 提升鲁棒性
5. 每一个 agent 类，可以输入工作路径、自动识别 agent 人格 md 文档，便于多 agent 编排

和这个目标最匹配的，不是 OpenClaw 的平台控制面，而是 nanobot 的轻量闭环骨架。

nanobot 最值得借的点主要有：

- 工作区中心化
- 人格文件装配
- 轻量 session / memory 闭环
- 简洁配置路径模型
- 实用导向的测试护栏

## 为什么 OpenClaw 不能整体照搬

OpenClaw 当然很强，但它的强是平台级的强。

如果你现在直接向 OpenClaw 靠齐，最容易出现两个问题：

### 1. 过早平台化

你会很快进入下面这些建设任务：

- 大 gateway
- 重控制面
- 完整 daemon 生命周期
- 更复杂的插件体系
- 更重的命令层

这些东西本身没有错，但在当前阶段会把项目带回复杂化。

### 2. 简化路线被中断

你现在走的是“从 skill-mcp-agent 出发逐步简化”的路线。  
如果过早引入平台级外壳，很容易从“清边界、减冗余”变成“再搭一层更大的框架”。

所以对 OpenClaw 的正确使用方式，不是整体模仿，而是选择性借鉴：

- 借生命周期治理思想
- 借命令层分层思想
- 借 restart / drain 思想
- 借插件契约意识

但不要直接抄它的大控制面。

## agent-alpha 现在最像什么，最缺什么

### 已有优势

agent-alpha 的内核并不弱。

它已经有：

- 面向 coding agent 的核心骨架
- MCP 自动发现
- skills
- permission
- session snapshot
- 多工作区雏形
- 从工作区读取部分人格文档的能力

另外，它已经有一定的测试基础，这意味着后续可以比较稳地重构。

### 主要短板

agent-alpha 当前最主要的问题，不在“不会做事”，而在“外壳层不够实例化”。

具体表现为：

1. 配置仍偏代码常量化  
还没有真正变成面向实例与环境的配置模型。

2. 项目根目录承担太多共享资源角色  
skills、mcp、部分路径和资源仍然默认围绕项目根组织。

3. CLI 和运行时边界还不够清楚  
CLI 中混入了不少会话恢复、工作区管理等职责。

4. 生命周期治理偏薄  
总线、cron、运行状态、重启治理等还更像占位能力。

## agent-alpha 最该借什么

### 从 nanobot 借

- 工作区中心化
- 人格文件装配
- 轻量 session / memory 闭环
- 简洁配置路径模型

为什么值得借：  
因为这套东西最贴近“把旧项目简化并保持可扩展”的目标。

### 从 OpenClaw 借

- 生命周期治理
- 命令层分层
- restart / drain 思想
- 插件契约意识

为什么值得借：  
因为它能帮助你避免后面一做大就散架。

### 从 agent-alpha 自己保留

- MCP 与 coding-agent 方向积累
- 现有工具系统
- 现有测试和权限思路

为什么要保留：  
因为这是你最贴近真实需求的资产，不应该推倒重来。

## 对 agent-alpha 的建议路线

### 阶段 1：先做 agent instance contract

先回答一个根本问题：

一个 agent 实例到底由什么组成？

建议至少明确以下对象：

- workspace
- identity docs
- skills
- memory
- mcp sources
- private config
- session store
- logs

这一步的目标是：  
让“输入工作路径，自动识别人格文档”成为正式能力，而不是散落在运行时中的零散逻辑。

这一步做对后，多 agent 编排才有真正的承载对象。

### 阶段 2：拆 CLI 与运行时边界

把 CLI 的交互逻辑、session 恢复、workspace 管理，从核心 runtime 中进一步剥离。

理想状态是：

- CLI 只是一个入口
- FastAPI 也是一个入口
- cron 也是一个入口
- 多 agent orchestration 也是一个入口

它们都挂在同一个更干净的 runtime 上。

这样做的好处是：

- 后端接口设计会更清楚
- 运行模式会更容易扩展
- 后续做编排层时，不需要反复绕过 CLI 逻辑

### 阶段 3：补生命周期与编排层

等实例边界和运行时边界清楚以后，再向 OpenClaw 选学：

- 健康检查
- 运行状态
- 重启恢复
- 任务排队
- 中断处理
- 多 agent orchestration

顺序上要注意：  
这些能力不是不该做，而是不该先做成平台壳。

## 优先级建议

### 优先级最高

先做实例边界。

先回答：

- 这个 agent 是谁
- 它住在哪个目录
- 它读哪些人格文档
- 它写哪些 memory / session / logs
- 它与别的 agent 如何隔离

### 优先级中等

再做运行入口分层。

目标是让：

- CLI
- API
- cron
- subagent 编排

都能挂在同一个核心 runtime 上。

### 优先级靠后

最后再补平台能力。

例如：

- 健康检查
- 运维工具
- 重启治理
- 编排控制面

这些很重要，但不该抢在实例边界之前。

## 最后的判断

你现在最该学的是“nanobot 的轻骨架”，而不是“OpenClaw 的重控制面”。

原因很简单：

你当前要做的不是从零搭一个完整平台，而是：

- 从既有项目中减冗余
- 清边界
- 提模块化
- 提鲁棒性
- 把工作区和人格识别能力做扎实

所以最合适的路线不是“朝 OpenClaw 扩张”，而是：

以 nanobot 的轻量骨架为参考，把 agent-alpha 现有的 coding-agent 核心重新挂到更清楚的实例外壳上。

最后用一句更直白的话收束：

OpenClaw 适合学“做大以后怎么不失控”，  
nanobot 适合学“做小以后怎么不散”，  
而 agent-alpha 现在最需要的，是把自己从“能跑”推进到“能稳、能隔离、能编排”。
