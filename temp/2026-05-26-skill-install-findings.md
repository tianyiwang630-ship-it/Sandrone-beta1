# 2026-05-26 Skill 安装机制研究发现

本文件记录源码阅读过程中的关键发现，最终会汇总到正式报告。

## 初始定位

- openclaw 的 skill 核心文件集中在 `learning proj/openclaw/src/agents/skills*.ts` 和 `learning proj/openclaw/src/agents/skills/`。
- openclaw 有明确的安装相关实现：`skills-install.ts`、`skills-install-download.ts`、`skills-install-extract.ts`、`skills-status.ts`。
- hermes agent 的 skill 管理核心集中在 `learning proj/hermes-agent/hermes_cli/skills_hub.py`、`skills_config.py`、`agent/skill_bundles.py`、`agent/skill_utils.py`、`agent/skill_commands.py`。
- agent-alpha 当前对应入口集中在 `agent/core/skill_loader.py`、`agent/core/tool_loader.py`、`agent/tools/bash_tool.py`、`agent/core/sandbox_guard.py`、`agent/core/command_path_extractor.py`。

## openclaw 初步发现

- `openclaw skills list/info/check` 是诊断入口，不是完整的技能包下载器；CLI 输出提示使用 `npx clawhub` 搜索、安装和同步技能。
- OpenClaw 本体支持从已存在的 skill metadata 里读取 `install` 规格，并执行 `brew`、`node`、`go`、`uv`、`download` 五类安装器。
- `node` 安装命令会用配置里的 `nodeManager`，默认 npm，执行类似 `npm install -g --ignore-scripts <package>`。
- `download` 安装会下载到每个 skill 自己的 tools 目录，并限制 targetDir 不可逃逸。
- OpenClaw 加载 skill 的来源有 workspace `skills/`、workspace `.agents/skills`、用户 `~/.agents/skills`、托管 `~/.openclaw/skills`、bundled skills、extraDirs、plugin skills，并有明确优先级。

## hermes 初步发现

- Hermes 有完整的 Skills Hub：搜索、浏览、安装、检查更新、更新、卸载、审计、tap、快照导入导出。
- Hermes 安装流程是 fetch bundle -> quarantine -> security scan -> confirm -> move into `~/.hermes/skills` -> 写 `~/.hermes/skills/.hub/lock.json`。
- Hermes 支持 GitHub 仓库 skill 目录、官方 optional-skills、skills.sh、ClawHub、Claude Marketplace、LobeHub、browse.sh、直接 URL 等来源。
- Hermes 能通过 `tap add owner/repo` 增加自定义 GitHub 仓库源。
- Hermes 的依赖多写在 `SKILL.md` 的 `dependencies`、`prerequisites`、正文命令、`requirements.txt` 中；当前看到的 hub install 代码本身不自动执行 pip/npm 依赖安装。
