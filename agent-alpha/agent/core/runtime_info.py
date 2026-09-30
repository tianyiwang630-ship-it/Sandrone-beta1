"""Write the public runtime path guide used by skill installation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agent.core.runtime_layout import runtime_python
from agent.core.runtime_paths import build_runtime_env, python_cli_dir


PUBLIC_ENV_KEYS = (
    "AGENT_ALPHA_ROOT", "AGENT_ALPHA_APP_ROOT", "AGENT_ALPHA_PYTHON",
    "AGENT_ALPHA_BROWSER_PYTHON", "AGENT_ALPHA_NODE_EXECUTABLE",
    "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "TMP", "TEMP",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
    "PIP_CACHE_DIR", "UV_CACHE_DIR", "UV_TOOL_DIR", "UV_TOOL_BIN_DIR",
    "NPM_CONFIG_PREFIX", "NPM_CONFIG_CACHE", "NODE_PATH", "VIRTUAL_ENV",
    "PYTHONUSERBASE", "PYTHONPYCACHEPREFIX", "PYTHONNOUSERSITE",
    "PYTHONUTF8", "PYTHONIOENCODING", "HF_HOME", "TRANSFORMERS_CACHE",
    "PLAYWRIGHT_BROWSERS_PATH", "DOTNET_CLI_HOME", "CARGO_HOME", "RUSTUP_HOME",
)


def write_runtime_info(
    *, data_root: Path, app_root: Path, built_in_skills: Path, third_party_skills: Path
) -> Path:
    root = Path(data_root).resolve()
    python = runtime_python(root)
    env = build_runtime_env(root)
    lines = [
        "# Alpha 运行环境与技能安装路径",
        "",
        "此文档由后端按当前运行配置生成，只用于查阅，不要手动编辑。",
        "",
        f"- 程序资源根：`{Path(app_root).resolve()}`",
        f"- 可写数据根：`{root}`",
        f"- 内置技能：`{Path(built_in_skills).resolve()}`",
        f"- 第三方技能安装目录：`{Path(third_party_skills).resolve()}`",
        f"- 共用 Python：`{python}`",
        f"- 共用 Python 的 CLI 目录：`{python_cli_dir(python)}`（使用前确认命令确实存在）",
        f"- 独立技能环境根：`{root / 'tools' / 'venvs'}`",
        f"- uv 工具环境：`{root / 'tools' / 'uv'}`",
        f"- 命令入口：`{root / 'bin'}`",
        f"- 长期资料：`{root / 'state'}`",
        f"- 临时文件：`{root / 'temp'}`",
        f"- 服务变量配置：`{root / 'config' / 'runtime_env.local.json'}`",
        "",
        "## 工作指引",
        "",
        "Bash 默认在当前 Agent 工作区执行。安装时用绝对路径明确指定目录和 Python。",
        "技能文件放第三方技能目录；任务成果放工作区，长期能力资料放 state，一次性文件放 temp。",
        "普通 Python 依赖先检查共用环境；兼容才安装，冲突时在独立技能环境根创建环境并明确调用其 Python。",
        "独立环境无需激活；新建后告知用户原因、位置和调用方式。",
        "技能安装不能修改后端工具注册表或应用核心代码。",
        "",
        "## 本次终端环境中的公开变量",
        "",
    ]
    lines.extend(f"- `{key}`：`{env[key]}`" for key in PUBLIC_ENV_KEYS if env.get(key))
    body = "\n".join(lines) + "\n"
    destination = root / "state" / "runtime-info.md"
    staging = root / "temp" / "runtime-info"
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_text(encoding="utf-8") == body:
        return destination
    fd, temporary = tempfile.mkstemp(prefix="runtime-info-", suffix=".md", dir=staging)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination
