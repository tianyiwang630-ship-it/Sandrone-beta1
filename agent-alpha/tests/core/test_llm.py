from agent.core.agent_loop import AgentLoop  # noqa: F401 - initialize the existing package import order
from agent.api.llm import LLMClient
from agent.api.llm_profiles import LLMProfile
import pytest
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError


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


class FlakyCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FlakyClient:
    def __init__(self, completions):
        self.chat = type("Chat", (), {"completions": completions})()


class RetryableTestError(Exception):
    pass


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


def _ok_response(content="ok"):
    message = type("Message", (), {"content": content})()
    choice = type("Choice", (), {"message": message})()
    return type("Response", (), {"choices": [choice]})()


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


def test_generate_with_tools_retries_transient_connection_error(monkeypatch):
    client = _client()
    first = FlakyCompletions([APIConnectionError(request=None)])
    second = FlakyCompletions([_ok_response("ok")])
    client.client = FlakyClient(first)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "_new_client", lambda: FlakyClient(second), raising=False)

    response = client.generate_with_tools(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert response.choices[0].message.content == "ok"
    assert len(first.calls) == 1
    assert len(second.calls) == 1


def test_generate_with_tools_refreshes_client_before_retry(monkeypatch):
    client = _client()
    first = FlakyCompletions([APIConnectionError(request=None)])
    second = FlakyCompletions([_ok_response("ok")])
    first_client = FlakyClient(first)
    second_client = FlakyClient(second)
    client.client = first_client
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "_new_client", lambda: second_client)

    response = client.generate_with_tools(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert response.choices[0].message.content == "ok"
    assert client.client is second_client
    assert len(first.calls) == 1
    assert len(second.calls) == 1


def test_generate_with_tools_refreshes_client_for_any_retryable_error(monkeypatch):
    client = _client()
    first = FlakyCompletions([RetryableTestError("temporary upstream failure")])
    second = FlakyCompletions([_ok_response("ok")])
    second_client = FlakyClient(second)
    client.client = FlakyClient(first)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "RETRYABLE_ERRORS", (RetryableTestError,), raising=False)
    monkeypatch.setattr(client, "_new_client", lambda: second_client, raising=False)

    response = client.generate_with_tools(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert response.choices[0].message.content == "ok"
    assert client.client is second_client
    assert len(first.calls) == 1
    assert len(second.calls) == 1


def test_generate_with_tools_raises_after_retry_budget(monkeypatch):
    client = _client()
    clients = [
        FlakyClient(FlakyCompletions([APIConnectionError(request=None)])),
        FlakyClient(FlakyCompletions([APIConnectionError(request=None)])),
        FlakyClient(FlakyCompletions([APIConnectionError(request=None)])),
    ]
    client.client = clients[0]
    refreshes = iter(clients[1:])
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "_new_client", lambda: next(refreshes), raising=False)

    with pytest.raises(APIConnectionError):
        client.generate_with_tools(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert [len(item.chat.completions.calls) for item in clients] == [1, 1, 1]


def test_generate_with_tools_does_not_retry_non_retryable_error(monkeypatch):
    client = _client()
    completions = FlakyCompletions([ValueError("bad request shape"), _ok_response("should not run")])
    client.client = FlakyClient(completions)
    refresh_calls = []
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "_new_client", lambda: refresh_calls.append("refresh"), raising=False)

    with pytest.raises(ValueError, match="bad request shape"):
        client.generate_with_tools(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert len(completions.calls) == 1
    assert refresh_calls == []


def test_generate_retries_transient_connection_error(monkeypatch):
    client = _client()
    first = FlakyCompletions([APIConnectionError(request=None)])
    second = FlakyCompletions([_ok_response("summary")])
    client.client = FlakyClient(first)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "_new_client", lambda: FlakyClient(second), raising=False)

    assert client.generate("summarize", max_tokens=6000) == "summary"
    assert len(first.calls) == 1
    assert len(second.calls) == 1


def test_generate_raises_after_retry_budget_and_refreshes_each_retry(monkeypatch):
    client = _client()
    clients = [
        FlakyClient(FlakyCompletions([APIConnectionError(request=None)])),
        FlakyClient(FlakyCompletions([APIConnectionError(request=None)])),
        FlakyClient(FlakyCompletions([APIConnectionError(request=None)])),
    ]
    client.client = clients[0]
    refreshes = iter(clients[1:])
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "_new_client", lambda: next(refreshes))

    with pytest.raises(APIConnectionError):
        client.generate("summarize", max_tokens=6000)

    assert [len(item.chat.completions.calls) for item in clients] == [1, 1, 1]


def test_retryable_errors_include_openai_transient_failures():
    assert APIConnectionError in LLMClient.RETRYABLE_ERRORS
    assert APITimeoutError in LLMClient.RETRYABLE_ERRORS
    assert RateLimitError in LLMClient.RETRYABLE_ERRORS
    assert InternalServerError in LLMClient.RETRYABLE_ERRORS


def test_new_client_disables_sdk_internal_retries(monkeypatch):
    captured = {}

    def build_openai(**kwargs):
        captured.update(kwargs)
        return RecordingClient()

    monkeypatch.setattr("agent.api.llm.OpenAI", build_openai)

    LLMClient(
        LLMProfile(
            name="test",
            provider="openai",
            base_url="https://example.test/v1",
            api_key="secret",
            model="test-model",
        )
    )

    assert captured["max_retries"] == 0
