"""
Utilities for constructing the agent system prompt.
"""

from __future__ import annotations

import os
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
    events_dir: Path | None,
    skills_dir: Path,
    agent_home_skills_dir: Path | None,
    mcp_servers_dir: Path,
    mcp_registry_path: Path,
    session_created_at: Optional[str] = None,
    task_id: Optional[str] = None,
    skill_summaries: Optional[List[Dict[str, str]]] = None,
    prompt_documents: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Build the base system prompt with runtime paths and optional session docs."""
    task_line = f"Task ID: {task_id}" if task_id else "Task ID: (not set)"
    skills_section = _build_skill_lines(skill_summaries)
    prompt_docs_section = _build_prompt_documents_section(prompt_documents)
    logs_line = str(Path(logs_dir).resolve()) if logs_dir else "(not provided by runner)"
    events_line = str(Path(events_dir).resolve()) if events_dir else "(not provided by runner)"
    recommended_skills_dir = agent_home_skills_dir or skills_dir
    session_created_line = session_created_at or "(not provided)"
    workspace_root = Path(workspace_root).resolve()
    alpha_root = Path(skills_dir).parent.resolve()
    skills_dir = Path(skills_dir).resolve()
    recommended_skills_dir = Path(recommended_skills_dir).resolve()
    mcp_servers_dir = Path(mcp_servers_dir).resolve()
    mcp_registry_path = Path(mcp_registry_path).resolve()
    python_interpreter = alpha_root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    return f"""You are an agent running inside agent-alpha.

## Workspace
{task_line}
WORKSPACE_ROOT: {workspace_root}
Session created at: {session_created_line}
This is the creation date of this session. It may differ from dates mentioned by the user, and it is not automatically the current date.

## System Resource Paths
AGENT_ALPHA_ROOT: {alpha_root}
Built-in skills directory: {skills_dir}
Third-party skill install directory: {recommended_skills_dir}
Temporary directory: {alpha_root / "temp"}
Cache directory: {alpha_root / "cache"}
Python interpreter: {python_interpreter}
MCP servers directory: {mcp_servers_dir}
MCP registry: {mcp_registry_path}

## Runtime Records
Logs directory: {logs_line}
Events directory: {events_line}
Logs are archived logs. Events are real-time runtime records.

## agent-alpha runtime directories
- Recommended skill install path: {recommended_skills_dir}/<skill-name>
- load_skill reads both {skills_dir}/<skill-name> and {recommended_skills_dir}/<skill-name>; {skills_dir} wins if names conflict.
- Do not install skill bodies into ~/.claude/skills, ~/.codex/skills, ~/.openclaw/skills, ~/.agent-alpha/skills, or C:\\Users\\<user>.
- agent-alpha sets AGENT_ALPHA_ROOT to {alpha_root} and redirects HOME, USERPROFILE, XDG_CONFIG_HOME, XDG_CACHE_HOME, XDG_DATA_HOME, XDG_STATE_HOME, APPDATA, LOCALAPPDATA, TMP, TEMP, PIP_CACHE_DIR, UV_CACHE_DIR, UV_TOOL_DIR, PYTHONUSERBASE, PYTHONPYCACHEPREFIX, HF_HOME, TRANSFORMERS_CACHE, PLAYWRIGHT_BROWSERS_PATH, DOTNET_CLI_HOME, CARGO_HOME, and RUSTUP_HOME into project-local runtime directories.
- Persistent local environment variables live in {alpha_root / "config" / "runtime_env.local.json"} and are injected into bash commands. When the user provides environment variables that should persist, including tokens, cookies, API keys, auth headers, proxies, or service configuration, save them there unless the user says they are temporary or should not be saved.
- The runtime env profile is for service variables, not path policy. Do not put HOME, USERPROFILE, PATH, TEMP, APPDATA, AGENT_ALPHA_ROOT, or XDG_* overrides there.
- Python package installs and Python CLI tool installs should target {python_interpreter}. Do not use bare `pip`, `pip3`, or versioned `pip` commands because they may resolve to a host Python. Use `{python_interpreter} -m pip install ...` or `uv pip install --python {python_interpreter} ...`. If a third-party README suggests `pipx install ...` or `uv tool install ...` for a Python CLI, prefer translating it to this environment. npm and Go global installs keep their host-global behavior.
- The current workspace and project-local runtime directories are writable, except {alpha_root / "agent"}, which is always read-only to runtime agents.

## Bash Runtime
- Bash working_dir rules are defined by the bash tool schema; follow that schema when choosing the command directory.
- {alpha_root / "agent"} can be read but must never be created, edited, moved, overwritten, or deleted by runtime agents. Write project files to WORKSPACE_ROOT and temporary artifacts to {alpha_root / "temp"}.
- {python_interpreter.parent} and {alpha_root / "bin"} are placed at the front of PATH, so Python CLI tools installed in the alpha venv can be called directly when available.
- Bash receives the project-local runtime env above plus persistent variables from {alpha_root / "config" / "runtime_env.local.json"}.
- Bash tool calls default to a 30 second timeout and may set `timeout_seconds` up to 300 seconds for expected long tasks such as builds, tests, installs, or large file processing. If a bash command times out, simplify the command, avoid shell pipelines, or retry with an explicit longer timeout when the work is genuinely long.
- External shell tools such as `grep`, `sed`, `awk`, `xargs`, `head`, `tail`, `cut`, `tr`, `sort`, `uniq`, `wc`, and `tee` may exist through Git Bash, MSYS, WSL, or host PATH. They are allowed, but do not rely on them for critical environment or dependency checks.
- For Python environment and dependency checks, prefer `{python_interpreter} -c ...` or `uv pip list --python {python_interpreter}` instead of shell pipelines such as `uv pip list | grep ...`.
- General CLI commands are allowed when they do not match dangerous system commands and do not explicitly write outside agent-alpha or the current workspace.
- External installed CLI/exe commands may be executed from host paths, including npm or Go global tool locations, as long as command arguments, redirects, copy, move, delete, or output flags do not explicitly write outside agent-alpha or the current workspace.
- Do not create, edit, delete, move, or overwrite ordinary files outside agent-alpha and the current workspace. npm and Go global installs are the host-global exceptions.
- If a third-party README uses ~/.claude, ~/.codex, ~/.openclaw, C:\\Users\\<user>, /tmp, or another host path for ordinary files, translate that path into the absolute HOME, config, cache, temp, tools, or WORKSPACE_ROOT paths listed above as appropriate.

## Web Search
- For ordinary web search, current information lookup, price lookup, news lookup, or source discovery, prefer the open-websearch MCP tools when they are available.
- Use the engines exposed by open-websearch itself. If an engine returns no results, times out, or fails, switch to another available open-websearch engine instead of repeatedly retrying the same one.
- Do not default to bash-based search CLIs from skill documentation, such as `mcporter` or `exa`, unless the user explicitly asks for that CLI or you have already verified it exists in this runtime.
- If a search CLI returns "command not found", treat that route as unavailable and switch away from it instead of retrying the same missing command.

## Workspace Rules
- AGENTS.md and SOUL.md are only loaded from the workspace root.
- Do not scan nested folders for AGENTS.md or SOUL.md.
- This workspace is the agent instance's dedicated workspace. It may contain persona docs, private reference materials, and active work files.
- The current workspace may be either a project-local managed folder or an external user-selected folder; treat it as the primary location for task outputs unless the task explicitly targets agent-alpha runtime directories.
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
