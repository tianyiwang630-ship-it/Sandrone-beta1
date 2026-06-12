# agent-alpha 运行时环境与 Skill 安装管理设计

日期：2026-05-26

## 1. 设计背景

agent-alpha 需要支持类似 Agent-Reach 这样的 CLI 工具型 skill。

这类 skill 往往不是单个 Markdown 文件就能工作，而是需要安装 Python、Node.js 或 Go 相关依赖。例如：

- Python CLI 工具可能需要 `uv` 或 `pip` 安装。
- Node.js CLI 工具可能需要 `npm` 安装。
- Go CLI 工具可能需要 `go install`。

但 agent-alpha 不能直接让 skill 自己随意执行这些安装命令，因为那样可能污染用户电脑的系统环境。

因此本设计把问题拆成两个部分：

1. 运行时环境管理：agent-alpha 如何安全地管理 Python、Node.js、Go 依赖。
2. skill 安装与加载管理：agent-alpha 如何安装、记录、加载和调用 skill。

## 2. 已确认边界

### 2.1 不允许改用户电脑环境

agent-alpha 不能默认修改：

- 用户系统 Python 环境
- 用户系统 npm 全局目录
- 用户系统 GOPATH
- 用户系统 PATH
- 用户系统级配置文件

### 2.2 “全局依赖”的真实含义

本设计里的“全局依赖”不是用户电脑全局依赖。

它的意思是：

> agent-alpha 托管全局依赖。

也就是写入 agent-alpha 自己管理的运行时目录，例如：

```text
agent-alpha/.runtime/
```

### 2.3 依赖不能由 skill 随意安装

认可的原则是：

> 用户或 skill 可以声明“我要装什么”，但具体怎么装、装到哪里，由 agent-alpha 的 RuntimeManager 决定。

这能避免 skill 偷偷把依赖安装到用户电脑系统环境里。

## 3. agent-alpha 当前现状

当前 agent-alpha 的项目状态：

- Python 依赖文件是 `agent-alpha/requirements.txt`。
- 暂时没有 `pyproject.toml` 和 `uv.lock`。
- 暂时没有项目级 `package.json`，说明 agent-alpha 本体当前没有必须安装的 Node.js 依赖。
- CLI 入口在 `agent-alpha/agent/cli/main.py`，当前可通过 `python -m agent.cli.main` 运行。
- 当前 `SkillLoader` 只扫描 `agent-alpha/skills/**/SKILL.md`。
- 当前 skill 加载偏向文档型加载：先给 AI 看 skill 摘要，需要时再通过 `load_skill(name)` 读取完整内容。

因此 V1 不需要一上来重做所有工程结构。

V1 的重点是：

```text
启动脚本自动准备 agent-alpha 的托管 Python 环境
RuntimeManager 管理受控运行时目录
SkillManager 支持安装型 skill
现有 SkillLoader 继续兼容本地 SKILL.md
```

## 4. 第一版目标

第一版先解决“能装”的问题，不追求完整 skill 市场。

### 4.1 第一版要支持

- 启动 agent-alpha 时自动准备 `.runtime/python/.venv`。
- 根据 `requirements.txt` 自动安装 agent-alpha 本体 Python 依赖。
- 在 CLI 中使用托管 Python 环境运行 agent-alpha。
- 从 GitHub 仓库或本地目录安装 skill。
- 兼容文档型、多 SKILL.md 包型、CLI 型、脚本型、MCP 型 skill。
- 读取 skill 的依赖声明和入口声明。
- 根据依赖声明安装 Python、Node.js、Go 工具或依赖。
- 把依赖安装到 agent-alpha 托管目录或项目级目录。
- 写入安装记录。
- 让现有 agent-alpha 能加载已安装 skill。

### 4.2 第一版暂不重点做

- 完整 skill 商店。
- 复杂版本冲突解决。
- 多版本并存策略。
- 自动更新策略。
- 完整权限沙箱。
- 跨设备同步。
- 复杂 GUI 管理界面。

这些可以后续迭代。

## 5. 运行时环境设计

### 5.1 目录结构

agent-alpha 托管运行时目录：

```text
agent-alpha/
  .runtime/
    bootstrap/
      uv/
      node/
      go/
    python/
      .venv/
    uv/
      bin/
      tools/
      pythons/
      cache/
    node/
      runtime/
      prefix/
      cache/
    go/
      runtime/
      bin/
      pkg/
      cache/
    skills/
      installed/
      cache/
      lock.json
```

项目级目录：

```text
some-user-project/
  .venv/
  node_modules/
  .agent-tools/
    go/
      bin/
      pkg/
      cache/
```

### 5.2 依赖作用域

| 类型 | agent-alpha 托管全局 | 项目级 |
| --- | --- | --- |
| agent-alpha 本体 Python | `.runtime/python/.venv/` | 不适用 |
| Python | `.runtime/uv/tools/` | 项目 `.venv/` |
| Node.js | `.runtime/node/prefix/` | 项目 `node_modules/` |
| Go | `.runtime/go/bin/` | 项目 `.agent-tools/go/bin/` |

### 5.3 agent-alpha 本体 Python 管理

V1 应该让 agent-alpha 本体也运行在托管 Python 环境中。

启动时：

```text
1. 启动脚本检查 uv。
2. 如果系统已有 uv，借用系统 uv。
3. 如果没有 uv，下载 uv 到 .runtime/bootstrap/uv/。
4. 使用 uv 创建 .runtime/python/.venv。
5. 根据 agent-alpha/requirements.txt 安装依赖。
6. 使用 .runtime/python/.venv/Scripts/python.exe 或 .runtime/python/.venv/bin/python 启动 agent-alpha CLI。
```

当前 agent-alpha 没有 `pyproject.toml` 和 `uv.lock`，所以 V1 可以先使用：

```bash
uv venv agent-alpha/.runtime/python/.venv
uv pip install --python agent-alpha/.runtime/python/.venv -r agent-alpha/requirements.txt
```

后续再升级为：

```text
pyproject.toml + uv.lock + uv sync --locked
```

这样依赖更可复现。

### 5.4 skill Python 管理

Python 第一版建议使用 `uv` 作为默认管理工具。

原则：

- 不直接使用系统 `pip install` 修改系统 Python。
- agent 级 Python CLI 工具使用 `uv tool install`。
- 项目级 Python 依赖使用项目 `.venv`。
- 如果未来需要新 Python 版本，由 `uv` 管理，不要求用户手动改系统 Python。
- 调用 `uv` 时必须显式设置 agent-alpha 托管目录，不能依赖 uv 默认目录。

agent 级 Python 工具安装时建议设置：

```bash
UV_TOOL_DIR=agent-alpha/.runtime/uv/tools
UV_TOOL_BIN_DIR=agent-alpha/.runtime/uv/bin
UV_CACHE_DIR=agent-alpha/.runtime/uv/cache
UV_PYTHON_INSTALL_DIR=agent-alpha/.runtime/uv/pythons
uv tool install <package>
```

示例：

```text
skill 声明需要 Python CLI 工具
  -> RuntimeManager 判断作用域是 agent
  -> PythonInstaller 设置 UV_TOOL_DIR/UV_TOOL_BIN_DIR 后使用 uv tool install
  -> 工具进入 agent-alpha/.runtime/uv/tools/
  -> 可执行入口进入 agent-alpha/.runtime/uv/bin/
```

### 5.5 Node.js 管理

Node.js 第一版只支持 `npm`，不急着同时支持 pnpm、yarn、bun。

原则：

- 不使用系统 `npm install -g`。
- agent 级 Node CLI 工具使用 agent-alpha 自己的 npm prefix。
- 项目级 Node 依赖安装到项目自己的 `node_modules`。

agent 级安装形式：

```bash
npm install -g --prefix agent-alpha/.runtime/node/prefix <package>
```

调用时，agent-alpha 临时把下面路径加入当前进程 PATH：

```text
macOS/Linux: agent-alpha/.runtime/node/prefix/bin
Windows:     agent-alpha/.runtime/node/prefix
```

这个 PATH 只对 agent-alpha 进程有效，不写入用户系统 PATH。

如果系统没有 Node.js / npm，后续由启动脚本下载 Node.js 到：

```text
agent-alpha/.runtime/node/runtime/
```

如果 agent-alpha 本体未来出现前端或 Node.js 项目依赖，则本体依赖和 skill CLI 依赖要分开：

```text
agent-alpha 本体 Node 依赖 -> 对应项目目录的 node_modules
skill 的 Node CLI 依赖 -> .runtime/node/prefix/
```

当前 agent-alpha 未发现 `package.json`，所以 V1 启动脚本不需要默认执行 `npm install`。

### 5.6 Go 管理

Go 第一版支持 agent 级和项目级工具安装。

agent 级安装时，设置：

```bash
GOBIN=agent-alpha/.runtime/go/bin
GOMODCACHE=agent-alpha/.runtime/go/pkg
GOCACHE=agent-alpha/.runtime/go/cache
go install <package>
```

Go 的 `<package>` 第一版要求使用明确版本，例如：

```text
github.com/example/tool@latest
github.com/example/tool@v1.2.3
```

如果用户或 skill 没写版本，agent-alpha 可以第一版先补成 `@latest`，并在 lock.json 里记录实际安装请求。

项目级安装时，设置：

```bash
GOBIN=<project>/.agent-tools/go/bin
GOMODCACHE=<project>/.agent-tools/go/pkg
GOCACHE=<project>/.agent-tools/go/cache
go install <package>
```

如果系统没有 Go，后续由启动脚本下载 Go 到：

```text
agent-alpha/.runtime/go/runtime/
```

## 6. 启动脚本设计

V1 需要新增启动脚本，让用户不再手动执行：

```bash
pip install -r requirements.txt
```

用户预期只需要执行：

```text
Windows: start-agent-alpha.ps1 或 start-agent-alpha.bat
macOS/Linux: ./start-agent-alpha.sh
```

启动脚本职责：

```text
1. 定位 agent-alpha 项目根目录。
2. 确保 .runtime/ 目录存在。
3. 检查 uv 是否可用。
4. 如果 uv 不存在，下载 uv 到 .runtime/bootstrap/uv/。
5. 用 uv 创建或复用 .runtime/python/.venv。
6. 根据 requirements.txt 安装或更新 Python 依赖。
7. 用托管 venv 里的 python 启动 agent.cli.main。
```

### 6.1 Windows 启动命令

建议主入口：

```powershell
.\start-agent-alpha.ps1
```

脚本最后执行：

```powershell
agent-alpha\.runtime\python\.venv\Scripts\python.exe -m agent.cli.main
```

执行目录应该是：

```text
agent-alpha/
```

这样 Python import 能正常找到 `agent` 包。

### 6.2 依赖更新策略

V1 可以采用简单策略：

```text
每次启动都执行一次 uv pip install -r requirements.txt
```

这会稍慢一点，但简单可靠。

后续可以优化为：

```text
记录 requirements.txt 的 hash
没变化就跳过安装
变化才重新同步
```

### 6.3 启动脚本和 Node.js / Go

当前 agent-alpha 本体没有 Node.js 和 Go 依赖，所以启动脚本 V1 不需要默认安装 Node.js / Go。

但 RuntimeManager 和 SkillManager 要预留：

```text
skill 需要 npm 时 -> 检查 node/npm，缺少则引导下载到 .runtime/node/runtime/
skill 需要 go 时 -> 检查 go，缺少则引导下载到 .runtime/go/runtime/
```

## 7. RuntimeManager 设计

RuntimeManager 是 agent-alpha 的运行时环境总管。

它不负责理解 skill 内容，只负责回答这些问题：

- agent-alpha 的运行时目录在哪里？
- 当前项目级目录在哪里？
- Python、Node.js、Go 的工具应该安装到哪里？
- 执行某个 skill 时需要临时注入哪些 PATH 和环境变量？
- 当前机器是否具备 uv、npm、go 这些基础工具？

### 7.1 RuntimeManager 的职责

```text
ensure_runtime_dirs()
detect_tools()
ensure_uv()
ensure_node()
ensure_go()
build_agent_env()
build_project_env(project_path)
resolve_install_target(language, scope)
```

### 7.2 基础工具缺失时

V1 对 uv 的要求更高，因为 agent-alpha 本体 Python 环境也由 uv 托管。

建议行为：

```text
如果缺 uv：
  下载 uv 到 .runtime/bootstrap/uv/。

如果缺 npm：
  当前 agent-alpha 本体不需要 npm，可以暂不处理；
  如果安装 Node.js skill 时需要 npm，再下载 Node.js 到 .runtime/node/runtime/。

如果缺 go：
  当前 agent-alpha 本体不需要 go，可以暂不处理；
  如果安装 Go skill 时需要 go，再下载 Go 到 .runtime/go/runtime/。
```

注意：即使系统里存在 uv、npm、go，agent-alpha 也只借用这些可执行程序本身，不使用它们的系统级全局安装目录。

## 8. Installer 设计

Installer 负责真正执行安装，但它必须接受 RuntimeManager 给出的受控目录。

第一版建议三个安装器：

```text
PythonInstaller
NodeInstaller
GoInstaller
```

### 8.1 PythonInstaller

支持：

```text
uv tool install <package>
uv venv
uv pip install <package>
```

第一版优先支持 CLI 工具安装：

```text
scope = agent -> uv tool install
scope = project -> uv pip install 到项目 .venv
```

agent 级安装必须设置：

```text
UV_TOOL_DIR
UV_TOOL_BIN_DIR
UV_CACHE_DIR
UV_PYTHON_INSTALL_DIR
```

这样 Python CLI 工具和缓存都留在 agent-alpha 托管目录里。

### 8.2 NodeInstaller

支持：

```text
scope = agent -> npm install -g --prefix .runtime/node/prefix <package>
scope = project -> npm install <package>
```

第一版重点是 agent 级 CLI 工具安装。

### 8.3 GoInstaller

支持：

```text
scope = agent -> 设置 GOBIN 到 .runtime/go/bin 后 go install
scope = project -> 设置 GOBIN 到项目 .agent-tools/go/bin 后 go install
```

## 9. Skill 管理设计

### 9.1 第一版 SkillManager 目标

第一版 SkillManager 只需要做到：

```text
install_skill(source)
list_skills()
load_skill(name)
enable_skill(name)
disable_skill(name)
remove_skill(name)
```

其中最核心的是 `install_skill(source)`。

### 9.2 第一版支持的 skill 类型

V1 不能只支持 CLI 型 skill。

建议先按以下类型建模：

| 类型 | 说明 | 是否需要依赖安装 |
| --- | --- | --- |
| docs | 一个或多个 `SKILL.md`，只提供说明和工作流 | 通常不需要 |
| bundle | 一个仓库或目录里包含多个具体 skill | 通常不需要，也可能有资源 |
| cli | 安装后提供命令行入口 | 通常需要 Python/Node/Go |
| script | 入口是 Python/Node/shell 脚本 | 可能需要依赖 |
| mcp | 安装后作为 MCP server 启动 | 通常需要依赖和配置 |
| assets | 主要提供模板、素材、参考文件 | 通常不需要 |

类似 superpowers 的 skill 包更接近：

```text
bundle + docs
```

类似 Agent-Reach 更接近：

```text
cli
```

### 9.3 skill 安装流程

用户输入：

```text
安装 Panniantong/Agent-Reach.git
```

agent-alpha 执行：

```text
1. 下载或复制 skill 到 .runtime/skills/cache/
2. 读取 skill manifest
3. 判断 skill 需要哪些依赖
4. RuntimeManager 决定每个依赖的安装目录
5. Installer 执行受控安装
6. 写入 .runtime/skills/lock.json
7. 把 skill 注册为可加载状态
```

### 9.4 skill 加载流程

```text
1. ToolLoader 或 SkillLoader 请求加载 skill
2. SkillManager 查询 lock.json
3. 确认 skill 已安装且启用
4. 读取 skill 的说明文档和入口信息
5. 返回给 agent 使用
```

文档型和 bundle 型 skill 没有命令调用步骤。

它们的核心是：

```text
安装到 .runtime/skills/installed/
扫描其中的 SKILL.md
加入 SkillLoader 的可加载清单
AI 需要时通过 load_skill(name) 读取
```

CLI、script、MCP 型 skill 才需要 RuntimeManager 构造执行环境。

### 9.5 skill 调用流程

CLI 型 skill 调用时：

```text
1. SkillManager 找到 skill entry
2. RuntimeManager 构造受控环境变量
3. 在当前项目工作区执行命令
4. 捕获 stdout、stderr、退出码
5. 返回给 agent
```

## 10. Skill Manifest 设计

第一版 manifest 不需要复杂，但必须能声明依赖。

建议格式：

```yaml
name: agent-reach
description: Agent-Reach CLI skill
source: github:Panniantong/Agent-Reach
version: main

runtime:
  node:
    scope: agent
    packages:
      - agent-reach
  python:
    scope: none
  go:
    scope: none

entry:
  type: cli
  command: agent-reach

permissions:
  network: ask
  filesystem: workspace
```

文档型或 bundle 型 skill 可以更简单：

```yaml
name: superpowers
description: Workflow skill bundle
type: bundle

skills:
  discovery:
    - "**/SKILL.md"

runtime:
  python:
    scope: none
  node:
    scope: none
  go:
    scope: none
```

如果没有 manifest，V1 可以提供自动识别：

```text
如果仓库/目录里有多个 SKILL.md -> 按 bundle/docs 处理
如果只有一个 SKILL.md -> 按 docs 处理
如果 manifest 声明 entry -> 按 cli/script/mcp 处理
```

### 10.1 scope 取值

```text
agent   -> 安装到 agent-alpha 托管全局环境
project -> 安装到当前项目环境
none    -> 不需要这种运行时
```

### 10.2 entry 取值

第一版先支持：

```text
type: cli
command: <command-name>
```

后续可以扩展：

```text
type: mcp
type: python_module
type: node_script
```

## 11. lock.json 设计

安装成功后写入：

```json
{
  "agent-reach": {
    "name": "agent-reach",
    "source": "github:Panniantong/Agent-Reach",
    "version": "main",
    "commit": "unknown",
    "enabled": true,
    "installed_at": "2026-05-26T00:00:00+08:00",
    "runtime": {
      "node": {
        "scope": "agent",
        "packages": ["agent-reach"]
      }
    },
    "entry": {
      "type": "cli",
      "command": "agent-reach"
    }
  }
}
```

第一版 lock.json 的重点不是完美版本解析，而是让 agent-alpha 知道：

- 装过什么 skill
- 来源是什么
- 依赖装在哪里
- 入口命令是什么
- 当前是否启用

## 12. 与现有 agent-alpha 的关系

现有 agent-alpha 已有 SkillLoader / ToolLoader。

第一版不建议直接推翻，而是增加一层：

```text
现有 SkillLoader
  + 本地 skills 目录扫描
  + 新增：读取 SkillManager 已安装 skill
```

也就是说：

```text
旧的本地 SKILL.md 继续可用
新的安装型 skill 走 SkillManager
```

这样改动范围更小，也更容易验证。

V1 接入方式建议：

```text
SkillManager 管 .runtime/skills/installed/
SkillLoader 支持多个 skill 根目录：
  - agent-alpha/skills/
  - agent-alpha/.runtime/skills/installed/
```

这样 superpowers 这类多 SKILL.md 包安装后，也能被现有 `load_skill(name)` 使用。

## 13. 第一版实施顺序

### 阶段 1：启动脚本和托管 Python

目标：

- 新增启动脚本。
- 检查或下载 uv。
- 创建 `.runtime/python/.venv`。
- 根据 `requirements.txt` 安装 Python 依赖。
- 用托管 Python 启动 `agent.cli.main`。

### 阶段 2：RuntimeManager

目标：

- 创建 `.runtime/` 目录结构。
- 识别 agent 级和项目级安装路径。
- 构造受控 PATH 和环境变量。
- 检测 uv、npm、go 是否可用。

### 阶段 3：Installer

目标：

- PythonInstaller 支持 uv。
- NodeInstaller 支持 npm prefix。
- GoInstaller 支持 GOBIN/GOMODCACHE/GOCACHE。

### 阶段 4：SkillManager

目标：

- 支持从 GitHub 或本地路径安装 skill。
- 读取 manifest。
- 没有 manifest 时自动识别 docs/bundle 型 skill。
- 调用 RuntimeManager 和 Installer。
- 写入 lock.json。

### 阶段 5：接入现有加载机制

目标：

- ToolLoader / SkillLoader 能看到已安装 skill。
- CLI 型 skill 能被 agent 调用。
- docs/bundle 型 skill 能通过 load_skill 使用。

## 14. 成功标准

第一版成功标准：

```text
执行 agent-alpha 启动脚本
agent-alpha 可以：
  1. 自动准备 .runtime/python/.venv
  2. 自动安装 requirements.txt 里的依赖
  3. 使用托管 Python 进入 CLI

给 agent-alpha 一个类似 superpowers 的多 SKILL.md 包
agent-alpha 可以：
  1. 安装到 .runtime/skills/installed/
  2. 扫描多个 SKILL.md
  3. 在 CLI 里通过 load_skill 读取具体 skill

给 agent-alpha 一个类似 Panniantong/Agent-Reach.git 的 CLI skill 来源
agent-alpha 可以：
  1. 下载或复制 skill
  2. 读取依赖声明
  3. 安装 CLI 依赖到 .runtime/
  4. 写入 lock.json
  5. 在后续会话中识别这个 skill
  6. 调用这个 skill 的入口命令
```

不要求第一版做到：

```text
完整商店
自动更新
复杂权限系统
完美依赖冲突解决
```

## 15. 风险与取舍

### 15.1 为什么不让 skill 直接执行安装命令

因为这样无法保证安装目标，可能污染用户电脑环境。

例如：

```bash
pip install xxx
npm install -g xxx
go install xxx
```

这些命令如果直接执行，可能写入系统环境。

### 15.2 为什么 V1 自动处理 uv，但不默认处理 Node.js / Go

因为当前 agent-alpha 本体需要 Python 依赖，所以 uv 是启动链路的一部分。

但当前 agent-alpha 本体没有 Node.js / Go 依赖，所以 Node.js 和 Go 可以在安装相关 skill 时再处理。

自动安装 Node.js / Go 本体会引入更多复杂度：

- 下载源选择
- 平台差异
- 校验
- 失败回滚
- 用户确认

因此 V1 可以：

```text
uv -> 启动时必须确保可用
Node.js -> 安装 Node skill 时确保可用
Go -> 安装 Go skill 时确保可用
```

### 15.3 为什么保留现有 SkillLoader

现有 SkillLoader 已能加载本地 SKILL.md。

第一版目标是补足“安装型 skill”，不是重写所有 skill 系统。

保留旧机制可以降低风险。

## 16. 结论

agent-alpha 第一版应该采用：

> RuntimeManager 统一决定依赖安装位置，SkillManager 只处理 skill 生命周期，Installer 只执行受控安装。

这能同时满足：

- skill 可以安装依赖。
- 不污染用户电脑环境。
- 支持 Python、Node.js、Go。
- 支持 agent 托管全局依赖和项目级依赖。
- 为后续 skill 更新、删除、权限、市场打基础。
