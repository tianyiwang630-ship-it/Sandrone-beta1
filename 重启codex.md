按下面顺序做，目标是：彻底清除旧沙箱与工具包装器，保留项目和任务资料，重新安装最新版 Codex Desktop，并使用 PowerShell 7 + `unelevated` 工作区沙箱。

## 一、重装前备份

不要删除整个 `C:\Users\20157\.codex`。

只需要备份这个配置文件：

```text
C:\Users\20157\.codex\config.toml
```

项目目录不用处理：

```text
D:\files\demo\0312-newagent - 交互试验beta
```

Codex 的历史任务主要在：

```text
C:\Users\20157\.codex\sessions
```

保留即可。

## 二、彻底退出相关程序

1. 完全退出 Codex Desktop。
2. 完全退出所有 VS Code 窗口。
3. 打开任务管理器，结束以下残留进程：

```text
codex.exe
codex-command-runner.exe
codex-windows-sandbox-setup.exe
```

4. 在 VS Code 扩展管理中，暂时禁用或卸载 ChatGPT/Codex 扩展。重装期间只保留桌面版，避免两套运行时同时使用同一份 `.codex` 状态。

## 三、卸载 Codex Desktop

进入：

```text
Windows 设置
→ 应用
→ 已安装的应用
→ Codex
→ 卸载
```

不要手动修改 `C:\Program Files\WindowsApps`。

## 四、清理旧沙箱和工具缓存

卸载完成且相关进程全部结束后，删除：

```text
C:\Users\20157\.codex\.sandbox
C:\Users\20157\.codex\.sandbox-bin
C:\Users\20157\.codex\tmp\arg0
C:\Users\20157\AppData\Local\OpenAI\Codex
```

这些分别是：

- Windows 沙箱运行状态；
- 沙箱命令执行器；
- `apply_patch` 生成的旧批处理包装器；
- Codex Desktop 下载的本地运行时。

不要删除：

```text
C:\Users\20157\.codex\sessions
C:\Users\20157\.codex\plugins
C:\Users\20157\.codex\memories
C:\Users\20157\.codex\auth.json
```

## 五、重置异常的桌面端权限状态

将下面两个文件改名备份，不要直接删除：

```text
C:\Users\20157\.codex\.codex-global-state.json
C:\Users\20157\.codex\.codex-global-state.json.bak
```

例如改成：

```text
.codex-global-state.json.old
.codex-global-state.json.bak.old
```

这一步会重置桌面端保存的审批和界面状态，但不会删除项目代码或任务会话文件。

## 六、确认 PowerShell 7

打开普通 Windows 终端，运行：

```powershell
pwsh --version
```

再运行：

```powershell
(Get-Command pwsh).Source
```

理想结果类似：

```text
PowerShell 7.x.x
C:\Program Files\PowerShell\7\pwsh.exe
```

如果路径指向 `WindowsApps`，优先保留你刚安装的 MSI/WiX 版本，并确认 `C:\Program Files\PowerShell\7` 在 PATH 中。

## 七、重新安装 Codex Desktop

安装当前最新版本，不要重新安装旧的 `26.707.9564.0` 安装包。官方已有案例表明，重装相同版本会立即复现 Windows `apply_patch` 问题。[官方 issue #13959](https://github.com/openai/codex/issues/13959)

安装后：

1. 只启动 Codex Desktop。
2. 登录账号。
3. 暂时不要打开 VS Code。
4. 暂时不要重新安装 VS Code 扩展。

## 八、设置 Windows 沙箱

打开新生成的：

```text
C:\Users\20157\.codex\config.toml
```

保留原来的模型、插件等配置，但将 Windows 部分设置为：

```toml
[windows]
sandbox = "unelevated"
```

不要设置 Full access，也不要使用：

```toml
sandbox_mode = "danger-full-access"
```

如果配置中本来存在 `sandbox_mode`，保持：

```toml
sandbox_mode = "workspace-write"
```

`unelevated` 在部分 Windows 环境中能避开 `elevated` 的沙箱刷新和 ACL 初始化问题。[官方 issue #24098](https://github.com/openai/codex/issues/24098)

## 九、首次启动顺序

1. 完全退出一次 Codex Desktop。
2. 重新打开 Codex Desktop，让它按新配置重建沙箱。
3. 打开项目。
4. 先只使用桌面版。
5. 确认运行稳定后，再决定是否重新安装最新版 VS Code 扩展。

这次重装的关键不是单纯“卸载再安装”，而是同时清除旧沙箱、旧 `apply_patch` 包装器、旧桌面权限状态和旧运行时，并避免桌面版与 VS Code 扩展在第一次启动时互相覆盖。