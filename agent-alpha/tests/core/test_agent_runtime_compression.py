import threading
from types import SimpleNamespace

from agent.core.agent_runtime import AgentRuntime
from agent.core.runtime_types import RuntimeRequest


def test_handle_clears_stale_interrupt_and_auto_compaction_allows_fallback(monkeypatch):
    captured: dict[str, object] = {}

    class FakeContextManager:
        def should_compress(self, history):
            captured["history_seen_by_should_compress"] = [dict(item) for item in history]
            return True

    class FakeAgentLoop:
        def __init__(self, **kwargs):
            captured["loop_interrupt_is_set"] = kwargs["interrupt_event"].is_set()
            self.was_interrupted = False

        def run(self, content):
            captured["loop_content"] = content
            return "ok"

    monkeypatch.setattr("agent.core.agent_runtime.AgentLoop", FakeAgentLoop)

    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.history = [{"role": "user", "content": "old"}]
    runtime.runtime_events = []
    runtime.runtime_events_dir = None
    runtime.context_manager = FakeContextManager()
    runtime.llm = object()
    runtime.tools = []
    runtime.tool_loader = object()
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

    response = AgentRuntime.handle(runtime, RuntimeRequest(content="hello", session_id="sess1"))

    assert response.content == "ok"
    assert captured["compact_interrupt_is_set"] is False
    assert captured["compact_allow_fallback"] is True
    assert captured["compact_trigger"] == "auto-threshold"
    assert captured["loop_interrupt_is_set"] is False
    assert runtime.history == [{"role": "user", "content": "old"}]
