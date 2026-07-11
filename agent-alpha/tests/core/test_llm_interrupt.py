from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from agent.api.llm import LLMClient
from agent.errors import LLMInterrupted


class BlockingStream:
    def __init__(self):
        self.closed = threading.Event()
        self.close_count = 0

    def __iter__(self):
        return self

    def __next__(self):
        while not self.closed.wait(0.01):
            pass
        raise RuntimeError("stream closed")

    def close(self):
        self.close_count += 1
        self.closed.set()


class ListStream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self.close_count = 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self):
        self.close_count += 1


class FakeCompletions:
    def __init__(self, stream):
        self.stream = stream

    def create(self, **_kwargs):
        return self.stream


class FakeClient:
    def __init__(self, stream=None):
        self.chat = SimpleNamespace(completions=FakeCompletions(stream))
        self.closed = False

    def close(self):
        self.closed = True


def make_client(stream):
    client = LLMClient.__new__(LLMClient)
    client.profile = SimpleNamespace(
        name="test",
        provider="test",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
        max_tokens=128,
    )
    client.client = FakeClient(stream)
    client.model_name = "model"
    client.event_callback = None
    client.stream_responses = True
    client.interrupt_event = None
    client._active_stream = None
    client._cancel_requested = False
    client._request_lock = threading.RLock()
    client._new_client = lambda: FakeClient()
    return client


def text_chunk(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=None,
                delta=SimpleNamespace(content=content, tool_calls=[]),
            )
        ]
    )


def test_cancel_current_request_closes_active_stream_and_interrupts():
    stream = BlockingStream()
    client = make_client(stream)
    error: list[BaseException] = []

    def run_with_capture():
        try:
            client._create_streaming_completion({"messages": []})
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=run_with_capture, daemon=True)
    thread.start()
    deadline = time.monotonic() + 1
    while client._active_stream is None and time.monotonic() < deadline:
        time.sleep(0.01)

    client.cancel_current_request()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert stream.close_count >= 1
    assert any(isinstance(exc, LLMInterrupted) for exc in error)


def test_finished_stream_is_not_marked_interrupted():
    stream = ListStream([text_chunk("hello")])
    client = make_client(stream)

    result = client._create_streaming_completion({"messages": []})

    assert result.choices[0].message.content == "hello"
    assert result.choices[0].message.tool_calls == []
    assert stream.close_count == 1


def test_interrupt_event_before_stream_raises_without_opening_stream():
    stream = ListStream([text_chunk("hello")])
    client = make_client(stream)
    event = threading.Event()
    event.set()
    client.set_interrupt_event(event)

    with pytest.raises(LLMInterrupted):
        client._create_streaming_completion({"messages": []})

    assert client._active_stream is None
    assert stream.close_count == 0


def test_empty_stream_is_retried_and_never_returned_as_success():
    streams = iter([ListStream([]), ListStream([text_chunk("recovered")])])

    class SequencedCompletions:
        def create(self, **_kwargs):
            return next(streams)

    client = make_client(None)
    client.client.chat.completions = SequencedCompletions()
    client._refresh_client = lambda: None

    response = client._create_completion_with_retry({"messages": []}, has_tools=False)

    assert response.choices[0].message.content == "recovered"


def test_stream_preserves_reasoning_diagnostics_even_without_final_content():
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                delta=SimpleNamespace(content=None, reasoning_content="thinking", tool_calls=[]),
            )
        ]
    )
    client = make_client(ListStream([chunk]))

    response = client._create_streaming_completion({"messages": []})

    assert response.choices[0].message.content is None
    assert response.choices[0].message.reasoning_content == "thinking"
    assert response._stream_diagnostics["chunk_count"] == 1
