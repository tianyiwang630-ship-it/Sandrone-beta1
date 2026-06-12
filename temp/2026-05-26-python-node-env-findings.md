# Python / Node 环境管理研究发现

日期：2026-05-26

## 概念判断

用户理解大体正确：

- Agent 运行中确实会遇到 Python 与 Node 两类依赖。
- Python 不只是“一个版本够不够”，还要区分 agent 自身运行环境、skill/tool 依赖、一次性任务依赖。
- Node 依赖也要区分全局 CLI、项目级 `node_modules`、临时执行或会话级路径。
- 运行时设计需要考虑依赖安装位置、PATH 暴露、隔离、更新、卸载和安全审批。

## OpenClaw

- OpenClaw 本体是 Node/TypeScript 项目，不是 Python agent runtime。
- OpenClaw 的 skill install spec 支持：`brew`、`node`、`go`、`uv`、`download`。
- `node` installer 使用全局安装：
  - npm: `npm install -g --ignore-scripts <package>`
  - pnpm: `pnpm add -g --ignore-scripts <package>`
  - yarn: `yarn global add --ignore-scripts <package>`
  - bun: `bun add -g --ignore-scripts <package>`
- Node manager 由配置 `skills.install.nodeManager` 决定，可选 `npm` / `pnpm` / `yarn` / `bun`，默认 `npm`。
- OpenClaw 没有看到自己管理 Node 安装目录；它调用现有 npm/pnpm/yarn/bun 的全局安装机制。
- `download` 类型依赖会放到每个 skill 独立的 tools 目录：`resolveConfigDir()/tools/<safe-skill-key>`。
- OpenClaw 的 Python 依赖不是通过 pip/venv 管理；它支持 `uv tool install <package>`，更像“装一个 Python CLI 工具”。
- 如果缺 `uv`，OpenClaw 可尝试用 brew 安装 uv；如果缺 go，可用 brew/apt 安装。
- OpenClaw skill watch 默认忽略 `node_modules`、`.venv`、`venv` 等目录。
- OpenClaw 会 bootstrap PATH：加入 brew、mise shims、pnpm、bun、yarn、`~/.local/bin` 等常见位置；项目本地 `node_modules/.bin` 默认不放前面，需显式允许。

## Hermes

- Hermes 本体是 Python 项目，安装脚本强依赖 uv。
- Windows installer 会安装/定位 uv，并用 `uv python find/install <version>` 管理 Python 版本。
- Windows installer 创建/使用 `$InstallDir\venv`，并用 `UV_PROJECT_ENVIRONMENT` 锁定 uv sync 目标，避免依赖落到错误的 sibling `.venv`。
- POSIX installer 对主包优先走 `uv sync --extra all --locked`，失败后用 `uv pip install` 分层 fallback。
- Hermes doctor 检查 Python 版本，3.10+ required / 3.11+ recommended；检查是否在 virtualenv。
- Hermes 对 Node 有明确的 Hermes-managed 目录：`$HERMES_HOME/node`。
- POSIX installer 如果系统有 node 就用系统 node；否则下载 Node 22 LTS 到 `$HERMES_HOME/node`，并软链 `node/npm/npx` 到 `~/.local/bin`，PATH 前置 `$HERMES_HOME/node/bin`。
- Windows installer 用 npm 的 `--prefix $HermesHome\node` 把 `agent-browser` 等装到 Hermes 自己的 node prefix。
- Hermes 安装项目级 Node 依赖时，在 `$INSTALL_DIR` 下跑 `npm install`，也就是项目级 `node_modules`。
- Hermes browser 工具依赖使用 `npm install -g --prefix "$HERMES_HOME/node"`，不是系统全局 npm 目录。
- Hermes skill hub 本身不自动跑 skill 内的 `pip install` / `npm install`；一些 skill 自带 setup.sh 或文档提示依赖安装。
