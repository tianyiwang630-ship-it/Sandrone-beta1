# 个人偏好
1 我不懂代码，你和我交流要用我能理解的表达方式
2 执行前，必须和我讨论1-3轮，收束边界才能执行
3 如果需要写后端接口，后端接口使用fastapi库，遵循RESTFUL api的规范。
4 代码风格要简洁，如无必要毋增实体；代码要清晰，注重模块化和可扩展性。
5 中间产物放进temp文件夹，尤其是pytest
6 项目有更改时，功能迭代、架构调整、bug修复等，如果最后确定实施了，要写到0312-newagent - 交互试验beta\开发日志.md里，记录日期、背景和关键更改内容；如果没有实际修改项目，则不要记开发日志。对于功能迭代、页面改版、功能增加、多智能体加入等产品或能力变化，除开发日志外，还要在\需求prd文件夹中为每次迭代单独建立一个Markdown文件，文件标题或文件名包含日期和迭代内容，例如“711复盘功能”。迭代文档至少记录“背景/原因”和“具体设计”，避免所有需求内容集中在一个Markdown文件中。
7 终端阅读中文内容，用utf-8
8 你作为codex的python环境是anaconda的ai12，D:\Anaconda\envs\ai12\python.exe，但是这个项目本身使用uv管理的
9 测试要刁钻一些，因为用户的行为是不可预测的，测试要能cover住边界行为，不过测试不需要过多；不要用浏览器测试

# 背景和任务
目前是有cli和web作为入口，入口以外的，也就是后端设计可以参考 harness设计.md 。

后续具体的功能我会写成文档放到需求prd。

# 要求
1 目前是前端在web 端，但是后续是打包成exe，弄到前端容器，不会是浏览器，设计要考虑兼容性
2 web和cli都只是入口层而已，整个harness是分为
入口层 / Channel Layer；Gateway 控制平面层；消息与会话编排层；Context / Prompt 组装层；Agent Runtime / Harness 层；Agent Loop 执行层；Tool / Skill / Plugin 能力层；权限 / 沙箱 / 安全层；Workspace / Memory / State 持久化层
这些部分，做设计改造的时候要明确是在哪个层做改变。
3 关于agent实例化，至少能够满足以下场景：单agent；平等的多agent；领导agent，去给多个下属agent分配任务，下属agent之间可以对话；有专门的整理记忆/替代用户给AI对话的agent实例。设计agent的时候，要能兼容这些场景，也要能满足当下单agent场景。
4 做任何改动前，都必须先摸清楚对应的代码和实现链路。
5 Windows 环境下，修改文件时优先使用 Codex 内置 apply_patch 工具，禁止调用 apply_patch.bat。若内置工具因 UTF-8、补丁内容截断、缺少 *** End Patch、参数传输或 Windows 沙箱包装器等原因无法执行，则使用 PowerShell 单引号 here-string 将补丁内容赋给变量，并调用当前环境中的 codex.exe --codex-run-as-apply-patch $patch。通过 Get-Command codex.exe 动态获取程序路径，禁止写死 Codex 安装目录或版本号。大补丁应按文件拆分；执行后必须检查退出码，并使用 git diff --check 和目标文件内容确认补丁完整生效。不得改用重定向、Set-Content 等方式绕过补丁流程。示例参考codexwindows沙箱问题解法.md
# 遵守的规范

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
