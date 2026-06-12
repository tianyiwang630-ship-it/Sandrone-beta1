# 2026-05-26 Skill 安装机制研究进度

## 日志

- 2026-05-26：开始研究。`rg` 在当前环境被拒绝执行，改用 PowerShell 文件枚举和 Select-String。
- 2026-05-26：已定位 openclaw、hermes agent、agent-alpha 的主要 skill 管理源码入口。
- 2026-05-26：已完成 openclaw 与 hermes 的核心源码第一轮阅读，进入 agent-alpha 对比。
- 2026-05-26：已补齐 agent-alpha 中 `skill_loader.py`、`command_path_extractor.py`、`sandbox_guard.py`、`permissions.json` 的证据。
- 2026-05-26：已生成详细 Markdown 报告：`temp/2026-05-26-openclaw-hermes-agent-alpha-skill安装机制对比报告.md`。
- 2026-05-26：已生成 HTML 可视化：`temp/2026-05-26-openclaw-hermes-agent-alpha-skill安装机制可视化.html`。
- 2026-05-26：未修改 agent-alpha 项目主体代码，因此不写 `开发日志.md`。
