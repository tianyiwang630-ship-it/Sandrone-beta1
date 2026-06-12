# agent-alpha browser 两点改造设计确认稿

日期：2026-05-30

## 1. 背景

当前已经确认：

- `agent-browser` 在 alpha 中可用。
- `agent-browser install` 下载的是 Chrome for Testing。
- Chrome for Testing 适合自动化测试，但在 Google、X、LinkedIn 等登录敏感网站上容易被识别为测试/自动化浏览器。
- 本机存在正式 Chrome：

```text
C:/Users/20157/AppData/Local/Google/Chrome/Application/chrome.exe
```

因此，本轮改造聚焦两点：

1. 让 alpha 长期优先使用本机正式 Chrome。
2. 把 alpha 的 browser profile 从 `state.json` 思路升级为完整 Chrome `user-data` 目录思路。

## 2. 改造点一：正式 Chrome 路由

### 2.1 目标

alpha 调用 `agent-browser` 时，优先使用本机正式 Chrome，而不是 `agent-browser` 下载的 Chrome for Testing。

### 2.2 长期注入方式

使用 `agent-browser` 官方支持的环境变量：

```text
AGENT_BROWSER_EXECUTABLE_PATH
```

写入 alpha 的持久环境变量文件：

```text
agent-alpha/config/runtime_env.local.json
```

推荐值：

```json
{
  "AGENT_BROWSER_EXECUTABLE_PATH": "C:/Users/20157/AppData/Local/Google/Chrome/Application/chrome.exe"
}
```

如果文件中已经有其他 token、cookie 或配置，则只新增这个字段，不覆盖原有字段。

### 2.3 回退规则

如果 `AGENT_BROWSER_EXECUTABLE_PATH` 存在并且路径有效：

```text
使用本机正式 Chrome
```

如果 `AGENT_BROWSER_EXECUTABLE_PATH` 不存在，或路径无效：

```text
回退到 agent-browser 默认浏览器，也就是 Chrome for Testing
```

但回退不能静默发生，工具结果中必须明确提示，例如：

```json
{
  "browser_executable": {
    "mode": "agent_browser_default",
    "configured_path": "C:/bad/path/chrome.exe",
    "exists": false,
    "fallback": true,
    "warning": "Configured Chrome path was not found; fell back to agent-browser default browser."
  }
}
```

这样可以避免用户误以为当前正在使用正式 Chrome。

## 3. 改造点二：完整 profile 管理

### 3.1 目标

alpha 的 browser profile 应该表示一个完整 Chrome 用户数据目录，而不是只表示一个 `state.json` 文件。

也就是说：

```text
profile = Chrome user-data 目录
```

而不是：

```text
profile = cookies/localStorage 的 state.json
```

### 3.2 长期 profile 目录

长期 profile 由 alpha 管理，存放在：

```text
agent-alpha/state/browser/profiles/<profile_name>/user-data
```

例如：

```text
agent-alpha/state/browser/profiles/default/user-data
agent-alpha/state/browser/profiles/google-main/user-data
agent-alpha/state/browser/profiles/x-main/user-data
agent-alpha/state/browser/profiles/linkedin-job/user-data
```

长期 profile 用来保存真实登录态、cookies、站点权限和浏览器状态。

### 3.3 有头模式

有头模式直接使用长期 profile：

```text
agent-browser --headed --profile <长期 user-data> open <url>
```

用户在有头浏览器中手动登录后，登录态会自然写入这个长期 `user-data` 目录。

有头模式不再依赖：

```text
agent-browser state save
```

因为完整 Chrome profile 会自己保存状态。

### 3.4 无头模式

无头模式不直接写长期 profile。

无头任务开始时，工具后端复制长期 profile：

```text
agent-alpha/state/browser/profiles/<profile_name>/user-data
```

到运行期临时目录：

```text
agent-alpha/state/browser/runtime/<session_id>/user-data
```

然后无头浏览器使用这个临时 profile：

```text
agent-browser --profile <runtime user-data> open <url>
```

任务结束后删除：

```text
agent-alpha/state/browser/runtime/<session_id>
```

默认不把无头任务产生的变化回写到长期 profile。

### 3.5 多 agent 模式

多 agent 模式下，每个 agent/browser session 都拿自己的临时 profile 副本：

```text
agent A -> state/browser/runtime/session_a/user-data
agent B -> state/browser/runtime/session_b/user-data
agent C -> state/browser/runtime/session_c/user-data
```

多个 agent 可以从同一个长期 profile 复制，但不能同时写同一个长期 profile。

## 4. 工具后端职责

这些逻辑应该由 browser 工具背后的后端/包装层实现，而不是让大模型自己处理。

大模型只需要知道工具语义：

```text
用 profile=google-main 打开有头浏览器
用 profile=google-main 打开无头浏览器
关闭浏览器
截图
点击
输入
获取页面内容
```

大模型不应该自己拼：

```text
Chrome.exe 路径
长期 profile 路径
runtime 临时 profile 路径
复制目录
删除目录
锁文件路径
```

后端自动处理：

- 选择正式 Chrome 或回退默认浏览器。
- 创建长期 profile 目录。
- 有头模式使用长期 profile。
- 无头模式复制临时 profile。
- 任务结束后清理临时 profile。
- 多 agent 时隔离各自临时 profile。
- 在工具结果中提示 Chrome 路由和回退状态。

## 5. 锁规则

为了避免 profile 被同时读写，建议增加简单锁：

```text
有头模式写长期 profile 时，对该长期 profile 加独占锁。
无头模式复制长期 profile 前，检查该长期 profile 是否正在被有头模式写入。
```

如果长期 profile 正在被有头模式写入，无头模式可以选择：

```text
等待
```

或：

```text
返回清楚错误，让用户稍后重试
```

第一版实现建议先返回清楚错误，逻辑更简单。

## 6. 与现有 state.json 的关系

现有的 `state.json` 可以暂时保留为兼容字段，但不再作为主登录态方案。

主方案变为：

```text
完整 Chrome user-data 目录
```

`state.json` 后续可以用于轻量导入/导出 cookies，但不承担 Google、X、LinkedIn 这类复杂登录场景。

## 7. 第一版验收标准

第一版改造完成后，应满足：

1. `runtime_env.local.json` 可以长期注入 `AGENT_BROWSER_EXECUTABLE_PATH`。
2. browser 工具调用 `agent-browser` 时优先使用正式 Chrome。
3. 如果正式 Chrome 路径无效，可以回退默认浏览器，并在结果中明确提示。
4. `profile=default` 会对应完整目录：

```text
agent-alpha/state/browser/profiles/default/user-data
```

5. 有头模式直接使用长期 `user-data`。
6. 无头模式复制长期 `user-data` 到 runtime 临时目录。
7. 无头任务结束后清理 runtime 临时目录。
8. 大模型不需要知道真实路径，只需要传 `profile` 和 `mode`。

