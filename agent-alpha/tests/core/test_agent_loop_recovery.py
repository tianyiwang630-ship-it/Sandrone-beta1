from types import SimpleNamespace

from agent.core.agent_loop import AgentLoop
from agent.errors import LLMInvalidResponse


class AlwaysInvalidLLM:
    def __init__(self):
        self.profile = SimpleNamespace(provider="test", name="test", max_tokens=100)
        self.calls = 0
        self.refreshes = 0
        self.event_callback = None

    def generate_with_tools(self, **_kwargs):
        self.calls += 1
        raise LLMInvalidResponse("empty")

    def refresh_client(self):
        self.refreshes += 1


class NoopToolLoader:
    def execute_tool(self, _name, _arguments):
        raise AssertionError("no tool should execute")


def test_recovery_exhaustion_keeps_user_message_and_never_appends_empty_assistant():
    llm = AlwaysInvalidLLM()
    history = []
    loop = AgentLoop(
        llm=llm,
        tools=[],
        tool_loader=NoopToolLoader(),
        history=history,
        system_prompt="system",
        max_turns=2,
        request_id="req",
    )

    response = loop.run("hello")

    assert response == loop.RECOVERABLE_RESPONSE
    assert loop.was_recoverable is True
    assert history == [{"role": "user", "content": "hello"}]
    assert llm.calls == 3
    assert llm.refreshes == 2
