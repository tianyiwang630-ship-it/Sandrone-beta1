# agent-alpha Skill 安装与 Sandbox 方向备忘

日期：2026-05-29

## 已确定方向

### 1. 取消用户目录 `~/.agent-alpha`

不再使用类似 Codex 的用户级路径：

```text
C:\Users\<user>\.agent-alpha
~/.agent-alpha
```

alpha 自己需要的运行目录全部放在项目内部。不是只创建几个业务目录，而是要在 `agent-alpha` 内部模拟一个更完整的软件用户目录环境：

```text
agent-alpha/home
agent-alpha/userfile
agent-alpha/skills
agent-alpha/temp
agent-alpha/cache
agent-alpha/tools
agent-alpha/config
agent-alpha/data
agent-alpha/state
agent-alpha/config/appdata
agent-alpha/data/localappdata
agent-alpha/.venv
```

`agent-alpha/home` 是 alpha 的本地 home 概念，不等于系统用户 home。

启动 alpha 时，应把常见用户目录、配置目录、缓存目录、临时目录环境变量都导向 alpha 内部：

```text
HOME=agent-alpha/home
USERPROFILE=agent-alpha/home
HOMEDRIVE=<agent-alpha 所在盘>
HOMEPATH=<agent-alpha/home 的盘内路径>

XDG_CONFIG_HOME=agent-alpha/config
XDG_CACHE_HOME=agent-alpha/cache
XDG_DATA_HOME=agent-alpha/data
XDG_STATE_HOME=agent-alpha/state

APPDATA=agent-alpha/config/appdata
LOCALAPPDATA=agent-alpha/data/localappdata

TMP=agent-alpha/temp
TEMP=agent-alpha/temp

PIP_CACHE_DIR=agent-alpha/cache/pip
UV_CACHE_DIR=agent-alpha/cache/uv
UV_TOOL_DIR=agent-alpha/tools/uv

PYTHONUSERBASE=agent-alpha/home/.local
PYTHONPYCACHEPREFIX=agent-alpha/cache/python

HF_HOME=agent-alpha/cache/huggingface
TRANSFORMERS_CACHE=agent-alpha/cache/huggingface/transformers

PLAYWRIGHT_BROWSERS_PATH=agent-alpha/cache/playwright

DOTNET_CLI_HOME=agent-alpha/home

CARGO_HOME=agent-alpha/cache/cargo
RUSTUP_HOME=agent-alpha/cache/rustup
```

目标是让大部分“默认写用户目录”的软件优先写入 `agent-alpha` 内部，而不是 `C:\Users\<user>`。

### 2. Skill 本体只能安装到 alpha 内部

skill 文件本体的唯一安装目标：

```text
agent-alpha/skills/<skill-name>
```

不允许把 skill 本体安装到：

```text
~/.claude/skills
~/.codex/skills
~/.openclaw/skills
C:\Users\<user>\...
```

第三方 README 中出现 `.claude`、`.codex`、`.openclaw` 等路径时，只能理解为其他 agent 的安装目标，不能照搬为 alpha 的安装目标。

### 3. 依赖安装允许作为 sandbox 例外

允许以下依赖安装命令产生 alpha 目录外部的副作用：

```text
npm install -g ...
pnpm add -g ...
yarn global add ...
go install ...
pip install ...
python -m pip install ...
uv tool install ...
uv pip install ...
```

其中：

- npm / pnpm / yarn 全局安装可以写入宿主机 Node 全局目录。
- Go 安装可以写入宿主机 Go bin/pkg/cache。
- pip 在 alpha 的 uv 启动环境下，默认应落入 `agent-alpha/.venv`。
- uv 相关命令维持当前行为，不额外强行压进 alpha 目录。

这类命令是明确例外，不代表 AI 可以任意写 alpha 外部文件。

为了保留 npm / go 的宿主全局安装语义，启动 alpha 时不要设置这些变量来强行改写它们的全局目录：

```text
NPM_CONFIG_PREFIX
GOPATH
GOBIN
GOMODCACHE
GOCACHE
```

也就是说：

```text
npm install -g ...
go install ...
```

仍按宿主机自己的规则安装。它们是 sandbox 的明确例外。

pip 不是宿主全局例外。pip 安装必须落入 alpha 的 `.venv`：

```text
agent-alpha/.venv
```

允许：

```text
pip install ...
python -m pip install ...
uv pip install ...
```

但前提是实际使用的是 `agent-alpha/.venv` 中的 Python / pip，或明确绑定到该 `.venv`。不允许系统 Python、conda 环境、用户 site-packages、`pip install --user` 等 alpha 外部 Python 环境安装。

### 4. 普通文件操作不得写 alpha / workspace 外部

sandbox 的基本规则：

```text
alpha 内部运行目录：可读写
当前 workspace：可读写
alpha 内部核心代码 / agent loop / sandbox / 权限系统：默认只读，改动需要确认
alpha 与当前 workspace 之外：可读，但禁止写、删、创建、移动、覆盖
```

这里采用稳妥版：减少普通运行时权限弹窗，但不让 AI 静默修改 alpha 的核心执行逻辑。

需要覆盖：

- 文件工具：write / edit / append
- shell：PowerShell / cmd / Linux shell
- 删除：`Remove-Item`、`rm`、`del`、`rmdir`、`rd`
- 创建：`New-Item`、`mkdir`、重定向写入、`Set-Content`
- 覆盖/追加：`>`、`>>`、`Out-File`、`tee`
- 移动/复制：`Move-Item`、`Copy-Item`、`move`、`copy`、`mv`、`cp`
- 间接写入：脚本、安装器、命令链中的文件操作

普通 shell 命令不能通过 PowerShell/cmd/Linux shell 绕过文件工具权限。

### 5. 写一个“安装 skill 的 skill”

需要新增一个 alpha 自己的 skill，专门教 AI 如何安装 alpha skill。

它不是复杂 installer，而是安装规则说明：

```text
1. skill 本体只放 agent-alpha/skills/<skill-name>
2. README 只用于理解依赖、使用方式和文件结构
3. README 里的 .claude/.codex/.openclaw 路径不能作为 alpha 目标路径
4. npm/go/pip/uv 依赖可以按说明安装
5. 安装后用 alpha 的 load_skill 验证是否能发现和加载
```

这个 skill 用来避免 AI 再把第三方 agent 的路径当成 alpha 的路径。

建议 skill 名称：

```text
install-alpha-skill
```

建议文件位置：

```text
agent-alpha/skills/install-alpha-skill/SKILL.md
```

这个 skill 只需要一个 `SKILL.md`，先不增加脚本、README、reference 或复杂资源。它的作用不是实现 installer，而是给 AI 一个明确的安装规则和路径翻译规则。

#### install-alpha-skill 的元信息设计

`SKILL.md` frontmatter 建议：

```yaml
---
name: install-alpha-skill
description: Install third-party skills into agent-alpha. Use when the user asks to install, inspect, configure, or enable a skill from a local folder, GitHub repository, GitHub subpath, README, or another agent's skill package, while adapting paths and dependency commands to agent-alpha's sandbox and runtime layout.
---
```

description 要覆盖这些触发场景：

- 用户说“安装 skill”
- 用户给 GitHub repo / 子路径
- 用户给本地目录
- 用户给 README / 安装说明
- 用户让 alpha 配置 web-access、Agent-Reach、superpowers 这类非标准 skill
- 用户让 alpha 按其他 agent 的说明安装 skill

#### install-alpha-skill 的主体结构

`SKILL.md` 主体建议分为四段：

```text
1. alpha 运行环境元信息
2. skill 安装目标与来源识别
3. 依赖安装命令改写规则
4. 安装后验证
```

#### 1. alpha 运行环境元信息

这一段要让 AI 先知道 alpha 的“世界观”：

```text
You are installing a skill for agent-alpha.

Do not install the skill body into Claude, Codex, OpenClaw, or any user-level skill directory.
The only target for skill files is:

agent-alpha/skills/<skill-name>

agent-alpha redirects common runtime directories into the project:

HOME=agent-alpha/home
USERPROFILE=agent-alpha/home
XDG_CONFIG_HOME=agent-alpha/config
XDG_CACHE_HOME=agent-alpha/cache
XDG_DATA_HOME=agent-alpha/data
XDG_STATE_HOME=agent-alpha/state
APPDATA=agent-alpha/config/appdata
LOCALAPPDATA=agent-alpha/data/localappdata
TMP=agent-alpha/temp
TEMP=agent-alpha/temp
PIP_CACHE_DIR=agent-alpha/cache/pip
UV_CACHE_DIR=agent-alpha/cache/uv
UV_TOOL_DIR=agent-alpha/tools/uv
PYTHONUSERBASE=agent-alpha/home/.local
PYTHONPYCACHEPREFIX=agent-alpha/cache/python
HF_HOME=agent-alpha/cache/huggingface
TRANSFORMERS_CACHE=agent-alpha/cache/huggingface/transformers
PLAYWRIGHT_BROWSERS_PATH=agent-alpha/cache/playwright
DOTNET_CLI_HOME=agent-alpha/home
CARGO_HOME=agent-alpha/cache/cargo
RUSTUP_HOME=agent-alpha/cache/rustup
```

还要明确可写边界：

```text
Writable without special confirmation:
- current workspace
- agent-alpha/home
- agent-alpha/skills
- agent-alpha/temp
- agent-alpha/cache
- agent-alpha/tools
- agent-alpha/config
- agent-alpha/data
- agent-alpha/state

Read-only unless the user explicitly asks to change agent-alpha itself:
- agent-alpha/agent/core
- agent loop files
- sandbox and permission-system files

Do not create, edit, delete, move, or overwrite ordinary files outside agent-alpha and the current workspace.
npm/go global installs are the only host-global dependency exceptions.
```

#### 2. skill 安装目标与来源识别

这一段要把安装流程写成 checklist：

```text
Workflow:

1. Identify the source:
   - local directory
   - GitHub repository URL
   - GitHub repository subpath

2. If the source is GitHub, clone or download it into:
   agent-alpha/temp/skill-install/<source-name>

3. Read installation documents before copying:
   - README.md
   - INSTALL.md
   - docs explicitly linked by README, if they are local files in the same repository

4. Find SKILL.md candidates:
   - if root has SKILL.md, treat root as one skill
   - if repository has exactly one SKILL.md, install that skill
   - if repository has multiple SKILL.md files, install them as multiple flat skills

5. Choose the skill name:
   - prefer SKILL.md frontmatter name
   - otherwise use the skill directory name
   - for packs, prefix with the pack name if needed to avoid conflicts, such as superpowers-brainstorming

6. Copy the skill body into:
   agent-alpha/skills/<skill-name>

7. Never copy the skill body into:
   ~/.claude/skills
   ~/.codex/skills
   ~/.openclaw/skills
   ~/.agent-alpha/skills
   C:\Users\<user>\...
```

路径翻译规则要写得非常硬：

```text
When a third-party README says to install into another agent path, translate only the target path.

Example:

README says:
~/.claude/skills/agent-reach

agent-alpha target:
agent-alpha/skills/agent-reach

README says:
mkdir -p ~/.codex/skills/foo
cp -r . ~/.codex/skills/foo

agent-alpha action:
copy the same skill files into agent-alpha/skills/foo
```

#### 3. 依赖安装命令改写规则

这一段要告诉 AI：README 要参考，但命令必须按 alpha 改写。

Python / pip：

```text
Python dependencies must install into agent-alpha/.venv.

Prefer:

Windows:
agent-alpha/.venv/Scripts/python.exe -m pip install <packages>

Linux/macOS:
agent-alpha/.venv/bin/python -m pip install <packages>

Allowed only if it resolves to agent-alpha/.venv:
pip install <packages>
python -m pip install <packages>
uv pip install <packages>

Forbidden:
pip install --user <packages>
system Python pip
conda pip
installing into user site-packages
installing into another project's virtualenv
```

uv tool：

```text
uv tool install ... may be used when README asks to install a Python CLI tool.
Use alpha's runtime environment variables and cache directories.
Do not rewrite uv tool install into npm/go/global tools.
```

npm / pnpm / yarn：

```text
npm install -g ...
pnpm add -g ...
yarn global add ...

These are host-global dependency exceptions.
Keep their global install meaning.
Do not force npm global tools into agent-alpha/tools.
Do not set NPM_CONFIG_PREFIX for this purpose.
```

Go：

```text
go install ...

This is a host-global dependency exception.
Keep Go's normal host behavior.
Do not force GOPATH, GOBIN, GOMODCACHE, or GOCACHE into agent-alpha.
```

Shell profile / env 配置：

```text
If README asks to edit:
- ~/.bashrc
- ~/.zshrc
- PowerShell profile
- system environment variables
- shell profile files under C:\Users\<user>

do not edit those files directly.
Use agent-alpha's runtime env profile or current configuration mechanism instead, if available.
If no alpha-local configuration mechanism exists yet, report the required env vars as follow-up work.
```

脚本安装：

```text
Do not blindly run install.ps1, install.sh, setup.sh, or similar installer scripts as a sandbox exception.
Read them first when possible.
If they only invoke allowed dependency commands, run or reproduce those commands.
If they create, edit, delete, move, or overwrite ordinary files outside agent-alpha or the current workspace, do not run them as-is.
```

#### 4. 安装后验证

验证流程：

```text
1. Use load_skill <skill-name>.
2. Confirm the loaded skill content matches the installed skill.
3. If README provides a smoke test, run it without asking the user.
4. If the smoke test requires credentials, accounts, paid services, or external side effects, only run the local non-destructive parts and report what remains.
```

安装结果摘要：

```text
After installation, report:
- source
- installed skill name(s)
- target path(s)
- dependency commands run
- load_skill result
- smoke test result, if any
- anything skipped because it would violate alpha's path rules
```

skill 来源先只支持三类：

```text
本地目录
GitHub 仓库链接
GitHub 仓库子路径
```

处理方式：

- AI 可以先把 GitHub 来源拉取到 `agent-alpha/temp/skill-install/...`。
- 如果根目录有 `SKILL.md`，安装为单个 skill。
- 如果仓库内只有一个 `SKILL.md`，安装该 skill。
- 如果仓库内有多个 `SKILL.md`，按多个 skill 文件夹扁平安装。
- 多 skill pack 先不做复杂 namespace / plugin 系统，例如可以安装为 `superpowers-brainstorming`、`superpowers-systematic-debugging` 这类普通 skill 文件夹。
- README 中的 `.claude`、`.codex`、`.openclaw`、`C:\Users\<user>` 等路径只能作为来源项目的说明，不能作为 alpha 目标路径。

## 关键边界

最终边界可以概括为：

```text
alpha 的运行文件世界在 agent-alpha 内部；
当前 workspace 也允许读写；
skill 本体只能进 agent-alpha/skills；
普通软件 home/config/cache/temp 默认导向 agent-alpha 内部；
npm/go 全局安装保留宿主全局行为；
AI 不能直接把普通文件写到 alpha 与当前 workspace 之外。
```

## 已对齐问题

1. 环境变量范围
   - 需要补充常见工具变量：Python 用户目录与 pycache、HuggingFace、Transformers、Playwright 浏览器缓存、.NET CLI、Cargo、Rustup。
   - npm / go 是明确例外，不改写它们的宿主全局目录。

2. sandbox 对依赖安装例外的识别
   - 只按明确命令前缀识别，例如 `npm install -g`、`go install`、`pip install`、`uv tool install`。
   - 不整体放行 `install.ps1`、`install.sh` 这类脚本；脚本内部如果写 alpha / workspace 外部，仍应被拦截。

3. alpha 内部可写范围
   - 采用稳妥版。
   - `agent-alpha/home`、`agent-alpha/skills`、`agent-alpha/temp`、`agent-alpha/cache`、`agent-alpha/tools`、`agent-alpha/config`、`agent-alpha/data`、`agent-alpha/state` 等运行目录可写。
   - `agent-alpha/agent/core`、agent loop、sandbox、权限系统等核心路径默认只读，修改需要确认。
   - 当前 workspace 允许读写。

4. skill 安装方式
   - 不做复杂 installer。
   - 新增一个 alpha 自己的“安装 skill 的 skill”，让 AI 按这个 skill 的规则安装。
   - 安装目标只允许 `agent-alpha/skills/<skill-name>`。

5. 旧错误路径
   - 不迁移。
   - 曾经安装到 `~/.agent-alpha/skills`、`.claude/skills` 等旧路径的内容由用户自行清理。

6. Docker
   - 不使用 Docker。

7. `pip install`
   - 强制使用 alpha `.venv`。
   - 不允许系统 Python、conda 环境、用户 site-packages、`pip install --user`。

8. skill 安装来源
   - 支持本地目录、GitHub 仓库链接、GitHub 仓库子路径。
   - 完全采用“安装 skill 的 skill + 文件工具复制”的方式。
   - 不做复杂 installer。

9. 外部读取
   - 不考虑信息安全读取限制。
   - alpha 可以读取外部文件。

10. session log 是否继续如实记录 token？
   - 之前已确认 log 是本地文件，可以如实记录。
   - 但如果未来允许读取外部文件，要不要避免把外部敏感文件内容写入长期 log？

11. 安装后验证
   - 默认只要求 `load_skill <name>` 能加载。
   - 如果 README 明确提供 smoke test，由 AI 自行执行，不需要再询问用户。

## 仍待讨论问题

暂无。
