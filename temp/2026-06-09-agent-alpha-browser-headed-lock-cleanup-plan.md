# agent-alpha 浏览器 headed lock 清理计划

## 背景

agent-alpha 的浏览器模式已经按三类分清：

- 有头浏览器：直接使用 `default` 长期登录态，主要用于主 agent 下的人工登录或人工确认。
- 无头浏览器：启动前复制 `default` 到本次 runtime 副本，在副本里运行，用完删除副本。
- CDP：接管用户自己管理的外部浏览器，不参与 alpha 本地 profile 生命周期。

当前问题是：有头浏览器异常退出、agent 会话中断或 CLI 被关闭后，`profiles/default/.headed.lock` 可能残留。无头浏览器随后看到这个旧锁，会误以为 `default` 仍被有头占用，导致无法复制 profile。

本计划只处理这个 lock / runtime 残留问题，不改变三种浏览器模式的总体设计。

## 目标

实现后应满足：

- 旧 `.headed.lock` 不会永久阻塞无头浏览器。
- 无头浏览器仍然只复制 `default` 副本，不直接写 `default`。
- 多 agent / subagent 仍然只使用无头浏览器能力。
- 清理浏览器残留时，只影响 alpha 自己管理的浏览器，不影响用户日常 Chrome。
- 不引入复杂 PID owner 系统、profile 版本管理或双向同步。

## 非目标

本次不做：

- CDP 行为调整。
- profile 双向同步。
- 多 profile 版本系统。
- 复杂的浏览器进程 ownership 数据结构。
- 对用户真实 Chrome profile 的任何写入。

## 设计原则

### 1. `.headed.lock` 是弱标记

`.headed.lock` 只表示：

```text
default 长期登录态曾经被有头浏览器占用
```

它不是必须长期保留的强锁。按当前设计约束，遇到旧锁时可以直接清理，然后让无头继续复制 `default`。

### 2. 启动时清理旧运行态

alpha 启动时可以清理这些目录或文件：

```text
agent-alpha/state/browser/runtime/*
agent-alpha/state/browser/sessions/*
agent-alpha/state/browser/sockets/*
agent-alpha/state/browser/profiles/*/.headed.lock
```

这些都是上次运行留下的临时状态，重启后不再信任。

不能清理：

```text
agent-alpha/state/browser/profiles/default/user-data
```

这是长期登录态。

### 3. 无头启动前强制清旧锁

无头浏览器准备复制 profile 前：

```text
1. 删除 default/.headed.lock
2. 复制 default/user-data 到 runtime/<session_id>/user-data
3. 在 runtime 副本中运行浏览器
4. 关闭后删除 runtime 副本
```

这样旧锁不会阻塞无头运行。

### 4. 复制失败时清理 alpha 自己的浏览器进程

如果删除 lock 后复制 profile 仍失败，说明可能还有 alpha 自己启动的 Chrome 正在占用 `state/browser` 下的 profile 文件。

这时允许清理的进程必须满足：

```text
进程名可以是 chrome.exe
但命令行必须包含 agent-alpha/state/browser
```

不能按 `chrome.exe` 名称一刀切杀进程。

明确禁止清理：

```text
C:\Users\20157\AppData\Local\Google\Chrome\User Data
```

也就是用户日常使用的 Chrome profile。

清理流程：

```text
1. 删除 default/.headed.lock
2. 第一次复制 default -> runtime
3. 如果复制失败，清理 alpha state/browser 相关浏览器进程
4. 再删除一次 lock 和失败的 runtime 副本
5. 第二次复制 default -> runtime
6. 如果仍失败，返回明确错误
```

不做无限重试。

### 5. 有头正常关闭仍删除 lock

有头浏览器逻辑保留：

```text
打开有头 -> 创建 .headed.lock
正常关闭 -> 删除 .headed.lock
异常退出 -> 下次启动或无头启动时清理
```

## 用户可理解的行为

如果一切正常：

```text
用户：用无头浏览器打开知乎
后端：删除旧 lock，复制 default 副本，启动无头
```

如果旧有头锁残留：

```text
后端：直接删除旧 lock，继续复制，不再让 AI 创建空 profile
```

如果 alpha 自己的有头浏览器还占用文件：

```text
后端：只关闭 alpha state/browser 相关浏览器进程，重试复制
```

如果复制仍失败：

```text
返回错误：default profile 仍然被占用，可能有 alpha 浏览器窗口没有关闭，请关闭 alpha 打开的浏览器窗口后重试。
```

## 实施范围

预计涉及：

- `agent-alpha/agent/tools/browser_manager.py`
  - 增加启动或初始化时的 browser runtime cleanup。
  - 无头复制前删除 `.headed.lock`。
  - 复制失败后清理 alpha state/browser 相关浏览器进程，并重试一次。
  - 改善复制失败的错误信息。
- `agent-alpha/tests/core/test_browser_tools.py`
  - 增加 lock 清理、runtime 清理、复制失败重试、进程过滤相关测试。

是否需要调整启动入口，要看当前 `BrowserManager` 实例化位置：

- 如果 browser manager 在工具加载时实例化，可以在 manager 初始化时清理。
- 如果希望更早清理，可以接到 alpha runtime 启动流程。

优先选择改动更少、边界更清晰的位置。

## 测试计划

需要覆盖：

1. 初始化时会清理：

```text
state/browser/runtime/*
state/browser/sessions/*
state/browser/sockets/*
profiles/*/.headed.lock
```

2. 无头启动前发现 `.headed.lock` 会删除并继续复制。

3. 复制失败时会触发一次 alpha 浏览器残留清理，然后重试。

4. 进程清理只匹配命令行里包含 `agent-alpha/state/browser` 的浏览器进程。

5. 普通 Chrome profile 路径不会被清理：

```text
C:\Users\20157\AppData\Local\Google\Chrome\User Data
```

6. 第二次复制仍失败时，返回清楚错误，而不是创建空 profile 或静默失败。

建议验证命令：

```powershell
D:\Anaconda\envs\ai12\python.exe -m pytest tests\core\test_browser_tools.py -q --basetemp ..\temp\pytest-browser-lock-cleanup
```

## 开发日志规则

当前文件只是计划，不更新 `D:\files\demo\0312-newagent\开发日志.md`。

等实际实施并通过测试后，再在开发日志中记录：

- 日期
- 背景：旧 `.headed.lock` 残留导致无头无法复制 profile
- 关键更改：启动清理、无头前清锁、alpha 浏览器残留进程清理、测试覆盖

