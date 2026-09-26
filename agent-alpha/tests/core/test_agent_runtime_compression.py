import threading
from types import SimpleNamespace

from agent.core.agent_runtime import AgentRuntime
from agent.core.runtime_types import RuntimeRequest


def test_handle_clears_stale_interrupt_and_auto_compaction_allows_fallback(monkeypatch):
    captured: dict[str, object] = {}

    class FakeLogWriter:
        def __init__(self):
            self.events = []
            self.commits = 0

        def write_session_header(self, event):
            self.events.append("session_started")

        def write_event(self, kind, event, **kwargs):
            self.events.append(kind)

        def commit_cycle(self):
            self.commits += 1

    log_writer = FakeLogWriter()

    class FakeContextManager:
        def should_compress(self, history):
            captured["history_seen_by_should_compress"] = [dict(item) for item in history]
            return True

    class FakeAgentLoop:
        def __init__(self, **kwargs):
            captured["loop_interrupt_is_set"] = kwargs["interrupt_event"].is_set()
            self.log_writer = kwargs["log_writer"]
            self.was_interrupted = False

        def run(self, content):
            captured["loop_content"] = content
            self.log_writer.write_event("llm_input", {})
            self.log_writer.write_event("llm_response", {})
            self.log_writer.write_event("llm_input", {})
            self.log_writer.write_event("llm_response", {})
            return "ok"

    monkeypatch.setattr("agent.core.agent_runtime.AgentLoop", FakeAgentLoop)

    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.history = [{"role": "user", "content": "old"}]
    runtime.runtime_events = []
    runtime.runtime_events_dir = None
    runtime.workspace_root = __import__("pathlib").Path(".").resolve()
    runtime.session_created_at = None
    runtime.context_manager = FakeContextManager()
    runtime.llm = SimpleNamespace(set_interrupt_event=lambda event: None)
    runtime.tools = []
    runtime.tool_loader = SimpleNamespace(set_interrupt_event=lambda event: None)
    runtime.system_prompt = "system"
    runtime.max_turns = 10
    runtime._interrupted = threading.Event()
    runtime._interrupted.set()

    def fake_compact_history(*, trigger, allow_fallback):
        captured["compact_interrupt_is_set"] = runtime._interrupted.is_set()
        captured["compact_trigger"] = trigger
        captured["compact_allow_fallback"] = allow_fallback
        return SimpleNamespace(success=False, fallback=False, error="network down")

    runtime.compact_history = fake_compact_history
    runtime._record_compression_event = lambda result, event_writer=None, log_writer=None, request_id=None: None
    runtime._print_compression_result = lambda result: None
    runtime._create_event_writer = lambda _session_id: None
    runtime._create_log_writer = lambda _session_id: log_writer

    response = AgentRuntime.handle(runtime, RuntimeRequest(content="hello", session_id="sess1"))

    assert response.content == "ok"
    assert captured["compact_interrupt_is_set"] is False
    assert captured["compact_allow_fallback"] is True
    assert captured["compact_trigger"] == "auto-threshold"
    assert captured["loop_interrupt_is_set"] is False
    assert runtime.history == [{"role": "user", "content": "old"}]
    assert log_writer.commits == 1
    assert log_writer.events.count("llm_input") == 2
