# Agent Reach、OpenClaw 与 agent-alpha 的 skill 安装机制分析

## 研究问题

这份笔记回答两个问题：

1. 为什么把 `agent-reach` 的仓库链接给到 `OpenClaw`，它往往就能自己装上？
2. 为什么 `agent-alpha` 现在做不到？如果要借鉴 `OpenClaw`，应该怎么改？

这份文档不是简单“把 skill 当提示词文档”来看，而是从更接近 harness engineering 的角度看：一个 agent 宿主，怎样接住“会安装 CLI、会准备环境、会注册能力”的外部 skill。

---

## 一句话结论

`OpenClaw` 能装上 `Agent Reach`，不是因为它更聪明，而是因为它和 `Agent Reach` 对 skill 的理解更接近：

- `Agent Reach` 不是普通提示词 skill，而是一个“能力安装包”
- `OpenClaw` 也不把 skill 只当成一份 `SKILL.md`，而是把它当成“可声明依赖、可执行安装、可检查状态”的能力单元
- `agent-alpha` 现在的 skill 机制还停留在“扫描文档、读文档、把文档提示给模型”的阶段，所以遇到这类带 CLI、带安装流程、带环境准备的 skill，就接不住

真正要借鉴的，不是 `OpenClaw` 的界面，也不是某一条安装命令，而是它背后的这套机制。

---

## 1. Agent Reach 到底是什么

### 1.1 它不是普通 skill

如果只看名字，容易把 `Agent Reach` 理解成一个“给 agent 读的说明文档”。  
但从仓库结构和安装方式看，它更像一个能力包：

- 它有 Python 包
- 它有 CLI 入口
- 它有安装命令
- 它有诊断命令
- 它会准备自己的工具目录
- 它还会把适合 agent 阅读的 `SKILL.md` 装到宿主的 skill 目录里

也就是说，`SKILL.md` 只是它对大模型暴露的一层说明。  
真正让它能工作的，是下面这些东西：

- Python 包本体
- CLI 命令
- 安装和诊断逻辑
- 依赖的外部工具
- skill 文档和参考资料

### 1.2 从仓库内容看，它已经是“安装型能力包”

从 `learning proj/agent-reach` 可以看到几件关键事：

- `pyproject.toml` 里注册了 CLI 入口：`agent-reach = agent_reach.cli:main`
- `docs/install.md` 不是在教人“复制一段提示词”，而是在教 agent 或用户先安装包，再执行 `agent-reach install --env=auto`
- `agent_reach/cli.py` 里有真正的安装逻辑，会准备目录、检查环境、安装依赖、复制 skill 文件
- skill 部分并不是仓库唯一主体，它只是被打包进去的一部分

所以更准确的描述是：

> Agent Reach 是一个“能给 agent 扩展外部能力的安装器 + skill 导出器”，而不是一份单纯的 prompt skill。

---

## 2. 为什么 OpenClaw 能装上 Agent Reach

## 2.1 因为 OpenClaw 承认 skill 可以不是纯文档

`OpenClaw` 对 skill 的建模，比 `agent-alpha` 更接近真实世界。

它并不假设每个 skill 都只是：

- 一个目录
- 一份 `SKILL.md`
- 一些说明文字

相反，它允许一个 skill 声明：

- 需要哪些依赖
- 如果缺依赖，应该怎么安装
- 安装动作属于哪一类
- 安装完后怎么判断是否可用

这意味着它把 skill 当成“能力单元”，而不只是“提示词单元”。

### 2.2 OpenClaw 的 skill metadata 更完整

从 `learning proj/openclaw/src/agents/skills/types.ts` 和相关解析代码看，`OpenClaw` 的 skill frontmatter 里已经有比较明确的安装语义，比如：

- `requires`
- `install`

这些字段很重要，因为它们把“这个 skill 需要什么”和“缺了以后怎么补”变成了结构化信息，而不是散落在文档里的自然语言说明。

对宿主来说，这种结构化信息意味着：

- 能做依赖检查
- 能生成安装计划
- 能限制安装动作的类型
- 能做安装前确认
- 能在安装后记录状态

### 2.3 OpenClaw 有受控的安装执行器

`OpenClaw` 不是简单地让模型自由执行一堆 shell 命令。  
它更像是给 skill 安装准备了一套“受控安装器”：

- 支持的安装方式是有限类型的
- 常见类型包括 `brew`、`node`、`go`、`uv`、`download`
- 它会对安装内容做一定检查
- 它会限制危险动作

这件事很关键。  
因为真实世界里的外部能力安装，几乎一定会碰到：

- 要装 CLI
- 要下载二进制
- 要配置环境变量
- 要准备目录
- 要把 skill 文档复制到托管目录

如果宿主没有“受控安装”这一层，模型就只能靠猜，靠现场拼命令，结果就很不稳定。

### 2.4 OpenClaw 有托管 skill 目录，而不是只看项目里的 skills

`OpenClaw` 还有一个很重要但容易被忽略的设计：

- 它不只读项目内 skill
- 它还有用户级或宿主级的托管 skill 目录，比如 `~/.openclaw/skills/...`

这意味着外来的能力包可以先装进宿主自己的空间，再被 runtime 发现和加载，而不是硬塞进当前项目仓库。

这个设计带来 3 个直接好处：

1. 不污染业务项目目录
2. skill 可以安装、卸载、升级、修复
3. 宿主可以把“工作区 skill”和“托管 skill”区分开管理

---

## 3. Agent Reach 是怎么把自己“装进 OpenClaw”的

### 3.1 Agent Reach 自己带安装器

从 `learning proj/agent-reach/agent_reach/cli.py` 可以看到，`Agent Reach` 并不是只提供说明文档，它自己已经实现了一层安装逻辑。

它会做的事情大致包括：

- 准备自己的工具目录，例如 `~/.agent-reach/tools`
- 安装或检查需要的外部工具
- 调用内部安装流程
- 把 `SKILL.md` 和 `references/` 复制到宿主可识别的位置

### 3.2 它会主动寻找宿主的 skill 目录

`Agent Reach` 的安装逻辑里，会检查一些已知宿主目录或相关环境变量。  
其中就包括 `~/.openclaw/skills` 和 `OPENCLAW_HOME` 这类路径线索。

这说明它不是“等宿主来理解我”，而是它自己也在主动适配宿主。

换句话说，这次能装上，实际上是两边一起配合：

- `Agent Reach` 愿意把自己导出成宿主能认的形态
- `OpenClaw` 也有足够成熟的托管和加载机制来接住它

### 3.3 真正跑通的不是一条命令，而是一条链

把现象拆开看，完整链路更像这样：

1. `OpenClaw` 能读懂这个 skill/能力包的安装信息
2. `OpenClaw` 允许在受控边界内执行安装
3. `Agent Reach` 的安装器把自己的外部依赖、目录和 skill 文件准备好
4. skill 文件进入 `OpenClaw` 可发现的托管目录
5. `OpenClaw` 的 runtime 再把它作为可用 skill 加载出来

所以“给 repo 链接然后自己装上”的表象下面，其实是：

> 宿主有安装模型，能力包也有导出模型，两边恰好对上了。

---

## 4. 为什么 agent-alpha 现在做不到

## 4.1 它的 skill 机制还太轻

结合当前 `agent-alpha` 代码看，它对 skill 的理解大致是：

- 扫描 `skills/**/SKILL.md`
- 读取 frontmatter 里的基础信息
- 把 skill 摘要放进 system prompt
- 在需要时通过 `load_skill` 读取正文

这套机制对于“文档型 skill”是成立的。  
比如：

- 一份操作规范
- 一份写作模板
- 一份某个工作流的提示词说明

但它对“安装型 skill”是不够的。

### 4.2 它没有安装状态层

`agent-alpha` 现在缺少一个明确的“skill 生命周期”。

也就是说，它没有系统地回答这些问题：

- 这个 skill 是不是已安装？
- 缺了哪些依赖？
- 它现在是否 ready？
- 它是否 degraded？
- 该不该提示用户修复？
- 卸载后怎么清理？

当 skill 只是文档时，这些问题不明显。  
可一旦 skill 依赖 CLI、二进制、环境变量、MCP 或目录注册，这层状态就不能没有。

### 4.3 它没有受控安装器

`agent-alpha` 目前没有像 `OpenClaw` 那样明确的一层：

- 解析安装元数据
- 生成安装计划
- 检查依赖
- 控制允许的安装类型
- 执行安装
- 落安装状态

没有这层以后，大模型面对外部能力仓库时，只能把安装说明当自然语言去“现想现做”。  
这会带来几个问题：

- 不稳定
- 难审计
- 难复现
- 难排错
- 很难让不同 skill 共存

### 4.4 它没有托管 skill 根目录体系

`agent-alpha` 现在更像是在项目内扫描 skill。  
但像 `Agent Reach` 这种东西，更合理的安装位置通常不是项目仓库，而是 agent 宿主自己的目录。

如果没有用户级托管目录，就会出现几个尴尬问题：

- 外部 skill 装到哪里？
- CLI 二进制放哪里？
- 安装状态记录放哪里？
- 多项目之间怎么复用？
- 卸载和升级怎么做？

### 4.5 它还没有把“skill”和“工具安装”分层

这是最本质的一点。

`agent-alpha` 现在更像是：

> skill = 给模型看的文档

但对 `Agent Reach` 这种能力包，正确抽象更接近：

> skill = 给模型看的使用说明  
> package = 给宿主安装外部能力的载体

如果宿主没有把这两层拆开，就会出现现在这个现象：

- 文档能读
- 但能力装不进去
- 文档说得再清楚，也不等于宿主真的会安装

---

## 5. OpenClaw 最值得借的，不是界面，而是这套机制

如果只从“抄什么”这个角度看，最值得借的有 6 件事。

### 5.1 Skill metadata 升级

skill 不能再只有 `name`、`description` 这类轻量信息。  
至少要让宿主知道：

- 需要什么依赖
- 依赖缺了怎么办
- 支持哪些平台
- 安装入口是什么
- 安装后导出什么能力

### 5.2 安装状态层

宿主要能维护每个 skill 的状态，例如：

- `not_installed`
- `installing`
- `ready`
- `degraded`
- `failed`

没有这层，agent 只能在每次调用时重新猜。

### 5.3 每个 skill 自己的工具目录

像 `Agent Reach` 这类能力包，最好有自己独立的 artifacts 目录。  
这样可以避免不同 skill 的依赖互相污染，也方便做卸载和诊断。

### 5.4 受控安装器

宿主不应该把“任意 shell 执行”当成安装机制。  
更好的方式是白名单化安装类型，比如：

- `uv`
- `node`
- `go`
- `download`

这样比较容易做审计、日志和权限控制。

### 5.5 外来 skill 的托管接入路径

宿主要允许外来的能力包被安装到自己的托管目录里，然后再纳入 skill 发现流程。

这一步非常重要，因为它决定宿主是不是能接住“仓库型 skill”“CLI 型 skill”“MCP 型 skill”。

### 5.6 安全边界

这类机制一旦做出来，就天然会触碰：

- 执行命令
- 下载文件
- 修改目录
- 配置环境

所以必须一开始就把安全边界想清楚。  
否则能力会强，但系统会很脆。

---

## 6. agent-alpha 如何支持这种“非典型 skill”

## 6.1 先把定义改对

对 `agent-alpha` 来说，最重要的第一步不是“赶紧支持安装命令”，而是先把模型抽象改对。

更合适的定义是：

- `Skill Doc`：给模型读的说明
- `Skill Package`：给宿主安装能力的包
- `Managed Skill`：已经被宿主托管、可被 runtime 发现的能力

这样以后遇到：

- 纯文档型 skill
- 带脚本的 skill
- 带 CLI 的 skill
- 带 MCP 的 skill
- 带 exe 的 skill

都可以落到同一套框架里，而不是每来一种新类型就临时打补丁。

### 6.2 建议 skill metadata 最少补这些字段

第一版不需要太重，但建议至少补下面这些能力：

- `skill_key`
- `os`
- `requires.bins`
- `requires.env`
- `install[]`
- `entrypoints`

可以把它理解成几类问题：

- 我是谁
- 我在哪些系统能装
- 我依赖什么
- 我怎么装
- 装完后从哪里使用

### 6.3 新增 `skill_manager.py`，不要把所有逻辑塞进 `skill_loader.py`

`skill_loader.py` 更适合负责：

- 扫描
- 解析文档
- 提供 skill 摘要
- 返回 skill 内容

而安装、状态、生命周期这些事，建议单独给一个模块，例如：

- `skill_manager.py`

它来负责：

- 读取安装元数据
- 检查依赖
- 生成安装计划
- 执行安装
- 记录状态
- 暴露 doctor / uninstall / repair 能力

这样后面系统不会越长越乱。

### 6.4 运行时先判断 skill 是否 ready

未来的调用逻辑最好从“直接加载 skill 文档”改成：

1. 先判断这个 skill 是不是已安装、是否 ready
2. 如果只是文档型 skill，直接读
3. 如果是安装型 skill 但未就绪，优先进入受控安装流程
4. 安装完成后，再让 agent 使用它

这一步看起来只是流程调整，实际上会明显提升鲁棒性。

---

## 7. 一个适合 agent-alpha 的落地模型

下面这个模型，比较适合 `agent-alpha` 当前阶段：不至于过重，但能把路走对。

### 7.1 目录层

建议区分 3 类目录：

- 工作区内 skill：项目自己的 `skills/`
- 用户级托管 skill：例如 `<agent-home>/skills/`
- 用户级工具目录：例如 `<agent-home>/tools/<skill-key>/`

这样做以后：

- 项目内 skill 继续保留
- 外来 skill 不污染项目仓库
- 每个 skill 的安装产物有独立位置

### 7.2 状态层

建议增加一个简单状态记录，例如：

- `name`
- `version`
- `source`
- `installed_at`
- `status`
- `provided_bins`
- `skill_dir`

先别追求很复杂，第一版能回答“装了没、能不能用、东西放哪了”就已经很值钱。

### 7.3 安装动作层

第一阶段建议只支持少数受控类型：

- `uv`
- `node`
- `download`

原因很简单：

- 覆盖面已经不算低
- 实现复杂度相对可控
- 风险也更容易收住

`brew`、`go`、任意 shell、复杂系统级安装，可以后续再扩。

### 7.4 导出层

安装完成后，skill package 至少应该能导出 3 类东西：

- `SKILL.md` 和 `references/`
- 提供的 CLI 名称
- 可能需要注册的 MCP server

这里的关键不是“复制文件”，而是让宿主明确知道：

- 这次安装到底给系统增加了什么能力

---

## 8. 分阶段改造建议

## 阶段一：把地基补上

目标：先让 `agent-alpha` 能识别“安装型 skill”。

建议做的事：

- 给 frontmatter 增加 `requires` 和 `install`
- 新增 `skill_manager.py`
- 增加 `<agent-home>/tools/<skill-key>/` 这类工具目录
- 增加托管 skill 根目录
- 增加最基础的 status 记录

这一阶段的重点不是“多强”，而是先把模型从“纯文档 skill”升级成“可安装 skill”。

## 阶段二：让它真的能装

目标：先支持最常见的受控安装类型。

建议优先支持：

- `uv`
- `node`
- `download`

同时加上：

- 安装前依赖检查
- 安装计划展示
- 用户确认
- 安装日志
- 安装后状态刷新

## 阶段三：接住 Agent Reach 这类能力包

目标：不仅能装普通 skill，还能接住“能力型仓库”。

建议补上：

- 安装后注册 `SKILL.md`
- 支持 repo / url / package 作为来源
- 加入 `doctor` 能力
- 加入 repair / uninstall 基础流程

到这一阶段，`agent-alpha` 就开始具备接近 `OpenClaw` 的“可托管能力”雏形了。

## 阶段四：做成可长期扩展的宿主能力

目标：让这套机制能支撑多 agent、多工作区和更复杂的能力编排。

后续可以考虑：

- 托管 skill 与 workspace skill 的优先级策略
- 多 agent 共享与隔离策略
- MCP 注册表
- 前端或 API 展示安装状态与日志
- 权限审批和安全审计

---

## 9. 最后的判断

如果把这件事说得再直白一点：

- `OpenClaw` 之所以能装 `Agent Reach`，是因为它把 skill 当成“能力包”
- `Agent Reach` 之所以能被装上，是因为它自己也把自己做成了“可安装能力包”
- `agent-alpha` 现在接不住，不是差在模型智商，而是差在宿主抽象还太轻

所以对 `agent-alpha` 来说，最重要的不是去模仿 `OpenClaw` 的表面交互，而是补齐下面这条链：

> skill metadata -> install plan -> controlled installer -> managed roots -> status model -> runtime discovery

这条链补起来以后，`agent-alpha` 才有可能真正支持这类“非典型 skill”：

- 带 CLI 的 skill
- 带 exe 的 skill
- 带 MCP 的 skill
- 带安装器的 skill
- 不是单纯文档的 skill

如果这条链不补，未来即使偶尔能“装上一个”，大概率也只是碰巧跑通，而不是系统能力。

---

## 附：本次判断主要依据

主要参考了这些本地文件与项目结构：

- `learning proj/agent-reach/docs/install.md`
- `learning proj/agent-reach/agent_reach/cli.py`
- `learning proj/agent-reach/pyproject.toml`
- `learning proj/openclaw/src/agents/skills/types.ts`
- `learning proj/openclaw/src/agents/skills/frontmatter.ts`
- `learning proj/openclaw/src/agents/skills-install.ts`
- `learning proj/openclaw/src/agents/skills/workspace.ts`
- `agent-alpha/agent/core/skill_loader.py`
- `agent-alpha/agent/core/tool_loader.py`
- `agent-alpha/agent/core/system_prompt_builder.py`

---

## 后续可直接继续做的两件事

如果要把这份研究继续往前推，下一步最值得做的是：

1. 直接给 `agent-alpha` 补一版最小 `skill_manager.py` 设计稿
2. 先拿 `Agent Reach` 当样本，反推一份 `agent-alpha` 兼容的 skill package manifest 草案

这两步做完，后面就能从“分析”进入“可落地设计”了。
