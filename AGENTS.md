# 个人偏好
1 我不懂代码，你和我交流要用我能理解的表达方式
2 执行前，必须和我讨论1-3轮，收束边界才能执行
3 如果需要写后端接口，后端接口使用fastapi库，遵循RESTFUL api的规范。
4 代码风格要简洁，如无必要毋增实体；代码要清晰，注重模块化和可扩展性。
5 中间产物放进temp文件夹，尤其是pytest
6 项目有更改时，功能迭代、架构调整、bug修复等，如果最后确定实施了，要写到D:\files\demo\0312-newagent - 交互试验beta\开发日志.md里，记录日期、背景和关键更改内容；如果没有实际修改项目，则不要记开发日志。对于功能迭代、页面改版、功能增加、多智能体加入等产品或能力变化，除开发日志外，还要在D:\files\demo\0312-newagent - 交互试验beta\需求prd文件夹中为每次迭代单独建立一个Markdown文件，文件标题或文件名包含日期和迭代内容，例如“711复盘功能”。迭代文档至少记录“背景/原因”和“具体设计”，避免所有需求内容集中在一个Markdown文件中。
7 终端阅读中文内容，用utf-8
8 你作为codex的python环境是anaconda的ai12，D:\Anaconda\envs\ai12\python.exe，但是这个项目本身使用uv管理的
9 测试要刁钻，找很偏的角度，要钻牛角尖，尤其是边界情况和不符合预期的场景，这样才能保证能稳定运行

# 背景和任务
agent-alpha是一个类似于openclaw/hermes的一个ReActagent后端。目前是有cli作为入口，整体的设计可以看看 harness设计.md 。
paimon是之前的一个也是类似于龙虾的产物，不过做了前端/会话/用户管理，是一个app。
现在我们要做一个应用，只是暂时不用打包成exe和跨系统，只是本地做个前端local host加上会话管理，参考paimon的前端设计，把这个alphha做一个前端交互层。
会话管理呢，我觉得要和paimon不一样，应该是参考codex：一个工作路径开一个project，project可以开很多会话；工作路径可以自动新建，就在workspace里，自动分配id；然后也可以指定文件夹作为工作区（这里要参照一下harness设计.md，把沙盒改一下，一个是alpha根目录，一个是指定的工作区）
然后启动脚本可能得新建一个，可能作一个bat吧，点击就启动。
暂时不要考虑浏览器自动化的适配。
后续具体的功能我会写成文档放到需求prd。

# 要求
1 目前是前端在web 端，但是后续是打包成exe，弄到前端容器，不会是浏览器，设计要考虑兼容性
2 web和cli都只是入口层而已，整个harness是分为
入口层 / Channel Layer
Gateway 控制平面层
消息与会话编排层
Context / Prompt 组装层
Agent Runtime / Harness 层
Agent Loop 执行层
Tool / Skill / Plugin 能力层
权限 / 沙箱 / 安全层
Workspace / Memory / State 持久化层
这些部分，做设计改造的时候要明确是在哪个层做改变。
3 关于agent实例化，至少能够满足以下场景：单agent；平等的多agent；领导agent，去给多个下属agent分配任务，下属agent之间可以对话；有专门的整理记忆/替代用户给AI对话的agent实例
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
