# Python / Node 环境管理研究计划

日期：2026-05-26

## 用户问题

判断用户理解是否正确，并查看 OpenClaw 与 Hermes 如何管理：

- Python 环境
- Node 安装目录
- 全局、项目级、会话级依赖
- skill/runtime 安装依赖时的边界

## 边界

- 只读本地源码与本地文档。
- 不联网。
- 不修改 agent-alpha 主体代码。
- 输出为本轮中文回答；必要中间记录放入 `temp`。

## 步骤

1. 校准概念：Python/Node 依赖管理是否确实需要进入 runtime 设计。
2. 搜索 OpenClaw 中 `uv`、`python`、`node`、`npm`、`pnpm`、`bun`、`install`、`PATH`、`tools` 等关键词。
3. 搜索 Hermes 中同类关键词，重点看 skill hub、optional skills、runtime loader、config。
4. 形成对比结论。
