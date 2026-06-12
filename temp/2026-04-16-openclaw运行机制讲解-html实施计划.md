# OpenClaw 运行机制讲解 HTML 实施计划

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 `learning proj/openclaw` 的真实代码与文档，产出一份由浅入深、可交互、详细且通俗的 HTML 讲解材料，帮助会写 Python 脚本但不熟悉 agent/runtime 架构的读者理解 OpenClaw 的运行机制。

**Architecture:** 先从代码中提炼真实运行时主干，再把内容组织成“全景图 + 主流程 + 模块拆解 + 状态流转 + 设计取舍”的长篇交互页面。页面使用原生 HTML/CSS/JS 实现，重点通过信息分层、节点展开、流程切换和源码证据点来帮助读者逐步建立理解。

**Tech Stack:** HTML, CSS, Vanilla JavaScript

---

### Task 1: 梳理源码证据点

**Files:**
- Read: `learning proj/openclaw/README.md`
- Read: `learning proj/openclaw/src/gateway/*`
- Read: `learning proj/openclaw/src/agents/*`
- Read: `learning proj/openclaw/src/sessions/*`
- Read: `learning proj/openclaw/src/memory/*`
- Read: `learning proj/openclaw/src/cron/*`
- Read: `learning proj/openclaw/extensions/*`

- [ ] 列出运行时主干模块
- [ ] 找到每个模块的关键入口文件
- [ ] 记录主流程与状态流转证据

### Task 2: 设计 HTML 信息架构

**Files:**
- Create: `temp/openclaw-运行机制详解.html`

- [ ] 定义“由浅入深”的阅读路径
- [ ] 设计交互区块与导航结构
- [ ] 规划每个模块的讲解模板

### Task 3: 编写页面内容与交互

**Files:**
- Modify: `temp/openclaw-运行机制详解.html`

- [ ] 写全景概览与主流程
- [ ] 写关键模块拆解与数据流
- [ ] 加入交互、样式和源码证据点

### Task 4: 自检输出

**Files:**
- Verify: `temp/openclaw-运行机制详解.html`

- [ ] 检查 HTML 是否可直接打开
- [ ] 检查内容是否严格基于 openclaw 实现
- [ ] 检查讲解是否从浅到深、前后衔接自然
