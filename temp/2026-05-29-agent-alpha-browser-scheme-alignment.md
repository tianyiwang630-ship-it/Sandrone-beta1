# Agent-Alpha Browser 方案对齐稿

日期：2026-05-29

## 目标

这份文档用于沉淀当前已经对齐的 `agent-alpha` 浏览器自动化方案，作为后续实现时的共识基础。

目标覆盖以下 4 个场景：

1. 无头浏览器执行任务，比如在已经登录好的 X 平台查信息、去 arXiv 下载论文。
2. 有头模式由用户手动登录某个网站，并保存登录信息，下次不再重复登录，比如推特。
3. 开启 CDP，连接用户已经打开的浏览器，帮助执行自动化任务，比如投递简历。
4. 多 agent 模式下，多个 agent 同时使用无头浏览器执行任务。

## 实现注记

第一版落地时，`agent-browser` 官方已经支持 `--session`、`--headed`、`--cdp`、`state save/load` 等能力。
因此 `agent-alpha` 的长期 profile 先实现为“profile 元数据 + `state.json` 登录态文件”，而不是直接复制完整 Chrome `user-data-dir`。
这能更小地覆盖当前场景：有头登录后 `state save`，无头任务前 `state load`，CDP 仍由外部浏览器自己管理登录态。

## 核心原则

浏览器能力按 4 层拆分：

1. `profile`
   保存长期登录态，是“浏览器身份容器”。
2. `session`
   表示某一次浏览器运行实例。
3. `backend`
   表示浏览器运行方式。
4. `tool policy`
   表示某个 agent 实例能看到哪些浏览器工具。

一句话总结：

`profile` 管登录态，`session` 管一次运行，`backend` 管运行方式，`tool policy` 管当前 agent 是否能用这些能力。

## 三种浏览器模式

第一版支持三种模式：

### 1. `local-headless`

- 默认执行模式。
- 无界面，适合自动化任务。
- 用于查信息、下载论文、访问已登录网站等常规任务。

### 2. `local-headed-login`

- 有头模式。
- 主要用于用户手动登录、扫码、过验证码、人工确认。
- 不作为 subagent 或多 agent 的常规执行模式。

### 3. `external-cdp`

- 连接用户已经打开的浏览器。
- 适合强人工参与、可随时接管的任务。
- 典型场景是投递简历、复杂表单、多轮交互页面。

## 登录态设计

### 长期登录态

默认有一个母版 profile：

```text
default
```

用户也可以手动创建新的长期 profile，比如：

```text
work
twitter-main
job-search
research
```

注意：

- 一个长期 profile = 一套浏览器身份。
- 一套浏览器身份里可以同时登录多个网站。
- 不是“每个网站必须一个 profile”。
- 只有在需要隔离账号、用途、工作环境时，才新建新的长期 profile。

例如：

```text
default
  - Google 个人账号
  - GitHub 个人账号
  - Twitter 个人账号
  - LinkedIn 个人账号

work
  - Google 工作账号
  - GitHub 公司账号
  - LinkedIn 工作身份
```

### 运行时副本

多 agent 或无头任务运行时，不直接使用母版 profile，而是复制出临时副本：

```text
profiles/default       # 母版，长期保存
runs/task-001-default  # 临时副本
runs/task-002-default  # 临时副本
```

这些临时副本：

- 继承母版登录态；
- 互相隔离；
- 默认任务完成后删除；
- 不自动回写母版，避免污染长期登录态。

### CDP 登录态

`external-cdp` 不使用本地 profile 副本逻辑。

它连接的是用户自己打开的浏览器，因此登录态由那个外部浏览器自己的 profile 管理，`agent-alpha` 只负责连接和操作。

## 目录建议

建议将浏览器相关状态放在本地隐藏目录，例如：

```text
agent-alpha/
  .local/
    browser/
      profiles/
        default/
          user-data/
          downloads/
          artifacts/
        work/
          user-data/
          downloads/
          artifacts/
      runs/
        task-001-default/
        task-002-default/
      profiles.json
      locks/
```

并加入 `.gitignore`：

```text
.local/browser/
```

原因：

- 这里会保存 cookie、localStorage、IndexedDB、缓存等敏感信息；
- 这些内容绝不能提交到 git。

## 工具权限设计

浏览器工具不应该对所有 agent 一视同仁开放，而应该跟 agent 实例的角色和权限绑定。

建议分为 3 个工具组：

### 1. `browser_headless`

用于正常无头执行：

```text
browser_navigate
browser_snapshot
browser_click
browser_type
browser_scroll
browser_press
browser_close
```

### 2. `browser_profile`

用于 profile 管理和人工登录：

```text
profile_list
profile_create
profile_use
profile_login_headed
```

### 3. `browser_cdp`

用于连接外部浏览器：

```text
browser_connect_cdp
browser_disconnect_cdp
browser_cdp_status
```

## 不同 agent 的开放策略

### 主 agent

建议开放：

```text
browser_headless + browser_profile + browser_cdp
```

行为规则：

- 默认使用 `local-headless`。
- 遇到需要登录的网站时，暂停并询问用户是否开启 `local-headed-login`。
- 只有当用户明确要求时，才开启 `external-cdp`。

### subagent

建议只开放：

```text
browser_headless
```

原因：

- subagent 应保持稳定、可批量运行；
- 不应随意弹出浏览器窗口；
- 不应连接真实用户浏览器。

### 多 agent worker

建议也只开放：

```text
browser_headless
```

并且每个 worker 使用自己独立的临时 profile 副本。

## 有头模式的定位

`local-headed-login` 的定位是：

```text
登录 / 人工接管 / 观察调试
```

而不是让 subagent 或多 agent 的常规执行都能随便用有头模式。

否则可能出现：

- 多个 agent 同时弹窗口；
- 多个 agent 抢同一个登录态；
- 浏览器界面混乱；
- 用户无法判断当前是谁在操作。

## 场景覆盖说明

### 场景 1：无头浏览器执行任务

例如：

- 在已经登录好的 X 平台查信息；
- 去 arXiv 下载论文；
- 浏览静态或轻量动态网页。

方案：

- 使用 `local-headless`；
- 如果任务需要登录，则从母版 profile 复制临时副本运行；
- 如果任务不需要登录，可用匿名或临时 profile。

### 场景 2：有头模式手动登录并保存

例如：

- 登录推特；
- 扫码登录某网站；
- 通过验证码验证。

方案：

- 使用 `local-headed-login`；
- 直接打开母版 profile；
- 用户手动完成登录；
- 关闭后将登录态保存在母版 profile 中。

### 场景 3：开启 CDP 执行自动化

例如：

- 投递简历；
- 操作复杂交互页面；
- 用户希望随时接管。

方案：

- 使用 `external-cdp`；
- 用户自己先打开浏览器；
- `agent-alpha` 连接该浏览器；
- 登录态由外部浏览器自身管理。

### 场景 4：多 agent 并发

例如：

- 多个 agent 同时跑多个网页任务；
- 同时查询多个站点；
- 并行下载多个论文页面。

方案：

- 所有 worker 只用 `local-headless`；
- 每个 worker 从母版 profile 复制自己的临时副本；
- 不允许多个 worker 直接同时打开同一个母版 profile。

## 关键约束

### 1. 同一个母版 profile 不能被多个浏览器进程直接共享写入

否则容易出现：

- profile 被锁；
- cookie 相互覆盖；
- 一个 agent 登出导致大家都失效；
- 缓存和页面状态混乱；
- 文件损坏。

### 2. 并发任务必须使用副本

母版 profile 只用于：

- 长期保存登录态；
- 有头登录更新；
- 派生运行副本。

### 3. 有头登录前要避免和写入型运行会话冲突

当用户要用 `local-headed-login` 更新某个母版 profile 时，需要确保没有正在基于这个母版写入的活跃会话。

## 第一版建议边界

第一版先不做这些：

- 云浏览器；
- 反检测浏览器；
- 自动验证码；
- 自动同步临时副本回母版；
- 复杂账号托管。

第一版先把这些打稳：

1. `local-headless`
2. `local-headed-login`
3. `external-cdp`
4. 长期 profile
5. 临时副本派生
6. 基于 agent 实例的工具权限控制

## 当前共识摘要

当前对齐的 browser 方案可以概括为：

1. 浏览器模式分为 `local-headless`、`local-headed-login`、`external-cdp` 三种。
2. 登录态由母版 profile 保存，运行时复制出临时副本。
3. 一个长期 profile 是一套浏览器身份，可以同时登录多个网站。
4. subagent 和多 agent 默认只开放无头浏览器工具。
5. 主 agent 默认无头运行，遇到需要登录的情况时停下来询问用户是否切到有头登录。
6. CDP 只在用户明确要求时使用。
7. 同一个母版 profile 不能被多个运行实例直接并发使用。
