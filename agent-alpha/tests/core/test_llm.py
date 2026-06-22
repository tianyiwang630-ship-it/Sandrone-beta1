from agent.core.agent_loop import AgentLoop  # noqa: F401 - initialize the existing package import order
from agent.api.llm import LLMClient
from agent.api.llm_profiles import LLMProfile


class RecordingCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = type("Message", (), {"content": "ok"})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class RecordingClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": RecordingCompletions()})()


def _client(max_tokens=32000) -> LLMClient:
    client = LLMClient(
        LLMProfile(
            name="test",
            provider="openai",
            base_url="https://example.test/v1",
            api_key="secret",
            model="test-model",
            max_tokens=max_tokens,
        )
    )
    client.client = RecordingClient()
    return client


def test_generate_with_tools_uses_profile_max_tokens_by_default():
    client = _client()

    client.generate_with_tools(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert client.client.chat.completions.calls[0]["max_tokens"] == 32000


def test_generate_explicit_max_tokens_overrides_profile_for_summaries():
    client = _client()

    client.generate("summarize", max_tokens=6000)

    assert client.client.chat.completions.calls[0]["max_tokens"] == 6000


def test_generate_with_tools_falls_back_to_global_max_when_profile_omits_it():
    client = _client(max_tokens=None)

    client.generate_with_tools(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert client.client.chat.completions.calls[0]["max_tokens"] == 20000
