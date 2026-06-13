from pathlib import Path
import json
import sys
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from tests.conftest import cleanup_test_dir, make_test_dir
from agent.core.agent_runtime import AgentRuntime
from agent.core.context_manager import ContextCompressionResult
from agent.core.runtime_types import RuntimeRequest


def _read_event_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    index = 0
    records: list[dict] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        record, next_index = decoder.raw_decode(text, index)
        records.append(record)
        index = next_index
    return records


def test_agent_runtime_loads_prompt_docs_from_workspace_root_only():
    tmp_dir = make_test_dir("core-agent")
    try:
        workspace_root = tmp_dir / "workspace"
        nested = workspace_root / "nested"
        nested.mkdir(parents=True)
        (workspace_root / "AGENTS.md").write_text("Use the private rulebook.", encoding="utf-8")
        (workspace_root / "SOUL.md").write_text("You are a patient planner.", encoding="utf-8")
        (nested / "AGENTS.md").write_text("This should not be loaded.", encoding="utf-8")

        with patch("agent.core.agent_runtime.ToolLoader.load_all", lambda self: []), patch(
            "agent.core.agent_runtime.LLMClient.from_profile",
            side_effect=lambda profile_name=None: object(),
        ):
            agent = AgentRuntime(
                workspace_root=str(workspace_root),
                logs_dir=str(tmp_dir / "logs"),
            )

        assert agent.workspace_root == workspace_root.resolve()
        assert not hasattr(agent, "workspaces")
        assert "Use the private rulebook." in agent.system_prompt
        assert "You are a patient planner." in agent.system_prompt
        assert "This should not be loaded." not in agent.system_prompt
    finally:
        cleanup_test_dir(tmp_dir)


def test_agent_runtime_exposes_log_payload_without_owning_log_files():
    tmp_dir = make_test_dir("core-agent-log")
    try:
        workspace_root = tmp_dir / "workspace"
        workspace_root.mkdir(parents=True)

        with patch(
            "agent.core.agent_runtime.ToolLoader.load_all",
            lambda self: [],
        ), patch(
            "agent.core.agent_runtime.LLMClient.from_profile",
            side_effect=lambda profile_name=None: object(),
        ):
            agent = AgentRuntime(workspace_root=str(workspace_root))

        agent.history = [{"role": "user", "content": "hello"}]
        payload = agent.get_session_log_data()

        assert payload["history"] == [{"role": "user", "content": "hello"}]
        assert payload["available_tools"] == 0
        assert "system_prompt" in payload
        assert payload["workspace"] == str(workspace_root.resolve())
        assert not hasattr(agent, "session_id")
        assert not hasattr(agent, "logs_dir")
        assert not hasattr(agent, "input_dir")
    finally:
        cleanup_test_dir(tmp_dir)


def test_agent_runtime_uses_selected_llm_profile():
    tmp_dir = make_test_dir("core-agent-profile")
    try:
        workspace_root = tmp_dir / "workspace"
        workspace_root.mkdir(parents=True)
        captured = {}

        class DummyLLM:
            pass

        def fake_from_profile(profile_name=None):
            captured["profile_name"] = profile_name
            return DummyLLM()

        with patch("agent.core.agent_runtime.ToolLoader.load_all",
            lambda self: [],
        ), patch(
            "agent.core.agent_runtime.LLMClient.from_profile",
            side_effect=fake_from_profile,
        ):
            agent = AgentRuntime(workspace_root=str(workspace_root), llm_profile_name="kimi-fast")

        assert captured["profile_name"] == "kimi-fast"
        assert isinstance(agent.llm, DummyLLM)
    finally:
        cleanup_test_dir(tmp_dir)


def test_agent_runtime_handle_delegates_to_agent_loop():
    tmp_dir = make_test_dir("core-agent-handle")
    try:
        workspace_root = tmp_dir / "workspace"
        workspace_root.mkdir(parents=True)

        class DummyLoop:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.history = kwargs["history"]

            def run(self, user_input):
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": f"handled:{user_input}"})
                return f"handled:{user_input}"

        with patch("agent.core.agent_runtime.ToolLoader.load_all", lambda self: []), patch(
            "agent.core.agent_runtime.LLMClient.from_profile",
            side_effect=lambda profile_name=None: object(),
        ), patch(
            "agent.core.agent_runtime.AgentLoop",
            DummyLoop,
        ):
            agent = AgentRuntime(workspace_root=str(workspace_root))
            response = agent.handle("hello runtime")

        assert response.content == "handled:hello runtime"
        assert response.session_id == "runtime:local"
        assert agent.history[0] == {"role": "user", "content": "hello runtime"}
        assert agent.history[-1] == {"role": "assistant", "content": "handled:hello runtime"}
    finally:
        cleanup_test_dir(tmp_dir)


def test_agent_runtime_records_auto_compaction_event_before_handling_turn(capsys):
    tmp_dir = make_test_dir("core-agent-auto-compact")
    try:
        workspace_root = tmp_dir / "workspace"
        workspace_root.mkdir(parents=True)
        events_dir = tmp_dir / "events"

        class DummyLoop:
            def __init__(self, **kwargs):
                self.history = kwargs["history"]

            def run(self, user_input):
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": "done"})
                return "done"

        class FakeContextManager:
            def should_compress(self, history):
                return True

            def compress_history_with_result(self, history, *, trigger, allow_fallback):
                assert trigger == "auto-threshold"
                assert allow_fallback is True
                return ContextCompressionResult(
                    trigger=trigger,
                    history=[{"role": "user", "content": "## 当前状态\n- 自动摘要。"}],
                    summary="## 当前状态\n- 自动摘要。",
                    before_message_count=len(history),
                    after_message_count=1,
                    before_tokens=100,
                    after_tokens=20,
                    success=True,
                    fallback=False,
                    error=None,
                )

        with patch("agent.core.agent_runtime.ToolLoader.load_all", lambda self: []), patch(
            "agent.core.agent_runtime.LLMClient.from_profile",
            side_effect=lambda profile_name=None: object(),
        ), patch(
            "agent.core.agent_runtime.AgentLoop",
            DummyLoop,
        ):
            agent = AgentRuntime(workspace_root=str(workspace_root), events_dir=str(events_dir))
            agent.history = [{"role": "user", "content": "old"}]
            agent.context_manager = FakeContextManager()
            response = agent.handle(RuntimeRequest(content="new", session_id="abc123"))

        assert response.content == "done"
        assert agent.runtime_events[0]["type"] == "context_compacted"
        assert agent.runtime_events[0]["summary"] == "## 当前状态\n- 自动摘要。"
        assert agent.get_session_log_data()["events"][0]["summary"] == "## 当前状态\n- 自动摘要。"
        records = _read_event_records(events_dir / "abc123.jsonl")
        assert records[0]["type"] == "context_compacted"
        assert records[0]["event"]["trigger"] == "auto-threshold"
        assert "自动摘要" in capsys.readouterr().out
    finally:
        cleanup_test_dir(tmp_dir)


def test_agent_runtime_records_auto_compaction_fallback_without_summary(capsys):
    tmp_dir = make_test_dir("core-agent-auto-compact-fallback")
    try:
        workspace_root = tmp_dir / "workspace"
        workspace_root.mkdir(parents=True)
        events_dir = tmp_dir / "events"

        class DummyLoop:
            def __init__(self, **kwargs):
                self.history = kwargs["history"]

            def run(self, user_input):
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": "done"})
                return "done"

        class FakeContextManager:
            def should_compress(self, history):
                return True

            def compress_history_with_result(self, history, *, trigger, allow_fallback):
                return ContextCompressionResult(
                    trigger=trigger,
                    history=[{"role": "user", "content": "recent only"}],
                    summary="",
                    before_message_count=len(history),
                    after_message_count=1,
                    before_tokens=1000,
                    after_tokens=100,
                    success=False,
                    fallback=True,
                    error="summary failed",
                )

        with patch("agent.core.agent_runtime.ToolLoader.load_all", lambda self: []), patch(
            "agent.core.agent_runtime.LLMClient.from_profile",
            side_effect=lambda profile_name=None: object(),
        ), patch(
            "agent.core.agent_runtime.AgentLoop",
            DummyLoop,
        ):
            agent = AgentRuntime(workspace_root=str(workspace_root), events_dir=str(events_dir))
            agent.history = [{"role": "user", "content": "old"}]
            agent.context_manager = FakeContextManager()
            response = agent.handle(RuntimeRequest(content="new", session_id="abc123"))

        assert response.content == "done"
        event = agent.runtime_events[0]
        assert event["type"] == "context_compaction_failed"
        assert event["fallback"] is True
        assert event["summary"] == ""
        assert event["error"] == "summary failed"
        records = _read_event_records(events_dir / "abc123.jsonl")
        assert records[0]["type"] == "context_compaction_failed"
        assert records[0]["event"]["fallback"] is True
        assert records[0]["event"]["summary"] == ""
        out = capsys.readouterr().out
        assert "fallback" in out
        assert "summary failed" in out
    finally:
        cleanup_test_dir(tmp_dir)
