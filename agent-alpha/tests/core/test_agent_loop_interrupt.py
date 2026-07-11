from __future__ import annotations

import threading
from types import SimpleNamespace

from agent.core.agent_loop import AgentLoop
from agent.errors import LLMInterrupted


class InterruptingLLM:
    def __init__(self):
        self.profile = SimpleNamespace(provider="test", max_tokens=128)
        self.event_callback = None
        self.cancelled = False

    def generate_with_tools(self, **_kwargs):
        raise LLMInterrupted("stopped")

    def cancel_current_request(self):
        self.cancelled = True


def test_llm_interrupt_does_not_append_partial_assistant_message():
    interrupt_event = threading.Event()
    history: list[dict] = []
    llm = InterruptingLLM()
    loop = AgentLoop(
        llm=llm,
        tools=[],
        tool_loader=SimpleNamespace(execute_tool=lambda _name, _args: None),
        history=history,
        system_prompt="system",
        max_turns=3,
        interrupt_event=interrupt_event,
    )

    result = loop.run("hello")

    assert result == AgentLoop.INTERRUPTED_RESPONSE
    assert loop.was_interrupted is True
    assert history == [{"role": "user", "content": "hello"}]
