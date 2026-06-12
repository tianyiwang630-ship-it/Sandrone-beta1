# OpenClaw / Hermes / agent-alpha 的 Skill 安装与管理机制对比

日期：2026-05-26  
范围：只基于本地项目源码与本地文档，不联网，不对 agent-alpha 做代码修改。  
关注场景：用户给出 `Panniantong/Agent-Reach.git` 这类 GitHub skill/CLI 工具，希望 agent 能安装并处理 `npm` 或 `pip` 等依赖。

## 1. 一句话结论

OpenClaw、Hermes、agent-alpha 对“安装 skill”的理解并不相同：

- OpenClaw 把“skill 包的获取”和“skill 声明的依赖安装”分成两层：ClawHub 负责下载、同步、更新 skill 包；OpenClaw 核心负责读取 skill frontmatter 中的安装声明，并可执行 `brew`、`npm`、`go`、`uv`、下载包等安装动作。
- Hermes 有比较完整的 skill hub：能从 GitHub、URL、内置索引、tap 等来源安装、更新、卸载 skill 包，并用 lock 文件记录来源与内容哈希；但本地代码显示，它主要是安装 skill 文件本身，不会自动执行 skill 文档中的 `pip install` 或 `npm install`。
- agent-alpha 目前是“手动放入 skills 目录后加载”的机制：能扫描和调用 `SKILL.md`，也能在普通 bash 工具里识别 `pip install` / `npm install` 这类命令需要审批，但没有 skill 安装器、依赖解析、lock、更新、卸载或来源记录。

因此，像 `Panniantong/Agent-Reach.git` 这种“给一个 Git 仓库，让 agent 安装成 skill，并处理依赖”的流程，在 agent-alpha 里目前没有形成闭环。

## 2. 研究对象与证据位置

### OpenClaw

主要证据：

- `learning proj/openclaw/src/agents/skills-install.ts`
- `learning proj/openclaw/src/agents/skills-install-download.ts`
- `learning proj/openclaw/src/agents/skills-install-extract.ts`
- `learning proj/openclaw/src/agents/skills-status.ts`
- `learning proj/openclaw/src/agents/skills/types.ts`
- `learning proj/openclaw/src/agents/skills/frontmatter.ts`
- `learning proj/openclaw/src/agents/skills/workspace.ts`
- `learning proj/openclaw/src/agents/skills/refresh.ts`
- `learning proj/openclaw/src/cli/skills-cli.ts`
- `learning proj/openclaw/src/gateway/server-methods/skills.ts`
- `learning proj/openclaw/docs/tools/clawhub.md`

### Hermes

主要证据：

- `learning proj/hermes-agent/hermes_cli/skills_hub.py`
- `learning proj/hermes-agent/tools/skills_hub.py`
- `learning proj/hermes-agent/tools/skills_tool.py`
- `learning proj/hermes-agent/agent/skill_utils.py`
- `learning proj/hermes-agent/agent/skill_bundles.py`
- `learning proj/hermes-agent/agent/skill_commands.py`
- `learning proj/hermes-agent/tools/skills_config.py`
- `learning proj/hermes-agent/optional-skills/...`

### agent-alpha

主要证据：

- `agent-alpha/agent/core/skill_loader.py`
- `agent-alpha/agent/core/tool_loader.py`
- `agent-alpha/agent/core/command_path_extractor.py`
- `agent-alpha/agent/core/sandbox_guard.py`
- `agent-alpha/agent/core/permissions.json`
- `agent-alpha/agent/tools/bash_tool.py`
- `agent-alpha/README.md`

## 3. 生命周期总览

| 生命周期环节 | OpenClaw | Hermes | agent-alpha |
|---|---|---|---|
| 获取 skill 包 | 主要通过 ClawHub；OpenClaw 本体也能从多个目录加载本地/托管/插件 skill | 内置 skill hub，可从 GitHub、URL、tap、索引等来源安装 | 无安装入口；需要手动把 skill 放进 `skills/` |
| 存储位置 | 工作区、`.agents/skills`、`~/.agents/skills`、`~/.openclaw/skills`、bundled、extra、plugin | `~/.hermes/skills`，可按 category 分组；hub 元数据在 `.hub` | `project_root/skills` |
| 元数据解析 | 解析 frontmatter，支持结构化 install spec | 解析 frontmatter 与 skill index，hub 另有 metadata/lock | 只做简单 `key: value` 拆分 |
| 依赖安装 | 有明确 install spec：`brew` / `node` / `go` / `uv` / `download` | hub 安装 skill 文件；未发现自动执行 `pip` / `npm` 依赖安装 | 无依赖安装流程；普通 bash 可跑 `pip install` / `npm install`，但不是 skill 安装 |
| 安全控制 | install spec 校验、目录扫描、下载路径防逃逸、压缩包安全解包 | quarantine、路径校验、安全扫描、policy、lock、audit | bash 命令分类与审批；无 skill 包扫描 |
| 状态检查 | `skills-status.ts` 检查 bin 是否缺失并选择安装方案 | lock hash 对比检查更新；list 显示 hub/builtin/local/disabled | reload 后只知道有哪些 skill |
| 更新 | ClawHub 支持 update；运行时有 refresh/watch | hub update 通过 lock 重新 fetch 并比较 hash | 无远程更新机制 |
| 删除 | ClawHub 文档有 delete/undelete；本体加载层可随文件移除刷新 | hub uninstall，只卸载 lock 记录的 hub skill | 手动删除文件夹 |
| 调用 | skill 可变成 slash command / tool dispatch；也能暴露 bin 状态 | progressive disclosure，`skill_view` 加载完整内容；可启用/禁用 | `load_skill(name)` 工具加载完整 skill 文本 |

## 4. OpenClaw 机制拆解

### 4.1 Skill 包安装与依赖安装是两件事

OpenClaw 的代码里，“skill 包从哪里来”和“这个 skill 需要什么依赖”是分开的。

ClawHub 文档显示，它负责公共 registry 相关动作，例如：

- `search`
- `install`
- `update`
- `list`
- `publish`
- `delete` / `undelete`
- `sync`

默认安装位置是当前目录下的 `./skills`，并维护 `.clawhub/lock.json`。这部分更像“skill 包管理器”。

OpenClaw 核心的 `skills-install.ts` 则处理已经被加载的 skill 所声明的依赖。也就是说，它不是简单看到一个 GitHub URL 就直接克隆并运行，而是先要有一个可识别的 skill，然后从 skill metadata 中读取安装声明。

### 4.2 OpenClaw 的 install spec

`learning proj/openclaw/src/agents/skills/types.ts` 中的 `SkillInstallSpec` 支持这些类型：

- `brew`
- `node`
- `go`
- `uv`
- `download`

每一种类型都有自己的字段，例如：

- `node`：`package`
- `go`：`module`
- `brew`：`formula`
- `download`：`url`、`archive`、`extract`、`targetDir`
- 通用：`id`、`label`、`description`、`bins`、`os`

这意味着 OpenClaw 可以让 skill 自己声明：“我需要哪个 npm 包、哪个 uv tool、哪个二进制文件、或者哪个下载包。”

### 4.3 OpenClaw 的依赖安装动作

`skills-install.ts` 中会根据 `kind` 生成不同安装命令：

- `node` 默认走 `npm install -g --ignore-scripts <package>`
- 也支持 `pnpm add -g --ignore-scripts`
- 也支持 `yarn global add --ignore-scripts`
- 也支持 `bun add -g`
- `brew` 走 `brew install`
- `go` 走 `go install`
- `uv` 走 `uv tool install`

另外，代码中还有辅助安装逻辑：

- 如果缺 `uv`，可尝试用 `brew` 安装 `uv`
- 如果缺 `go`，可尝试用 `brew` 或 Linux 上的 `apt` 安装

对下载型依赖，OpenClaw 使用单独的 `skills-install-download.ts` 和 `skills-install-extract.ts`，把工具放到每个 skill 对应的 tools 目录，并检查下载路径和解压路径，避免压缩包把文件写到安全目录外。

### 4.4 OpenClaw 的安全与状态

OpenClaw 的 frontmatter 解析会做基本校验：

- `brew formula` 必须是安全格式
- `npm package spec` 必须是安全格式
- `go module` 必须是安全格式
- `uv package` 必须是安全格式
- 下载 URL 只接受 `http` / `https`
- 缺少必要字段会拒绝

安装前还会扫描 skill 目录，并把扫描结果和警告一起返回。

`skills-status.ts` 会检查 skill 需要的二进制命令是否缺失，并在多个安装方案中选择一个更合适的方案。大致优先级是：偏好的 brew、`uv`、`node`、可用 brew、`go`、`download`、brew fallback、第一项。

### 4.5 OpenClaw 的存储、刷新与调用

`workspace.ts` 会从多个位置加载 skill：

- 当前 workspace 的 `skills`
- 当前 workspace 的 `.agents/skills`
- 个人级 `~/.agents/skills`
- OpenClaw 托管目录 `~/.openclaw/skills`
- bundled skills
- extra dirs
- plugin skill dirs

代码里还写了加载优先级，大致是 extra < bundled < managed < personal < project < workspace。

`refresh.ts` 会 watch skill 文件变化，主要关注 `SKILL.md`。因此 OpenClaw 的 skill 可以被动态刷新。

调用层面，OpenClaw 可以把 skill 转为 slash command；如果 frontmatter 里有 `command-dispatch: tool`，也能走 tool dispatch 形式。

## 5. Hermes 机制拆解

### 5.1 Hermes 有完整的 skill hub

Hermes 的 hub 逻辑集中在：

- `hermes_cli/skills_hub.py`
- `tools/skills_hub.py`

关键目录常量：

- skill 存储：`~/.hermes/skills`
- hub 元数据：`~/.hermes/skills/.hub`
- lock 文件：`~/.hermes/skills/.hub/lock.json`

Hermes 的安装流程不是“只扫描本地目录”，而是有明确的 hub 命令和来源解析。

### 5.2 Hermes 支持多种来源

本地代码里可见的来源包括：

- GitHub 仓库目录
- 直接 URL Markdown 文件
- skills.sh
- ClawHub
- Claude Marketplace
- LobeHub
- Browse.sh
- optional skills
- Hermes index
- 自定义 tap

其中 GitHub 来源比较关键：`GitHubSource.fetch(identifier)` 期望标识类似：

```text
owner/repo/path/to/skill-dir
```

它通过 GitHub API 下载目录内容，要求目录中有 `SKILL.md`。它不是简单 `git clone` 整个仓库。

### 5.3 Hermes 的安装流程

Hermes 的 `do_install` 大致流程：

1. 解析用户传入的 identifier 或 URL。
2. 如果是短名，尝试从索引里解析。
3. 拉取 metadata 与 bundle。
4. 如果已经安装，需要 `--force` 才覆盖。
5. 先放入 quarantine 临时区。
6. 对 skill 执行安全扫描。
7. 检查 policy。
8. 需要时向用户确认。
9. 移动到 `~/.hermes/skills[/category]/skill-name`。
10. 写入 lock 文件。
11. 写 audit 记录。
12. 如果带 `--now`，清理 prompt cache，使当前会话更快看到变化。

### 5.4 Hermes 的 lock、更新、删除

Hermes 的 lock 记录内容比较完整，包括：

- source
- identifier
- trust_level
- scan_verdict
- content_hash
- install_path
- files
- metadata
- installed_at
- updated_at

更新时，Hermes 根据 lock 里的 source 和 identifier 重新拉取 upstream bundle，计算最新 hash，与本地 hash 比较：

- hash 一样：`up_to_date`
- hash 不同：`update_available`
- 拉取失败：`unavailable`

删除时，`uninstall_skill` 只删除 lock 中记录的 hub-installed skill。对 builtin 或普通 local skill，它不会把它当作 hub skill 删除。

### 5.5 Hermes 的启用、禁用与调用

Hermes 支持启用/禁用 skill 或 category。配置写在 `~/.hermes/config.yaml` 的 `skills.disabled` 和 `skills.platform_disabled` 等字段中。

运行时加载集中在 `tools/skills_tool.py` 和 `agent/skill_utils.py`：

- 所有 skill 主要来自 `~/.hermes/skills`
- 支持配置 external dirs
- 扫描时排除 `.hub`、`.git`、`.venv`、`node_modules`、`site-packages` 等目录
- `skill_view` 负责按需加载完整 skill 内容
- 也会检查禁用状态和路径安全

### 5.6 Hermes 对依赖安装的实际边界

Hermes 的 optional skills 中能看到很多依赖说明，例如：

- `pip install fastmcp`
- `pip install httpx`
- `npm install -g hyperframes`
- `requirements.txt`

但在 hub 安装流程中，没有看到自动执行这些命令的逻辑。也就是说，Hermes 很强的是“安装 skill 文件、记录来源、更新删除、管理启停”；但对 `pip` / `npm` 依赖，本地代码显示更偏向让 skill 文档说明，而不是 hub 自动执行。

这一点和 OpenClaw 不一样：OpenClaw 有显式的 install spec 与 installer；Hermes 有 hub 管理，但没有同等的自动依赖执行闭环。

## 6. agent-alpha 机制拆解

### 6.1 agent-alpha 当前是手动 skill 加载

`agent-alpha/agent/core/skill_loader.py` 很简洁：

- 只扫描传入的 `skills_dir`
- 查找所有 `SKILL.md`
- 解析 frontmatter
- 需要 `name` 和 `description`
- 通过 `get_summaries()` 提供摘要
- 通过 `get_content(name)` 返回完整 skill 内容

frontmatter 解析方式是按行拆 `key: value`，不支持复杂 YAML，不解析结构化安装声明。

### 6.2 agent-alpha 的工具加载

`tool_loader.py` 中会把 skills 目录固定到项目根下的 `skills`：

```text
project_root / "skills"
```

它会注册一个 `load_skill` 工具。这个工具的作用是：当模型需要某个 skill 的详细内容时，把 `SKILL.md` 正文加载进来。

这属于“调用前的渐进披露”，不是“安装管理”。

### 6.3 agent-alpha 能识别 pip/npm，但只是在 bash 权限层

`command_path_extractor.py` 中列出了 package install patterns：

- `pip install`
- `pip uninstall`
- `npm install`
- `npm uninstall`
- `pnpm install`
- `pnpm add`
- `yarn install`
- `yarn add`
- 以及 `python -m pip install`

`sandbox_guard.py` 会把这类命令归为 `package_install`，决策是 `ask`，原因是包安装或删除需要用户审批。

`permissions.json` 里也把 `bash:npm install*` 和 `bash:pip install*` 放进 ask 级别。

这说明 agent-alpha 不是完全不能运行 npm/pip。它可以在普通 shell 执行层面识别并审批这类命令。但这和 skill 安装器不是一回事：

- 没有从 GitHub 下载 skill 的流程
- 没有识别 skill 依赖声明的流程
- 没有 lock 文件
- 没有安装来源记录
- 没有更新检查
- 没有卸载流程
- 没有安装前扫描 skill 包
- 没有“安装后刷新 skill 索引”的专门动作

### 6.4 README 中的 skill 描述

agent-alpha README 描述的是手动添加 skill：

- 在 `skills/` 下创建目录
- 放入 `SKILL.md`
- 可以有 `scripts/`、`references/`、`assets/`
- agent 通过摘要和 `load_skill` 使用它

这更接近“本地技能目录约定”，还不是“skill 包管理器”。

## 7. Agent-Reach.git 场景走查

假设用户丢给 agent：

```text
Panniantong/Agent-Reach.git
```

希望它完成：

1. 获取仓库。
2. 判断它是不是 skill。
3. 放到正确的 skill 目录。
4. 解析依赖。
5. 安装 `npm` 或 `pip` 依赖。
6. 刷新 skill 列表。
7. 后续可以被 agent 调用。

### OpenClaw 中的可能路径

OpenClaw 的路径大致分两段：

第一段是 skill 包进入系统。这个更偏 ClawHub 或本地 skill 目录同步。

第二段是依赖安装。如果 Agent-Reach 作为 skill 已经被安装到 OpenClaw 可扫描的位置，并且 `SKILL.md` frontmatter 中声明了符合 OpenClaw 规则的 `install`，OpenClaw 就可以检查缺失 bin，并触发相应安装方式。

因此，OpenClaw 的关键点是：依赖安装不是靠模型自由发挥，而是靠 skill metadata 中的结构化 install spec。

### Hermes 中的可能路径

Hermes 的 hub 可以接受 GitHub 路径类 identifier，并下载其中包含 `SKILL.md` 的目录。它会 quarantine、安全扫描、安装到 `~/.hermes/skills`、写 lock、支持 update/uninstall。

但是如果 Agent-Reach 需要 `npm install` 或 `pip install`，本地代码没有显示 hub 会自动执行这些依赖安装命令。依赖更可能停留在 skill 文档里，由用户或 agent 在后续运行时按说明执行。

因此，Hermes 对“skill 包安装管理”比较完整；对“依赖自动安装”没有 OpenClaw 那样明确。

### agent-alpha 中的实际路径

agent-alpha 目前没有“给一个 GitHub repo 安装 skill”的入口。

如果用户丢 `Panniantong/Agent-Reach.git`，agent-alpha 现有机制最多只能：

- 通过普通 bash 工具执行 `git clone` 或类似命令
- 手动把内容放进 `skills/`
- 再依靠 `SkillLoader.reload()` 重新扫描
- 如果需要 `pip install` / `npm install`，通过普通 bash 命令执行，并触发审批

但这些步骤不是一个内置的 skill 安装流程，也不会被 lock、update、uninstall、status 管理。

## 8. 三者差异的本质

### OpenClaw：依赖安装能力最结构化

OpenClaw 的特点是把依赖安装写进 skill metadata，并用统一 installer 执行。它更关心：

- 这个 skill 需要哪些 bin？
- 缺了什么？
- 用哪个安装方案？
- 安装命令是否安全？
- 下载文件是否越界？

它适合处理“skill 需要某个 CLI 工具”的问题。

### Hermes：skill 包管理最完整

Hermes 的特点是 hub 管理成熟。它更关心：

- skill 从哪里来？
- 是否可信？
- 安装到了哪里？
- 哪些文件属于它？
- 现在是否有更新？
- 能否卸载？
- 能否按 category 启用/禁用？

它适合处理“skill 本身如何分发、记录、更新、回滚”的问题。

### agent-alpha：当前只做到本地加载

agent-alpha 的特点是简单。它更关心：

- `skills/` 里有哪些 `SKILL.md`？
- 哪些 skill 有 `name` 和 `description`？
- 模型需要时如何加载完整内容？

它还没有把“安装”作为一个独立生命周期来建模。

## 9. 对比表：安装与管理能力

| 能力 | OpenClaw | Hermes | agent-alpha |
|---|---:|---:|---:|
| 本地扫描 `SKILL.md` | 有 | 有 | 有 |
| 多目录加载 | 有 | 有 | 基本无，主要 `skills/` |
| GitHub skill 安装 | 主要通过 ClawHub/外部管理 | 有，hub 内置 | 无 |
| URL 单文件安装 | 未作为核心路径看到 | 有，Markdown URL | 无 |
| registry / index | ClawHub | Hermes index / optional / 多来源 | 无 |
| lock 文件 | ClawHub `.clawhub/lock.json` | `.hub/lock.json` | 无 |
| 安装来源记录 | ClawHub | 有 | 无 |
| 安装安全扫描 | 有目录扫描和安装校验 | 有 quarantine + scan + policy | 无 skill 包扫描 |
| 自动依赖安装 | 有结构化 installer | 未发现自动执行 pip/npm | 无 |
| npm 全局安装 | 有 `node` installer | 文档中可写，但 hub 不自动跑 | bash 可跑，需审批 |
| pip/uv 安装 | 有 `uv` installer；没有看到通用 pip installer | 文档中可写 pip，但 hub 不自动跑 | bash 可跑，需审批 |
| 缺失 bin 检查 | 有 | 未作为核心 hub 状态看到 | 无 |
| 更新检查 | ClawHub update；运行时 refresh | 有 hash 对比 | 无 |
| 卸载 | ClawHub 管理 | 有 hub uninstall | 手动删除 |
| 启用/禁用 | 主要通过目录/配置加载 | 有 skill/category disable | 无 |
| 调用方式 | slash command / tool dispatch / skill 内容 | progressive disclosure / `skill_view` | `load_skill(name)` |

## 10. 结论性观察

1. OpenClaw 的强项是“skill 依赖安装”。

   它不是把 `pip install` / `npm install` 写在正文里让模型猜，而是把安装声明作为 skill metadata 的一部分解析、校验、执行。

2. Hermes 的强项是“skill 包生命周期管理”。

   它知道 skill 从哪里来、装在哪里、有哪些文件、hash 是什么、能不能更新、能不能卸载，也能处理多来源和 tap。

3. agent-alpha 的当前状态是“加载器”，不是“安装器”。

   它能使用本地已经存在的 skill，但没有从 GitHub 安装 skill、安装依赖、记录来源、检查更新和删除的系统流程。

4. 对 `Agent-Reach.git` 这类场景，agent-alpha 卡住的位置不是单纯“能不能跑 npm/pip”，而是缺少从 repo 到 skill 生命周期的整条链路。

   npm/pip 在 agent-alpha 中属于普通 bash 命令审批；skill 安装在 agent-alpha 中还没有被建模。

