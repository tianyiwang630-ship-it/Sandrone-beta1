# 2026-09-18 Browser Harness 接入方案

> 状态：已实施并通过自动测试；浏览器授权与人工登录顺序已由同日《Browser Harness 原生授权与人工登录》迭代调整；Chrome for Testing 二进制和正式 EXE 打包仍按原范围留给后续分发迭代。

## 背景/原因

Agent Alpha 当前浏览器能力通过 `agent-browser` CLI 实现，并包含无头浏览器、可见登录浏览器和外部 CDP 等多套工具。实际使用中，这套能力的操作效果和扩展方式不如 Browser Harness，而且对模型暴露的工具数量较多。

本次迭代计划将 Browser Harness 作为新的默认浏览器能力。旧浏览器系统暂时停用，但代码、测试、资料目录、同步脚本和历史文档全部保留，确保以后仍可恢复。整体原则是尽量遵循 Browser Harness 自身的 daemon、标签页、CDP 和 helper 设计，仅增加 Agent Alpha 无法避免的薄适配，不重新实现一套浏览器管理系统。

## 目标与范围

- Browser Harness 成为 Agent Alpha 默认浏览器能力，模型只看到一个浏览器执行工具。
- 用户正在使用的日常 Chrome、Edge、窗口、标签页和浏览器资料不得受到影响。
- 所有 Web Agent 共用一个 Alpha 专属浏览器、登录态、Browser Harness daemon 和 helper 工作区，浏览器操作串行执行。
- 当前只支持 Web/FastAPI 入口，不为 CLI 增加专门适配。
- 当前实现浏览器路径和离线打包契约，但不在本次提交真正打包 Chrome、制作安装包或 EXE。
- 第一版继续使用文本模型，不改造多模态消息链路；Accessibility Tree、DOM 和 CDP 是主要页面理解方式。

## 具体设计

### 1. Tool / Skill / Plugin 能力层

- 新增唯一模型可见工具 `browser_harness_exec`，参数为：
  - `code`：交给 Browser Harness 执行的 Python 代码。
  - `timeout_seconds`：默认 60 秒，最大 300 秒。
- 工具通过 UTF-8 stdin 将代码交给官方 `browser-harness` CLI，不依赖 Git Bash、heredoc 或临时脚本文件。
- 工具返回 stdout、stderr、退出码、超时和中断状态，并限制输出规模，避免异常页面输出挤占上下文。
- 不对 Browser Harness 的 Python 代码建立脆弱的语法白名单。能力通过独立的 `browser_harness` 工具组授权；网页点击、输入和导航不逐步弹出权限确认。
- 新增 Alpha 内置 Browser Harness Skill，以固定版本的官方 Skill 为基础：
  - 将 heredoc 和直接 CLI 示例改写为 `browser_harness_exec` 用法。
  - 保留 Accessibility Tree、DOM、CDP、标签页、下载、上传和 helper 等官方工作流。
  - 每项任务首次导航使用 `new_tab(url)`；后续先检查 `current_tab()` 和 `list_tabs()`，通过 `switch_tab()` 复用页面。
  - Agent 只能关闭自己明确创建并记录了 `targetId` 的标签页，不能按域名批量关闭标签页。
  - 登录、密码、MFA、验证码、授权同意或账号选择需要用户处理时，结束当前调用并在对话中请用户操作；用户回复“继续”后再恢复任务。
- `agent_helpers.py` 和 domain-skills 工作区在整个 Alpha 实例内共用，允许 Agent 按 Browser Harness 原生方式编辑；第一版不增加 helper 数据库、自动备份服务或私有版本协议。
- domain skills 保持 Browser Harness 默认关闭状态，不自动触发；以后有明确需求时再单独启用。

### 2. Agent Runtime / Harness 层

- Browser Harness 固定使用 `0.1.13`，通过项目本地独立 `uv tool` 环境安装，不加入 Agent Alpha 主 `.venv`，避免其依赖版本与主环境冲突。
- 不安装 Browser Harness MCP extra。本次直接调用官方 CLI，不增加 MCP 服务。
- Browser Harness 的版本由 Alpha 统一管理：
  - 关闭上游更新检查。
  - 不向 Agent 暴露 `--update`。
  - 关闭遥测和默认录屏。
  - 后续仅在 Alpha 版本升级并完成兼容验证时更新。
- Web 后端进程内建立一个可中断的共享锁。一次完整的 `browser_harness_exec` 调用持有该锁，所有 Web 会话和 Agent 的本地浏览器操作排成一条串行通道；非浏览器任务仍可并行。
- 不增加 CLI 与 Web 之间的跨进程锁，也不把 CLI 纳入本次验收范围。
- 不建立 Alpha 私有标签页归属表、任务队列、daemon 状态机或浏览器 PID 数据库。daemon 启动、CDP 连接、标签页切换和连接恢复继续使用 Browser Harness 原生实现。
- ESC 或 Web 停止请求只终止当前 Browser Harness CLI 调用并释放锁，不关闭共享浏览器、daemon 或持久化资料。

### 3. 专属浏览器启动与隔离

- 正式发行时随 Alpha 附带固定版本 Chrome for Testing，约定路径为：

  `tools/chrome-for-testing/chrome-win64/chrome.exe`

- 本次不提交 Chrome 二进制，也不修改真正的安装包流水线；只实现上述路径识别并记录未来打包契约。
- 源码开发环境缺少随包 Chrome for Testing 时，可以查找本机已安装的 Chrome 或 Edge 程序文件，但只借用程序文件，绝不使用或复制用户日常浏览器资料。
- 为避免 Browser Harness 在 Windows 上误判并连接用户正在运行的 Chrome，增加一层最薄的专属启动适配：
  - 使用 Alpha 专属 `user-data-dir` 启动浏览器。
  - 不通过命令行强制传入 `--remote-debugging-port`；首次使用时，用户先在普通浏览器状态完成人工登录，再通过 `chrome://inspect/#remote-debugging` 原生授权。
  - 从专属资料目录由 Chrome 原生授权生成的 `DevToolsActivePort` 读取实际端口。
  - 将 `http://127.0.0.1:<port>` 通过 Browser Harness 官方 `BU_CDP_URL` 传入。
  - 不自行实现 CDP 客户端，不固定抢占端口，不记录 PID，不扫描或按进程名结束浏览器。
- 启动参数同时包含非默认资料目录、禁止首次运行引导和禁止默认浏览器检查，保证启动为独立 Alpha 窗口。
- 若上次 Alpha 异常退出后专属浏览器仍然健康，则读取同一 `DevToolsActivePort` 并重新连接；若端口记录已经失效，则清理该专属运行标记并重新启动浏览器。
- 若 Chrome 已打开但尚未原生授权，则返回可恢复的 `user_action_required`，提示用户登录和授权；浏览器非零退出时才报告启动错误，不使用强杀或按 `chrome.exe` 名称清理的方式处理。

### 4. 生命周期与人工接管

- 第一次使用 `browser_harness_exec` 时才启动 Alpha 专属浏览器和 Browser Harness daemon。
- 浏览器在整个 Web 后端生命周期内保持运行；关闭单个对话、项目或 Agent 不关闭浏览器。
- FastAPI 后端正常退出时，在共享锁内尽力完成：
  1. 通过 Browser Harness 执行 CDP `Browser.close`，只关闭 Alpha 专属浏览器实例。
  2. 调用 Browser Harness 官方 `--reload` 停止 daemon。
- 异常崩溃时不做 PID 强杀；残留浏览器由下一次启动按专属资料目录和 `DevToolsActivePort` 重新连接。
- 第一版不增加前端“人工接管/交还 Agent”按钮。首次授权时，用户先在 Alpha 专属浏览器完成人工登录，再启用 Chrome 原生远程调试；登录过期或 Google 阻止受控浏览器登录时，用户临时关闭远程调试、完成登录、重新启用后回复“继续”。

### 5. Workspace / Memory / State 持久化层

- Browser Harness 的持久状态统一放在 `state/browser-harness`，至少包含配置、runtime、专属浏览器资料和共享 agent workspace。
- 临时文件、截图和一次性运行产物放在 `temp/browser-harness`。
- 设置并固定 Browser Harness 使用的目录变量，包括 `BH_HOME`、`BH_RUNTIME_DIR`、`BH_TMP_DIR` 和 `BH_AGENT_WORKSPACE`。
- 明确禁用 Browser Use Cloud 自动启动，不读取或自动使用云端浏览器凭据。
- Alpha 专属浏览器资料长期保留，用户只需在新资料中手动登录一次；不自动复制、同步或导入用户日常 Chrome Profile 5。

### 6. 旧浏览器系统保留策略

- 从 `ToolLoader` 的默认工具注册表中移除旧的 `browser_*`、`profile_*` 和旧 CDP 工具，使其默认不可见、不可调用。
- 保留以下内容，不做删除或重构：
  - `browser_tool.py` 与 `browser_manager.py`。
  - 旧浏览器行为测试。
  - 旧 profile、session 和下载状态目录。
  - Profile 5 同步脚本。
  - 现有《浏览器自动化现状》及相关历史说明。
- 新增旧系统恢复文档，记录旧调用链、三种模式、工具注册项、提示词、资料目录、锁规则和重新启用步骤。
- 若旧系统专用操作文本仍散落在有效提示词或代码中，将内容迁入恢复文档后再从有效注册和提示入口移除；不丢弃历史信息。

### 7. 分发设计

- 正式发行介质未来需要同时包含：
  - 固定版本 Chrome for Testing。
  - Browser Harness 0.1.13 及其隔离依赖环境。
  - Agent Alpha 自身 Python/前端运行环境。
- 最终用户不需要安装 Git Bash、uv、Python、普通 Chrome，也不需要访问 Google 下载源。
- 当前开发环境仍可由 `setup-agent-alpha.ps1` 将固定版本 Browser Harness 安装到项目本地 `uv tool` 目录；正式离线打包方式留给后续打包迭代实现。

## 异常与边界处理

- Browser Harness CLI 缺失或版本不符：返回安装/修复提示，不临时联网更新。
- 随包浏览器缺失且找不到本机兼容程序文件：明确提示当前开发环境未准备浏览器，不运行时下载。
- 浏览器启动失败、端口文件无效或端口被安全软件拦截：返回具体阶段和诊断信息，允许下一次调用重试。
- daemon 暂时失效：先使用 Browser Harness 原生健康检查和恢复；只有上游确认 daemon 不可恢复时才调用官方 reload，不自己接管 daemon PID。
- 共享锁等待超时：返回“浏览器正被另一任务使用”的可恢复结果，不并行执行第二个浏览器任务。
- 用户关闭 Alpha 浏览器窗口或工作标签页：下次调用交由 Browser Harness 原生恢复，并要求 Agent 重新检查 `current_tab()` 和 `list_tabs()`。
- helper 语法或运行错误：保留官方 traceback 并返回给 Agent 修正，不静默替换为旧版本。
- 当前模型无法理解截图内容；画布、纯视觉控件或验证码由用户人工处理，不在本迭代引入图片消息格式。

## 测试设计

自动测试不启动真实浏览器，使用假进程、假端口和临时目录覆盖关键边界：

- 随包 Chrome for Testing 优先、本机 Chrome/Edge 程序文件回退、浏览器完全缺失。
- 用户日常 Chrome 已运行时，仍只启动 Alpha 专属资料目录，并且仅连接该资料目录经用户原生授权后生成的端口。
- 健康残留实例重连、失效 `DevToolsActivePort`、启动失败和资料目录被占用。
- 多个 Web Agent 同时调用时严格串行；等待超时、中断和异常后锁能够释放。
- ESC/停止请求只结束当前 CLI 调用，不关闭共享浏览器或 daemon。
- stdin 使用 UTF-8，多行代码不依赖 Git Bash；stdout/stderr 超长时正确截断。
- 环境变量指向 Alpha 状态目录，更新检查、遥测、录屏和云端自动启动均关闭。
- Web 后端正常退出时依次执行浏览器关闭和 daemon 停止；清理失败不误杀其他浏览器。
- 旧浏览器工具默认不再注册，但旧模块仍可导入、旧测试仍保留。
- 内置 Skill 不再包含要求模型使用 heredoc 或 Git Bash 的生产调用方式。

手工验收场景：

- 保持用户日常 Chrome 打开，再启动 Alpha 浏览器任务，确认日常窗口、标签页、登录态和前后台焦点不被接管。
- 在 Alpha 专属浏览器内手动登录网站，重启 Web 后确认登录态仍然存在。
- 两个 Web 会话同时请求浏览器，确认后发任务等待前一任务释放浏览器通道。
- 验证登录、验证码和 MFA 场景能够暂停，用户操作后可继续。
- 正常关闭 Web 后端，确认 Alpha 专属浏览器关闭而用户日常浏览器保持运行。

## 验收标准

- 模型默认只看到 `browser_harness_exec`，旧浏览器工具不再注册。
- Browser Harness 能通过 Alpha 专属浏览器完成导航、页面读取、点击、输入和标签页切换。
- 用户日常浏览器不被连接、导航、关闭或复用资料目录。
- 所有 Web Agent 共用登录态和 helpers，但浏览器操作不会并发执行。
- 无 Git Bash 的 Windows 环境可以正常调用 Browser Harness。
- 没有网络下载能力时，正式发行设计仍可依靠随包 Browser Harness 和 Chrome for Testing 工作。
- 旧浏览器系统的代码和恢复信息完整保留。
- 自动测试、现有非浏览器测试和手工边界验收通过。

## 本次明确不做

- 不删除旧浏览器系统代码、数据或测试。
- 不为 CLI 增加专门启动、锁、退出或恢复适配。
- 不增加前端浏览器设置页、状态面板或人工接管按钮。
- 不接入 Browser Harness MCP 或 Browser Use Cloud。
- 不改造 LLM 图片输入和多模态消息管线。
- 不在本次提交中下载或提交 Chrome for Testing，也不制作安装包或 EXE。
- 不建立 Alpha 私有标签页归属协议、浏览器 PID 管理器或 daemon 状态数据库。

## 实施结果（2026-09-18）

- 已新增唯一默认浏览器工具 `browser_harness_exec`，使用 UTF-8 stdin 调用项目本地 Browser Harness 0.1.13；旧 `browser_*`、`profile_*` 和旧 CDP 工具已从默认注册表移除，但源代码和行为测试继续保留。
- 已实现进程内共享串行通道、ESC/超时仅停止当前 CLI、输出截断、固定版本校验、缺失依赖诊断，以及 FastAPI 正常退出时依次关闭 Alpha 浏览器和停止 daemon。
- 已实现随包 Chrome for Testing 路径契约、本机 Chrome/Edge 开发回退、Alpha 专属 profile、Chrome 原生远程调试授权、`DevToolsActivePort` 健康检查与显式 `BU_CDP_URL` 连接；不再通过启动参数强制开放调试端口。
- 已新增内置 Browser Harness Skill 和《Browser旧系统恢复说明》，并将 Browser Harness 作为独立 `uv tool` 固定安装，不加入 Alpha 主 `.venv`。
- 已禁用更新检查、遥测、录屏、domain skills、云端自动启动和云端凭据；未启用 MCP、未增加 CLI 专用适配，也未增加前端控制页面。
- 自动测试未启动真实浏览器。新增/调整的边界测试与完整后端测试共 295 项通过；真实项目本地 CLI 固定版本校验通过，并确认当前开发机可解析本机 Chrome 作为开发回退。

## 参考资料

- Browser Harness 项目：https://github.com/browser-use/browser-harness
- Browser Harness 官方 Skill：https://github.com/browser-use/browser-harness/blob/main/SKILL.md
- Browser Harness 安装说明：https://github.com/browser-use/browser-harness/blob/main/install.md
- Browser Harness 0.1.13：https://pypi.org/project/browser-harness/0.1.13/
- Chrome for Testing：https://developer.chrome.com/docs/chromium/chrome-for-testing/
- Chrome 远程调试安全调整：https://developer.chrome.com/blog/remote-debugging-port
