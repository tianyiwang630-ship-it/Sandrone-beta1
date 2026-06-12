# agent-alpha 浏览器故障链路、设计缺陷分析与修复计划

日期：2026-06-09

## 1. 背景

本次问题出现在 `agent-alpha` 处理以下用户任务时：

> 然后，用无头浏览器，登陆b站，整理游戏 鸣潮 开服，游戏官方的节奏，以及其玩家的过度不理智行为

运行中最终暴露出的 Python 报错为：

```text
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb2 in position 8: invalid start byte
```

但这不是最原始的业务失败点，而是浏览器工具执行后的二次崩溃。

本文目标不是修某个单独 bad case，而是把这次故障拆成可复用的设计问题：

1. 外部 CLI 启动边界是否安全
2. 外部参数传递是否会被 Windows shell 重新解释
3. 外部进程 stdout/stderr 是否被 agent 当成“永远 UTF-8”的可信输入
4. 工具层异常是否会劫持整个 agent 主流程

## 2. 已确认的事实

### 2.1 浏览器会话确实被成功启动

本次浏览器运行目录：

`agent-alpha/state/browser/sockets/aa_local_headless_bilibili-session_8d92d590`

其中 `_stdout.txt` 内容为：

```json
{"success":true,"data":{"title":"鸣潮 开服 节奏-哔哩哔哩_bilibili","url":"https://search.bilibili.com/all?keyword=%E9%B8%A3%E6%BD%AE+%E5%BC%80%E6%9C%8D+%E8%8A%82%E5%A5%8F"},"error":null}
```

这说明：

1. `agent-browser` 至少已经成功打开了 B 站搜索页
2. 浏览器工具不是“完全没跑起来”
3. 崩溃发生在成功打开页面之后

### 2.2 浏览器会话没有正常收尾

会话元数据文件显示：

- `aa_local_headless_bilibili-session_8d92d590.pid = 13448`
- `aa_local_headless_bilibili-session_8d92d590.port = 53937`
- `aa_local_headless_bilibili-session_8d92d590.version = 0.27.0`

同时进程列表里还能看到与 20:46:34 启动时间一致的：

- `agent-browser-win32-x64.exe`
- 多个 `chrome.exe`

这说明浏览器会话仍然活着，真正崩掉的是 agent 这一轮工具执行后的收尾逻辑。

### 2.3 `_stderr.txt` 不是 UTF-8，而是 Windows 中文编码

`_stderr.txt` 的原始十六进制中包含 `B2` 等字节，按 UTF-8 严格解码失败，但按 GBK 解码可得到：

```text
'order' 不是内部或外部命令，也不是可运行的程序
或批处理文件。
```

这与最终 Python 栈里的 `UnicodeDecodeError` 完全对得上。

### 2.4 `browser_manager.py` 当前强制按 UTF-8 读取 stderr

关键代码位于 [browser_manager.py](/D:/files/demo/0312-newagent/agent-alpha/agent/tools/browser_manager.py:189)：

```python
def _command_prefix(self) -> list[str]:
    found = shutil.which("agent-browser")
    if found:
        return [found]
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    return [npx, "-y", "agent-browser@latest"]

...

stdout_text = stdout_path.read_text(encoding="utf-8").strip()
stderr_text = stderr_path.read_text(encoding="utf-8").strip()
```

这里有两个问题：

1. `shutil.which("agent-browser")` 在 Windows 上可能命中 npm 生成的 `agent-browser.cmd`
2. 读取 stdout/stderr 时假设外部输出一定是 UTF-8

## 3. 故障链路

这次故障不是单点异常，而是两段问题串联。

### 3.1 第一段：外部命令执行链路发生参数污染

Windows 上 `agent-browser` 实际命中的是：

`C:\Users\20157\AppData\Roaming\npm\agent-browser.cmd`

其内容为：

```bat
@ECHO off
"%~dp0node_modules\agent-browser\bin\agent-browser-win32-x64.exe" %*
```

这里的 `%*` 会把参数原样交给 `cmd.exe` 的这一层包装。问题在于 Windows `cmd.exe` 中：

- `&` 不是普通字符
- `&` 是命令分隔符

也就是说，如果某个 URL 参数里出现：

```text
&order=...
```

那么 `.cmd` 包装层有机会把它拆成两段：

1. 前半段仍然作为 URL
2. 后半段 `order=...` 被当成下一条命令

### 3.2 第二段：stderr 读取阶段发生解码崩溃

`order` 被 Windows 误判为命令后，系统把错误信息写进 stderr，而且是中文控制台编码，不是 UTF-8。

随后 `BrowserManager._run_cli()` 执行：

```python
stderr_path.read_text(encoding="utf-8")
```

这一步直接抛出 `UnicodeDecodeError`，于是：

1. 原本已经成功得到的页面打开结果没有机会正常返回
2. agent 工具执行中断
3. 浏览器会话残留
4. 用户只看到了 Python 解码异常，而不是更早发生的参数污染问题

## 4. 第二个问题为什么能确定是 `&order` 导致

我做了最小只读复现：

```cmd
cmd /c "echo before https://search.bilibili.com/all?keyword=test&order=totalrank"
```

结果为：

```text
before https://search.bilibili.com/all?keyword=test
'order' is not recognized as an internal or external command,
operable program or batch file.
```

这与本次 `_stderr.txt` 里读出来的 GBK 中文报错语义完全一致，只是语言不同。

因此，第二个问题不是“B 站奇怪”，而是：

**任何经过 Windows `.cmd` 包装层且参数中包含 `&...` 的 URL，都有机会被拆断。**

这意味着它不是 B 站专属问题，搜索页、带排序参数的页面、OAuth 回调页、部分社交平台 URL 都可能踩中。

## 5. 根因拆分

为了避免以后继续把“现象”和“根因”混在一起，这里分层定义。

### 5.1 直接触发点

直接触发点有两个：

1. `agent-browser.cmd` 这一层对 URL 参数不安全
2. `BrowserManager` 对 stderr 解码策略过于乐观

### 5.2 更上层的设计缺陷

真正的问题不在某个 URL，而在三个边界设计都偏脆弱。

#### 设计缺陷 A：CLI 启动边界不稳定

`BrowserManager._command_prefix()` 只做 `which("agent-browser")`，谁先命中就用谁，没有区分：

1. 原生二进制
2. Node wrapper
3. npm 生成的 `.cmd`
4. PowerShell `.ps1`

在 Windows 上，这几种入口的行为并不等价。

`agent-browser-win32-x64.exe` 是“原生进程参数”语义。

`agent-browser.cmd` 则带有 `cmd.exe` 的特殊字符解释语义。

当前实现把它们当成等价入口，这是设计缺陷。

#### 设计缺陷 B：参数边界没有显式防 shell

虽然 Python `subprocess.Popen(cmd_list)` 本身不是 shell 拼接，但一旦列表的第一个程序其实是 `.cmd` 包装器，就等于重新进入了 shell 语义。

也就是说，当前实现表面上看是“安全的参数列表调用”，实际上在 Windows 上可能退化为“参数交给 `.cmd` 再解释”。

这是一种隐藏的边界穿透。

#### 设计缺陷 C：外部输出被错误当成可信 UTF-8

stdout/stderr 来自外部进程，不能假设：

1. 永远 UTF-8
2. 永远纯文本
3. 永远不会混入本地 shell 的诊断输出

当前工具层没有做编码容错，导致“外部环境输出格式变化”可以直接把 agent 主流程炸掉。

这是明显的鲁棒性缺口。

#### 设计缺陷 D：工具层异常抢占主流程

本次页面其实打开成功了，但最后主流程仍然失败。这说明当前工具层更像：

- “只要 stderr 读取出问题，整个工具调用就失败”

而不是：

- “先保住主结果，再把 stderr 当诊断信息附带返回”

这会造成用户看到的第一错误不是最重要的错误，而是后续的包装错误。

## 6. 设计目标

这次修复不应该是“兼容 B 站 URL 中的 `order`”，而应该满足以下目标：

1. 在 Windows 上调用浏览器 CLI 时，不依赖 `.cmd` / `.ps1` 这种 shell 包装层
2. 所有 URL 都以普通进程参数传入，不被 shell 二次解释
3. 外部 stderr/stdout 无论是 UTF-8、GBK 还是混合输出，都不能导致 agent 崩溃
4. 已成功拿到的主结果，不能被后续诊断输出的读取失败覆盖
5. 修复必须放在 `agent-alpha` 自己的运行时边界里，而不是去 patch 第三方 npm 安装产物

## 7. 修复方案建议

### 7.1 推荐方案：在 `BrowserManager` 内部直接解析原生可执行文件

推荐把修复主点放在 `_command_prefix()`。

核心思路：

1. Windows 上如果 `which("agent-browser")` 命中的是 `.cmd` 或 `.ps1`
2. 则进一步解析同级 `node_modules/agent-browser/bin/agent-browser-win32-x64.exe`
3. 若该 exe 存在，则直接返回 exe 路径
4. 仅在找不到原生 exe 时才 fallback 到现有路径

这样做的好处：

1. 修的是 agent-alpha 自己的启动边界
2. 不依赖修改全局 npm shim
3. 不会被下一次 npm reinstall 覆盖
4. 不只修 `&order`，而是整体绕开 Windows shell 特殊字符解释层

### 7.2 stderr/stdout 解码做统一容错

建议加一个内部小函数，例如：

```python
def _read_process_text(path: Path) -> str:
    ...
```

策略建议：

1. 先尝试 UTF-8
2. 失败后尝试 `locale.getpreferredencoding(False)` 或 Windows 常见 `gbk`
3. 最后使用 `errors="replace"` 兜底

关键原则：

- 外部输出解码失败只能降级为“诊断信息不完整”
- 不能升级为“工具调用整体崩溃”

### 7.3 主结果优先，诊断信息次之

建议调整 `_run_cli()` 的结果处理顺序：

1. 先尽量解析 stdout 最后一行 JSON 主结果
2. stderr 读取失败时，把 stderr 标记为 decode fallback 或 raw bytes 摘要
3. 不要因为 stderr 解码失败抛 Python 异常

也就是说，主结果与诊断信息需要分级：

- 主结果：影响工具是否算成功
- 诊断信息：影响错误解释质量，但不应抢占主结果

### 7.4 不建议的修法

以下修法不推荐：

1. 直接修改 `C:\Users\20157\AppData\Roaming\npm\agent-browser.cmd`
   原因：这是第三方安装产物，重装即可覆盖。
2. 针对 B 站 URL 特判编码或替换 `&order`
   原因：这是在修 bad case，不是在修参数边界设计。
3. 只修 UTF-8 解码，不修 CLI 启动入口
   原因：这样只能避免崩溃，但参数污染仍会继续存在。
4. 只修 `.cmd` 包装，不修 stdout/stderr 解码
   原因：未来其他外部 CLI 仍可能输出非 UTF-8 内容。

## 8. 实施计划

建议实施拆成三个小步，尽量保持手术式改动。

### 第一步：修 CLI 入口解析

改动点：

- [browser_manager.py](/D:/files/demo/0312-newagent/agent-alpha/agent/tools/browser_manager.py:189)

目标：

1. Windows 优先直达 `agent-browser-win32-x64.exe`
2. 避免 `.cmd` / `.ps1` 进入 shell 解释层

预期收益：

- 从根上消掉 `&order` 被拆命令的问题

### 第二步：修输出读取策略

改动点：

- [browser_manager.py](/D:/files/demo/0312-newagent/agent-alpha/agent/tools/browser_manager.py:306)

目标：

1. stdout/stderr 读取容错
2. 禁止 `UnicodeDecodeError` 逃逸出工具层

预期收益：

- 即使外部工具输出异常编码，agent 主流程也不被打穿

### 第三步：补测试

建议新增或补充：

- [test_browser_tools.py](/D:/files/demo/0312-newagent/agent-alpha/tests/core/test_browser_tools.py)

至少覆盖两类测试：

1. `which("agent-browser")` 命中 `.cmd` 时，Windows 解析逻辑会改用原生 exe
2. stderr 为 GBK 字节内容时，`_run_cli()` 不抛 `UnicodeDecodeError`

如果测试粒度允许，再补一个参数级测试：

3. 含 `&order=...` 的 URL 作为命令参数时，不会生成额外 shell 命令

## 9. 验证计划

修复后建议按以下顺序验证。

### 9.1 单元验证

1. 原生 exe 解析逻辑测试通过
2. GBK stderr 容错解码测试通过

### 9.2 最小集成验证

用一个带 `&order=` 的公开 URL 做浏览器 open 调用，验证：

1. 页面正常打开
2. 不再产生 `'order' 不是内部或外部命令`
3. 不再出现 `UnicodeDecodeError`
4. 主结果可正常返回给 agent

### 9.3 回归关注点

需要特别检查不要误伤：

1. 非 Windows 平台的 `agent-browser` 启动逻辑
2. `npx -y agent-browser@latest` 的 fallback 路径
3. 已有 headed/headless/profile/session 逻辑
4. ESC interrupt 终止逻辑

## 10. 最终结论

本次故障不是一个单独的“B 站 URL 兼容性问题”，而是两层设计缺陷叠加：

1. Windows 上浏览器 CLI 启动入口命中了 `.cmd` 包装层，导致 URL 中的 `&order=...` 被解释成新命令
2. `BrowserManager` 把外部 stderr 当成必然 UTF-8，导致读取诊断输出时再次崩溃

因此，正确的修复方向应当是：

1. 在 `agent-alpha` 内部收紧外部 CLI 启动边界，Windows 优先直连原生 exe
2. 在工具层统一做 stdout/stderr 解码容错
3. 保证外部诊断输出异常不会覆盖主结果，不会打穿 agent 主流程

这才是面向设计缺陷的修复，而不是面向某个 URL 特例的补丁。
