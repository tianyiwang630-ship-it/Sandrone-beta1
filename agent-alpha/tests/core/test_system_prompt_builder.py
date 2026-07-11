from pathlib import Path

from agent.core.system_prompt_builder import build_system_prompt


def test_system_prompt_guides_general_search_to_open_websearch():
    prompt = build_system_prompt(
        workspace_root=Path("workspace"),
        logs_dir=Path("logs"),
        events_dir=Path("events"),
        skills_dir=Path("skills"),
        agent_home_skills_dir=Path("home/.agents/skills"),
        mcp_servers_dir=Path("mcp-servers"),
        mcp_registry_path=Path("mcp-servers/registry.json"),
    )

    assert "## Web Search" in prompt
    assert "prefer the open-websearch MCP tools" in prompt
    assert "engines exposed by open-websearch itself" in prompt
    assert "switch to another available open-websearch engine" in prompt
    assert "mcporter" in prompt
    assert 'command not found' in prompt


def test_system_prompt_includes_session_created_at_value():
    prompt = build_system_prompt(
        workspace_root=Path("workspace"),
        logs_dir=Path("logs"),
        events_dir=Path("events"),
        skills_dir=Path("skills"),
        agent_home_skills_dir=Path("home/.agents/skills"),
        mcp_servers_dir=Path("mcp-servers"),
        mcp_registry_path=Path("mcp-servers/registry.json"),
        session_created_at="2026-06-30T09:15:00",
    )

    assert "Session created at: 2026-06-30T09:15:00" in prompt
    assert (
        "This is the creation date of this session. It may differ from dates mentioned by the user, "
        "and it is not automatically the current date."
    ) in prompt


def test_system_prompt_includes_session_created_at_fallback():
    prompt = build_system_prompt(
        workspace_root=Path("workspace"),
        logs_dir=Path("logs"),
        events_dir=Path("events"),
        skills_dir=Path("skills"),
        agent_home_skills_dir=Path("home/.agents/skills"),
        mcp_servers_dir=Path("mcp-servers"),
        mcp_registry_path=Path("mcp-servers/registry.json"),
    )

    assert "Session created at: (not provided)" in prompt


def test_system_prompt_describes_bash_workspace_rules():
    prompt = build_system_prompt(
        workspace_root=Path("workspace"),
        logs_dir=Path("logs"),
        events_dir=Path("events"),
        skills_dir=Path("skills"),
        agent_home_skills_dir=Path("home/.agents/skills"),
        mcp_servers_dir=Path("mcp-servers"),
        mcp_registry_path=Path("mcp-servers/registry.json"),
    )

    assert "Bash commands default to cwd=" in prompt
    assert "`working_dir` may point to either AGENT_ALPHA_ROOT or the current workspace" in prompt
    assert "resolve it by checking AGENT_ALPHA_ROOT first" in prompt
    assert "Do not assume `workspace/...` means the current session workspace." in prompt
    assert "current workspace may be either a project-local managed folder or an external user-selected folder" in prompt


def test_system_prompt_describes_bash_timeout_and_pipeline_guidance():
    prompt = build_system_prompt(
        workspace_root=Path("workspace"),
        logs_dir=Path("logs"),
        events_dir=Path("events"),
        skills_dir=Path("skills"),
        agent_home_skills_dir=Path("home/.agents/skills"),
        mcp_servers_dir=Path("mcp-servers"),
        mcp_registry_path=Path("mcp-servers/registry.json"),
    )

    assert "Bash tool calls default to a 30 second timeout" in prompt
    assert "set `timeout_seconds` up to 300 seconds" in prompt
    assert "do not rely on them for critical environment or dependency checks" in prompt
    assert "`uv pip list --python <agent-alpha .venv python>`" in prompt
    assert "instead of shell pipelines such as `uv pip list | grep ...`" in prompt


def test_system_prompt_rejects_bare_pip_for_python_installs():
    prompt = build_system_prompt(
        workspace_root=Path("workspace"),
        logs_dir=Path("logs"),
        events_dir=Path("events"),
        skills_dir=Path("skills"),
        agent_home_skills_dir=Path("home/.agents/skills"),
        mcp_servers_dir=Path("mcp-servers"),
        mcp_registry_path=Path("mcp-servers/registry.json"),
    )

    assert "Do not use bare `pip`, `pip3`, or versioned `pip` commands" in prompt
    assert "`python -m pip install ...`" in prompt
    assert "`uv pip install --python <agent-alpha .venv python> ...`" in prompt


def test_system_prompt_includes_runtime_records_for_logs_and_events():
    prompt = build_system_prompt(
        workspace_root=Path("workspace"),
        logs_dir=Path("session-log/logs"),
        events_dir=Path("session-log/events"),
        skills_dir=Path("skills"),
        agent_home_skills_dir=Path("home/.agents/skills"),
        mcp_servers_dir=Path("mcp-servers"),
        mcp_registry_path=Path("mcp-servers/registry.json"),
    )

    assert "## Runtime Records" in prompt
    assert "Logs directory: session-log\\logs" in prompt or "Logs directory: session-log/logs" in prompt
    assert "Events directory: session-log\\events" in prompt or "Events directory: session-log/events" in prompt
    assert "Logs are archived logs. Events are real-time runtime records." in prompt


def test_system_prompt_includes_events_dir_fallback():
    prompt = build_system_prompt(
        workspace_root=Path("workspace"),
        logs_dir=Path("logs"),
        events_dir=None,
        skills_dir=Path("skills"),
        agent_home_skills_dir=Path("home/.agents/skills"),
        mcp_servers_dir=Path("mcp-servers"),
        mcp_registry_path=Path("mcp-servers/registry.json"),
    )

    assert "Events directory: (not provided by runner)" in prompt
