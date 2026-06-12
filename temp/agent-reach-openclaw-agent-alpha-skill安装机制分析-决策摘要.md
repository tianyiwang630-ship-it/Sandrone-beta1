# Agent Reach、OpenClaw 与 agent-alpha 的 skill 安装机制分析：决策摘要

## 一句话判断

`OpenClaw` 能装上 `Agent Reach`，核心不是模型更强，而是它把 skill 当成“可安装能力包”；`agent-alpha` 现在还主要把 skill 当成“给模型读的文档”，所以接不住这类带 CLI、带安装流程、带外部依赖的非典型 skill。

---

## 这件事的本质

`Agent Reach` 不是普通 skill。

它本质上更像一个“能力安装包”：

- 有 Python 包
- 有 CLI 入口
- 有安装命令
- 有诊断逻辑
- 会准备自己的工具目录
- 会把 `SKILL.md` 和参考资料导出到宿主的 skill 目录

所以它不是“读完提示词就能用”的东西，而是“先安装能力，再给 agent 一份使用说明”。

---

## 为什么 OpenClaw 能装上

因为 `OpenClaw` 具备 4 个 `agent-alpha` 现在还没有的关键能力：

1. `skill` 有安装语义  
它支持 `requires`、`install` 这类 metadata，不只识别 `name`、`description`。

2. 有受控安装器  
它不是让模型随便跑 shell，而是支持有限类型的安装动作，比如 `uv`、`node`、`go`、`download`。

3. 有托管 skill 目录  
像 `~/.openclaw/skills/` 这样的宿主目录，可以接住外部能力包。

4. 有 runtime 发现和加载闭环  
装进去以后，宿主能重新发现它、识别它、加载它。

简单说：

> OpenClaw 有“安装能力包”的宿主机制，Agent Reach 也有“导出给宿主”的安装器，所以两边对上了。

---

## 为什么 agent-alpha 现在不行

`agent-alpha` 现在的 skill 机制更像这样：

- 扫描 `skills/**/SKILL.md`
- 读 frontmatter
- 把 skill 摘要放进 system prompt
- 需要时再加载正文

这对文档型 skill 是够的，但对 `Agent Reach` 这种安装型 skill 不够。  
它当前主要缺 5 层：

1. 缺安装型 metadata  
没有系统表达“需要什么依赖、怎么安装、支持哪些系统”。

2. 缺安装状态层  
不知道某个 skill 是 `ready`、`failed` 还是根本没安装。

3. 缺受控安装器  
没有一层正式模块去解析安装计划、执行安装、记录结果。

4. 缺托管根目录  
没有用户级 managed skills / tools / state 目录。

5. 缺“文档”和“能力包”的分层  
现在更像 `skill = 文档`，但对非典型 skill 应该是：

`skill doc = 给模型看的`

`skill package = 给宿主安装能力的`

---

## 最值得借鉴的方向

不是去模仿 `OpenClaw` 的外观，而是补齐这条链：

`skill metadata -> install plan -> controlled installer -> managed roots -> status model -> runtime discovery`

只要这条链还没补齐，未来即使偶尔装上某个特殊 skill，也更像“碰巧跑通”，不是稳定系统能力。

---

## 对 agent-alpha 的最小改造建议

建议分两步看。

### 第一步：先把模型抽象改对

给 `agent-alpha` 增加一层“安装型 skill”的正式概念：

- `Skill Doc`：给模型读的说明
- `Skill Package`：给宿主安装外部能力的包
- `Managed Skill`：已经安装并可被 runtime 发现的能力

### 第二步：先做最小闭环，不要一开始做太重

优先补这些：

- frontmatter 增加 `requires`、`install`
- 新增 `skill_manager.py`
- 增加 `<agent-home>/skills/`、`<agent-home>/tools/<skill-key>/`
- 增加最基础的 status 记录
- 第一阶段只支持 `uv`、`node`、`download`

这样已经足够开始接住 `Agent Reach` 这类能力包。

---

## 最终建议

如果你的目标是让 `agent-alpha` 将来支持：

- 带 CLI 的 skill
- 带 exe 的 skill
- 带 MCP 的 skill
- 带安装器的 skill

那么下一步最值得做的，不是继续讨论 prompt，而是正式设计：

1. `skill_manager.py` 的职责边界
2. 一份 `agent-alpha` 兼容的 skill package manifest

这两件事落下来，`agent-alpha` 才会从“会读 skill”走向“会托管 skill”。
