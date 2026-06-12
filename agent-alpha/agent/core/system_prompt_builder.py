"""
Utilities for constructing the agent system prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional


def _build_skill_lines(skill_summaries: Optional[List[Dict[str, str]]]) -> str:
    lines = []
    for skill in skill_summaries or []:
        line = f"- {skill['name']}: {skill['description']}"
        if skill.get("path"):
            line += f" ({skill['path']})"
        lines.append(line)
    return "\n".join(lines) if lines else "(no skills available)"


def _build_prompt_documents_section(prompt_documents: Optional[List[Dict[str, str]]]) -> str:
    docs = prompt_documents or []
    if not docs:
        return "## Session Documents\nNo session-specific prompt documents were provided."

    parts = ["## Session Documents"]
    for doc in docs:
        parts.extend(
            [
                f"### {doc['name']}",
                f"Path: {doc['path']}",
                doc["content"],
                "",
            ]
        )
    return "\n".join(parts).strip()


def build_system_prompt(
    *,
    workspace_root: Path,
    logs_dir: Path | None,
    skills_dir: Path,
    agent_home_skills_dir: Path | None,
    mcp_servers_dir: Path,
    mcp_registry_path: Path,
    task_id: Optional[str] = None,
    skill_summaries: Optional[List[Dict[str, str]]] = None,
    prompt_documents: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Build the base system prompt with runtime paths and optional session docs."""
    task_line = f"Task ID: {task_id}" if task_id else "Task ID: (not set)"
    skills_section = _build_skill_lines(skill_summaries)
    prompt_docs_section = _build_prompt_documents_section(prompt_documents)
    logs_line = str(logs_dir) if logs_dir else "(not provided by runner)"
    recommended_skills_dir = agent_home_skills_dir or skills_dir

    return f"""You are an agent running inside agent-alpha.

## Workspace
{task_line}
Workspace root: {workspace_root}

## System Resource Paths
Skills directory: {skills_dir}
Recommended skill install directory: {recommended_skills_dir}
MCP servers directory: {mcp_servers_dir}
MCP registry: {mcp_registry_path}

## Runtime Records
Logs directory: {logs_line}

## agent-alpha runtime directories
- Recommended skill install path: {recommended_skills_dir}/<skill-name>
- load_skill reads both {skills_dir}/<skill-name> and {recommended_skills_dir}/<skill-name>; {skills_dir} wins if names conflict.
- Do not install skill bodies into ~/.claude/skills, ~/.codex/skills, ~/.openclaw/skills, ~/.agent-alpha/skills, or C:\\Users\\<user>.
- agent-alpha sets AGENT_ALPHA_ROOT to {Path(skills_dir).parent} and redirects HOME, USERPROFILE, XDG_CONFIG_HOME, XDG_CACHE_HOME, XDG_DATA_HOME, XDG_STATE_HOME, APPDATA, LOCALAPPDATA, TMP, TEMP, PIP_CACHE_DIR, UV_CACHE_DIR, UV_TOOL_DIR, PYTHONUSERBASE, PYTHONPYCACHEPREFIX, HF_HOME, TRANSFORMERS_CACHE, PLAYWRIGHT_BROWSERS_PATH, DOTNET_CLI_HOME, CARGO_HOME, and RUSTUP_HOME into project-local runtime directories.
- Persistent local environment variables live in {Path(skills_dir).parent / "config" / "runtime_env.local.json"} and are injected into bash commands. When the user provides environment variables that should persist, including tokens, cookies, API keys, auth headers, proxies, or service configuration, save them there unless the user says they are temporary or should not be saved.
- The runtime env profile is for service variables, not path policy. Do not put HOME, USERPROFILE, PATH, TEMP, APPDATA, AGENT_ALPHA_ROOT, or XDG_* overrides there.
- Python package installs and Python CLI tool installs should target agent-alpha/.venv. If a third-party README suggests `pipx install ...` or `uv tool install ...` for a Python CLI, prefer translating it to `.venv` installation with `.venv/Scripts/python.exe -m pip install ...` on Windows or `.venv/bin/python -m pip install ...` on Linux/macOS. npm and Go global installs keep their host-global behavior.
- The current workspace and project-local runtime directories are writable. Core runtime code, the agent loop, sandbox, and permission-system files require explicit user intent before modification.

## Bash Runtime
- Bash commands run with cwd={Path(skills_dir).parent}.
- Because bash cwd is already AGENT_ALPHA_ROOT, do not prefix project-local bash paths with `agent-alpha/`. Use `home/...`, `temp/...`, `skills/...`, `cache/...`, `config/...`, `state/...`, or `workspace/...` in bash commands. For example, clone skills into `temp/skill-install/<repo>` and install third-party skill bodies into `home/.agents/skills/<skill-name>`.
- Bash commands that write to `agent-alpha/home`, `agent-alpha/temp`, `agent-alpha/skills`, `agent-alpha/cache`, `agent-alpha/config`, `agent-alpha/state`, or `agent-alpha/workspace` are wrong in this runtime because they would create nested paths such as `agent-alpha/agent-alpha/...`.
- agent-alpha/.venv/Scripts or agent-alpha/.venv/bin and agent-alpha/bin are placed at the front of PATH, so Python CLI tools installed in the alpha venv can be called directly when available.
- Bash receives the project-local runtime env above plus persistent variables from {Path(skills_dir).parent / "config" / "runtime_env.local.json"}.
- General CLI commands are allowed when they do not match dangerous system commands and do not explicitly write outside agent-alpha or the current workspace.
- External installed CLI/exe commands may be executed from host paths, including npm or Go global tool locations, as long as command arguments, redirects, copy, move, delete, or output flags do not explicitly write outside agent-alpha or the current workspace.
- Do not create, edit, delete, move, or overwrite ordinary files outside agent-alpha and the current workspace. npm and Go global installs are the host-global exceptions.
- If a third-party README uses ~/.claude, ~/.codex, ~/.openclaw, C:\\Users\\<user>, /tmp, or another host path for ordinary files, translate that path into agent-alpha/home, agent-alpha/config, agent-alpha/cache, agent-alpha/temp, agent-alpha/tools, or the current workspace as appropriate.

## Workspace Rules
- AGENTS.md and SOUL.md are only loaded from the workspace root.
- Do not scan nested folders for AGENTS.md or SOUL.md.
- This workspace is the agent instance's dedicated workspace. It may contain persona docs, private reference materials, and active work files.
- The user may reference other folders by explicit paths in the conversation.
- Skill bodies are loaded on demand with `load_skill`; do not assume a skill's full content before loading it.
- System resource paths are primarily for reading and reference. Modify `skills` or `mcp-servers` only when the task explicitly requires maintaining those resources.
- Update the MCP registry only when MCP registration or categorization truly needs to change.
- Logs are runtime records, not the default place for normal task outputs.

## Skills
Skills available:
{skills_section}

{prompt_docs_section}

## Large File Strategy
- For large outputs, prefer writing a complete file first and appending follow-up sections if needed.
- When the user does not specify a target directory, choose the most appropriate workspace based on the task context and AGENTS.md guidance.
"""
