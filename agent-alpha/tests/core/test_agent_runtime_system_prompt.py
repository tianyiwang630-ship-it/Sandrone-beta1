from pathlib import Path

from agent.core import agent_runtime as agent_runtime_module
from agent.core.agent_runtime import AgentRuntime


def test_agent_runtime_build_system_prompt_passes_runtime_events_dir(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_build_system_prompt(**kwargs):
        captured.update(kwargs)
        return "system prompt"

    monkeypatch.setattr(agent_runtime_module, "build_system_prompt", fake_build_system_prompt)

    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.workspace_root = tmp_path / "workspace"
    runtime.runtime_logs_dir = tmp_path / "session-log" / "logs"
    runtime.runtime_events_dir = tmp_path / "session-log" / "events"
    runtime.skills_dir = tmp_path / "skills"
    runtime.agent_home_skills_dir = tmp_path / "home" / ".agents" / "skills"
    runtime.session_created_at = "2026-06-30T09:15:00"
    runtime.task_id = "task-1"
    runtime.skill_loader = type(
        "FakeSkillLoader",
        (),
        {"get_summaries": lambda self: [{"name": "test-skill", "description": "desc"}]},
    )()
    runtime.prompt_documents = [{"name": "AGENTS.md", "path": str(Path("AGENTS.md")), "content": "hello"}]

    prompt = AgentRuntime._build_system_prompt(runtime)

    assert prompt == "system prompt"
    assert captured["events_dir"] == runtime.runtime_events_dir
    assert captured["logs_dir"] == runtime.runtime_logs_dir
