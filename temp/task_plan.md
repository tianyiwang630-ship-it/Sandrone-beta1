# Task Plan

## Current Goal
搜集 `Anthropic` 官方文档与官方博客中和 harness engineering 直接相关的材料，重点覆盖：

- `Claude Code` 的工作方式
- 工具调用与权限边界
- subagent / 并行 / 委派
- 长期运行工作流、自动化、后台任务

输出一份研究 Markdown 到 `temp/改进方向`，然后基于这些官方材料，讨论 `agent-alpha` 改造时必须先做出的关键判断。

## Phases
- [completed] 建立 Anthropic 官方资料研究框架与检索范围
- [completed] 阅读 Anthropic 官方文档中与 Claude Code / tools / subagents / automation 相关页面
- [completed] 阅读 Anthropic 官方博客中与 agent harness / coding agents / tool use / long-running workflows 相关内容
- [completed] 提炼对 `agent-alpha` 有直接影响的工程判断
- [completed] 输出研究 Markdown 到 `temp/改进方向`
- [in_progress] 与用户讨论 `agent-alpha` 的关键决策点

## Key Questions
- Anthropic 官方如何描述 `Claude Code` 这类 harness 的核心构成？
- 官方强调了哪些边界：工具、权限、上下文、委派、并行、长期运行？
- Anthropic 官方有没有给出“什么时候该做 subagent / automation / background work”的明确主张？
- 如果把这些材料映射到 `agent-alpha`，哪些是现在就该学的，哪些暂时不该学？
- 在开始群体智能编排之前，`agent-alpha` 必须先做哪些工程判断？

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| `planning-with-files` 的 `session-catchup.py` 无法运行，报 `python.exe` cannot be accessed by the system | 1 | 记录后跳过自动 catchup，改为手动维护计划文件并继续 |
