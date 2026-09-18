# Agent Alpha 旧浏览器系统恢复说明

> 状态：旧系统代码与数据均保留，但自 2026-09-18 起不再注册为默认工具。

## 为什么保留

旧浏览器系统以 `agent-browser` 为执行引擎，覆盖无头浏览器、Alpha 可见登录浏览器和外部 CDP 三种模式。当前默认能力已经切换为 Browser Harness，但旧实现、测试、运行资料和历史说明没有删除，便于回查或在 Browser Harness 无法满足需求时恢复。

## 原调用链

1. `agent/core/tool_loader.py` 的 `BUILTIN_TOOLS` 注册 `agent/tools/browser_tool.py` 中的各个工具类。
2. 工具类把参数交给共享的 `agent/tools/browser_manager.py`。
3. `BrowserManager` 管理 session、profile、下载目录、交互锁和 `agent-browser` CLI 子进程。
4. Agent Runtime 通过 `ToolLoader.execute_tool()` 调用；ESC 由 `interrupt_event` 传到工具并停止当前 CLI 子进程。

## 原三种模式

- 无头模式：`browser_navigate` 创建无头 session，后续由 snapshot/click/type/scroll/press 操作。
- Alpha 可见登录模式：`profile_login_headed` 使用 Alpha 自己的 profile 打开可见浏览器，登录后由 `profile_save_headed` 保存；关闭与强制关闭是独立显式工具。
- 外部 CDP 模式：`browser_connect_cdp` 连接用户明确提供的 CDP 地址，`browser_disconnect_cdp` 只断开控制，不能把外部浏览器当作 Alpha 自有进程关闭。

## 原工具注册项

- 无头：`browser_navigate`、`browser_snapshot`、`browser_click`、`browser_type`、`browser_scroll`、`browser_press`、`browser_close`
- Profile：`profile_list`、`profile_create`、`profile_login_headed`、`profile_save_headed`、`profile_close_headed`、`profile_force_close_headed`
- CDP：`browser_connect_cdp`、`browser_disconnect_cdp`、`browser_cdp_status`

原工具组名称分别是 `browser_headless`、`browser_profile`、`browser_cdp`。恢复时也要同步检查角色配置是否只允许新工具组 `browser_harness`。

## 数据、目录与脚本

旧运行状态仍在 `state/browser` 下，包括：

- `profiles`：Alpha 浏览器资料；
- `sessions`：session 记录；
- `sockets`：旧 CLI 通信状态；
- `downloads`：旧下载目录；
- `runtime`：临时运行资料。

旧的 Profile 5 同步逻辑、锁规则、进程清理规则仍在 `browser_manager.py` 及其测试中。项目根目录的《浏览器自动化现状》保留了更完整的历史行为和风险说明。不要把 `state/browser` 与新系统的 `state/browser-harness` 混用，也不要把日常 Chrome Profile 5 复制进新系统。

## 恢复步骤

恢复前先单独设计并验证，不要直接同时开启两套系统：

1. 在 `ToolLoader.TOOL_GROUPS` 恢复上述旧工具与原工具组映射。
2. 在 `ToolLoader.BUILTIN_TOOLS` 恢复 `browser_tool.py` 的工具类注册。
3. 检查 `ToolLoader._load_builtin_tools()` 是否继续向 Browser/Profile 类传入 `project_root`。
4. 恢复需要的模型提示词或 Skill，明确三种模式、可见浏览器关闭确认和外部 CDP 只断连规则。
5. 检查 `agent-browser` 命令来源和 Windows 运行环境；旧实现可能回退到 `npx -y agent-browser@latest`，离线发行时不能依赖这一回退。
6. 运行 `tests/core/test_browser_tools.py` 全部旧测试，并新增“新旧系统不能同时控制同一资料目录”的验证。
7. 如果决定让两套系统并存，需要重新设计锁、资料目录和模型选路；不能仅把注册项加回来。

## 旧系统的关键安全/行为规则

- 可见登录浏览器不能由普通 `browser_close` 关闭；必须走 profile 专用关闭工具。
- 外部 CDP 浏览器只断开连接，不应结束用户浏览器。
- 旧 headed/CDP 交互锁和强制关闭只适用于旧系统，不能用于 Browser Harness。
- 历史代码包含按浏览器进程检查和清理的逻辑；恢复时必须重新审查，不能套用到新系统的专属浏览器。
