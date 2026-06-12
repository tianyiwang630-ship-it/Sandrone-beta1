# Progress

## 2026-04-11

- 已确认边界：静态读代码，不跑项目，输出详细分析文档。
- 已加载并遵循 `using-superpowers`、`planning-with-files`，并参考 `brainstorming` 的结构化思路。
- 已建立本次研究的磁盘工作记忆文件。
- 下一步：并行读取两边的 README、入口、与 agent/multi-agent/workspace/gateway 相关代码。
- 已完成第一轮全局关键词扫描，确认两边风格差异：
  - `openclaw` 偏产品化 runtime / gateway / session system
  - `learn-claude-code` 偏按 session 分章演进的教学实现
- 已读 `openclaw` 第一批关键文件：
  - `src/cli/program/build-program.ts`
  - `src/cli/program/register.agent.ts`
  - `src/cli/gateway-cli/run-loop.ts`
  - `src/agents/subagent-registry.ts`
- 已读第二批关键文件：
  - `openclaw/src/agents/subagent-spawn.ts`
  - `openclaw/src/agents/workspace.ts`
  - `openclaw/src/agents/tools/sessions-spawn-tool.ts`
  - `openclaw/src/routing/resolve-route.ts`
  - `learn-claude-code/agents/s04_subagent.py`
  - `learn-claude-code/agents/s07_task_system.py`
  - `learn-claude-code/agents/s09_agent_teams.py`
  - `learn-claude-code/agents/s12_worktree_task_isolation.py`
- 已补读长期运行与 capstone 相关文件：
  - `learn-claude-code/agents/s11_autonomous_agents.py`
  - `learn-claude-code/agents/s_full.py`
  - `openclaw/src/auto-reply/reply/commands-subagents/action-spawn.ts`
  - `openclaw/src/infra/heartbeat-runner.ts`
  - `openclaw/src/cron/isolated-agent/run.ts`
  - `openclaw/src/cli/gateway-cli/run.ts`
  - `learn-claude-code/README.md`
- 已输出正式报告：
  - `temp/改进方向/openclaw-learn-claude-code-多agent机制分析.md`
- 已做落盘检查：文件存在，主章节完整。

## 2026-04-13

- 已与用户确认本轮边界：以 `Anthropic` 官方文档为主，必要时补充官方博客。
- 已读取 `planning-with-files` 技能说明，并继续沿用 `temp/task_plan.md`、`temp/findings.md`、`temp/progress.md` 作为磁盘工作记忆。
- `session-catchup.py` 仍无法运行，报 `python.exe` cannot be accessed by the system`，本轮继续手动维护计划文件。
- 下一步：检索 `Anthropic` 官方站点中和 `Claude Code`、工具权限、subagent、自动化工作流相关的页面，并归纳成 `agent-alpha` 的关键决策点。
- 已完成官方资料第一轮检索，重点覆盖：
  - `overview`
  - `settings`
  - `team`
  - `security`
  - `memory`
  - `slash-commands`
  - `sub-agents`
  - `hooks-guide`
  - `hooks`
  - `cli reference`
  - `common workflows`
  - `devcontainer`
  - `monitoring`
  - `output-styles`
- 已输出正式研究文档：
  - `temp/改进方向/anthropic官方-harness工程研究.md`
- 结论已收束到 4 个核心判断面：
  - 上下文分层
  - 权限与工作区边界
  - hooks 与 cron 的先后顺序
  - subagent 与 capability install 的正确定位
