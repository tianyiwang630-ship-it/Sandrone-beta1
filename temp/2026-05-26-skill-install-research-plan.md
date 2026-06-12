# 2026-05-26 Skill 安装机制研究计划

## 目标

只基于本地源码，研究 openclaw 和 hermes agent 如何安装、管理、调用、更新、删除类似 Agent-Reach 这种带 pip/npm 依赖的 skill，并与 agent-alpha 当前机制做事实对比。

## 边界

- 不修改 agent-alpha 功能代码。
- 不访问互联网。
- 不给改造建议，只输出事实对比。
- 输出文件放在 `temp`。
- 不更新 `开发日志.md`，因为本次不做功能迭代、架构调整或 bug 修复。

## 阶段

1. 定位 openclaw、hermes agent、agent-alpha 的相关目录和关键词。
2. 梳理 openclaw 的 skill 安装、存储、配置、更新、调用、删除流程。
3. 梳理 hermes agent 的 skill 安装、存储、配置、更新、调用、删除流程。
4. 梳理 agent-alpha 当前对应能力。
5. 写 Markdown 详细报告。
6. 写 HTML 可视化报告，并做基本文件检查。

## 进展

- 2026-05-26：已确认用户要求只看本地源码，输出 Markdown 和 HTML 到 `temp`。

