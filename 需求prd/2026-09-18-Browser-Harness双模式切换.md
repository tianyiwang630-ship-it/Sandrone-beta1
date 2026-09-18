# 2026-09-18 Browser Harness 人工登录 / CDP 双模式切换

## 背景/原因

Alpha最初用 `--remote-debugging-port=0` 启动专属Chrome，Browser Harness可以稳定操作网页，但Google可能拒绝在已受自动化控制的浏览器中首次登录。随后改用Chrome原生远程调试授权，又出现专属资料目录无法被上游自动发现、`/json/version` 返回404以及Alpha提前删除 `DevToolsActivePort` 的问题，导致登录成功后仍无法接管。

本次将人工登录与自动操作明确拆成两个由Agent选择的模式。两种模式始终复用Alpha专属资料目录，允许切换时正常重开专属Chrome，以较小的适配层换取确定的登录和CDP连接行为。

## 具体设计

### Tool / Skill / Plugin能力层

- `browser_harness_exec`增加可选 `mode`：`manual`打开普通专属Chrome供用户登录，`cdp`用同一资料目录启动随机CDP端口并执行Browser Harness代码。
- 省略 `mode` 时兼容原有CDP调用；若专属Chrome正在等待人工登录，则返回 `user_action_required`，不自动抢回控制。
- `manual`不接收代码，`cdp`必须提供代码。Skill在登录、MFA、验证码、不安全浏览器提示或重复登录状态时进入人工模式；用户回复“继续”后显式进入CDP模式并重新检查页面。

### Agent Runtime / Harness层

- 新增小型专属浏览器生命周期模块，集中处理进程识别、正常关闭、启动模式和Chrome设置迁移；工具入口只校验和转发参数。
- Windows按完整 `--user-data-dir` 参数识别Alpha主进程，并复核PID与创建时间；通过窗口关闭消息正常退出，不按名称批量结束或强杀Chrome。
- Windows后台进程查询显式使用UTF-8，以兼容中文资料路径；查询失败必须停止切换并返回错误，不能当作“浏览器不存在”后继续修改资料或删除端口文件。
- 模式切换先停止旧daemon，确认专属Chrome退出，再关闭其 `Local State` 中遗留的原生远程调试开关并清理旧端口文件。设置文件先备份到 `temp/browser-harness`，再原子替换；失败时停止切换。
- 人工模式不带远程调试参数；CDP模式使用 `--remote-debugging-port=0`。端口必须属于使用专属资料目录的Chrome，并通过 `/json/version` 健康检查后才交给Browser Harness。
- 不再因HTTP 404直接删除 `DevToolsActivePort`。固定Alpha daemon名称，并清空继承环境中的云浏览器和CDP连接变量，避免复用错误连接。
- 所有Web Agent继续共享同一个运行对象和串行锁；人工登录等待不占用锁，后端重启后可从专属Chrome进程参数恢复当前模式。

### 退出与异常处理

- 退出时健康CDP浏览器仍优先通过 `Browser.close` 关闭；端点损坏但能确认是Alpha CDP浏览器时，停止daemon后正常关闭其窗口。纯人工浏览器继续保留。
- 模式切换遇到多主进程、进程身份变化、窗口无法关闭、设置损坏或连接超时时返回明确的可恢复错误，不启动第二个浏览器实例。
- 工具进程内一旦进入人工等待，省略模式的后续调用会优先返回人工登录提示；只有用户确认后显式传入 `mode="cdp"` 才能恢复自动操作。Skill将这条停止规则放在开头，并禁止用Bash另启Chrome自救。
- 后端清理总预算为25秒，Electron等待上限为30秒；重复清理保持幂等，清理失败不阻止桌面应用退出。
- Cookie、账号和站点存储保留在原资料目录；网站主动过期、退出账号或未提交表单跨重启丢失不属于登录态持久化保证。

## 验收标准

- Agent可以显式进入人工模式，用户登录后回复“继续”，再切到CDP模式完成网页操作。
- 人工模式中的普通调用不会自动重启浏览器；同模式调用不重复重启。
- 模式切换不影响用户日常Chrome，不强杀进程，不清理Alpha登录资料。
- 旧原生调试开关能够安全迁移；HTTP 404不会提前删除端口文件。
- 自动测试覆盖双向切换、旧调用兼容、精确进程归属、PID复用、设置失败、端口异常、daemon更换和退出时间预算；不启动真实浏览器。

## 与旧方案的关系

本设计替代同日《Browser Harness原生授权与人工登录》中“登录后通过 `chrome://inspect/#remote-debugging` 原生授权接管”的流程。Browser Harness版本、官方CLI调用、专属资料目录和旧浏览器系统保留策略不变。
