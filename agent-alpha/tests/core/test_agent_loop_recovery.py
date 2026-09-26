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


class AlwaysTruncatedLLM:
    def __init__(self):
        self.profile = SimpleNamespace(provider="test", name="test", max_tokens=300000)
        self.calls = []
        self.refreshes = 0
        self.event_callback = None

    def generate_with_tools(self, **kwargs):
        self.calls.append(kwargs["messages"])
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="unfinished", tool_calls=[]),
                    finish_reason="length",
                )
            ]
        )

    def refresh_client(self):
        self.refreshes += 1


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


def test_output_truncation_retries_twice_then_stops_current_turn_without_poisoning_history():
    llm = AlwaysTruncatedLLM()
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

    response = loop.run("large task")

    assert response == loop.OUTPUT_TRUNCATED_RESPONSE
    assert loop.was_recoverable is True
    assert history == [{"role": "user", "content": "large task"}]
    assert len(llm.calls) == 3
    assert llm.refreshes == 2
    assert "输出长度达到上限" in llm.calls[1][1]["content"]
    assert "上一次恢复仍因输出过长" in llm.calls[2][1]["content"]
