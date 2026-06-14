alpha下目录写一个md，browser管理规则
一、运行场景合同
必须支持：
1. 多个 alpha 可以同时运行。
2. 有头 / CDP 同一时间只能一个 alpha 使用。
3. 当 alpha A 正在用有头或 CDP 时，alpha B / C 仍然可以开无头。
4. 无头永远使用临时运行目录，不直接写 default。
5. 有头不会被 AI 通过 browser_close 自动关闭。
6. 有头关闭或保存后，同一个alpha实例的新开的无头能拿到最新登录态。
7. ESC / Ctrl+C / 异常退出后，下次能安全清理旧副本。
8. browser 状态绑定 alpha 运行空间，不绑定 workspace，也不绑定 CLI。
9. 单个 alpha 内部模式顺序任意：
   无头 -> 有头
   有头 -> 无头
   CDP -> 无头 -> 有头
   无头 -> CDP -> 无头
   都应该有明确语义，不互相误关、不误删、不抢 profile。
二、三种模式边界
无头：
- 可多实例并发。
- 每次创建自己的 runtime 临时目录。
- 不写 default。
- 结束后清理自己的 runtime。
- 不允许关闭有头/CDP。

有头：
- 用户可见窗口。
- 同一时间只能一个 alpha 使用。
- 负责人工登录、验证码、2FA。
- 不能被 browser_close 自动关闭。
- 关闭必须走明确的 profile_close_headed。
- 关闭或保存时，把登录态更新到 default 的稳定状态。

CDP：
- 连接用户外部打开的浏览器。
- 同一时间只能一个 alpha 使用。
- 和有头互斥。
- disconnect 只断开控制，不关闭用户真实浏览器。
- 不参与 alpha profile 的写入。
三、Profile 5 复制流程
这里要作为单独流程写进设计，不和运行时混在一起。
源：
C:\Users\20157\AppData\Local\Google\Chrome\User Data\Local State
C:\Users\20157\AppData\Local\Google\Chrome\User Data\Profile 5

目标：
agent-alpha/state/browser/profiles/default/user-data/Local State
agent-alpha/state/browser/profiles/default/user-data/Default
规则：
1. 复制脚本只做单向同步：
   本机 Chrome Profile 5 -> alpha default user-data

2. 不反向同步：
   alpha default 不写回本机 Chrome Profile 5。

3. 脚本运行前检查 Chrome / Chromium / agent-browser 是否还在运行。
   如果在运行，直接中止，不自动杀你的真实 Chrome。

4. alpha 路径自动识别：
   脚本根据自身所在位置定位 agent-alpha，不写死 D:\files\demo\0312-newagent。

5. 复制完成后，alpha 的有头浏览器可以使用这份 default user-data,无头浏览器也能在不开有头情况下使用新的profile的内容。

6. 后续如果你在真实 Chrome 的 Profile 5 里重新登录了网站，
   再跑同步脚本，把新的登录态覆盖进 alpha default。