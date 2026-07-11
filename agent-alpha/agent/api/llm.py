import random
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, Optional

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from agent.api.llm_profiles import LLMProfile, build_llm_profile_from_settings, load_llm_profile
from agent.core.config import LLM_MAX_TOKENS
from agent.errors import LLMInterrupted, LLMInvalidResponse


class LLMClient:
    RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError, LLMInvalidResponse)
    MAX_ATTEMPTS = 2
    BASE_RETRY_DELAY_SECONDS = 1.0

    def __init__(self, profile: LLMProfile):
        self.profile = profile
        self.client = self._new_client()
        self.model_name = profile.model
        self.event_callback: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
        self.stream_responses = False
        self.interrupt_event: threading.Event | None = None
        self._active_stream: Any | None = None
        self._cancel_requested = False
        self._request_lock = threading.RLock()

    @classmethod
    def from_profile(cls, profile_name: str | None = None) -> "LLMClient":
        return cls(load_llm_profile(profile_name))

    @classmethod
    def from_settings(cls, settings: dict[str, Any], profile_name: str | None = None) -> "LLMClient":
        profile = build_llm_profile_from_settings(settings, profile_name or "runtime")
        if profile is None:
            return cls.from_profile(profile_name)
        return cls(profile)

    def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        completion = self._create_completion_with_retry(
            {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self._resolve_max_tokens(max_tokens),
            },
            has_tools=False,
        )
        return completion.choices[0].message.content

    def generate_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: int | None = None,
    ) -> Any:
        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self._resolve_max_tokens(max_tokens),
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return self._create_completion_with_retry(kwargs, has_tools=bool(tools))

    def set_interrupt_event(self, interrupt_event: threading.Event | None) -> None:
        self.interrupt_event = interrupt_event

    def cancel_current_request(self) -> None:
        with self._request_lock:
            stream = self._active_stream
            self._cancel_requested = stream is not None
        self._close_resource(stream)
        self._refresh_client()

    def _new_client(self):
        return OpenAI(
            base_url=self.profile.base_url,
            api_key=self.profile.api_key,
            max_retries=0,
            timeout=60.0,
        )

    def _create_completion_with_retry(self, kwargs: dict[str, Any], *, has_tools: bool) -> Any:
        for attempt in range(self.MAX_ATTEMPTS):
            attempt_number = attempt + 1
            started_at = time.monotonic()
            self._emit_event(
                "llm_request_started",
                kwargs,
                attempt=attempt_number,
                elapsed_seconds=0.0,
                has_tools=has_tools,
            )
            try:
                response = (
                    self._create_streaming_completion(kwargs)
                    if self.stream_responses
                    else self.client.chat.completions.create(**kwargs)
                )
                diagnostics = self._validate_completion(response)
                self._emit_event(
                    "llm_request_succeeded",
                    kwargs,
                    attempt=attempt_number,
                    elapsed_seconds=time.monotonic() - started_at,
                    has_tools=has_tools,
                )
                return response
            except LLMInterrupted:
                self._emit_event(
                    "llm_request_interrupted",
                    kwargs,
                    attempt=attempt_number,
                    elapsed_seconds=time.monotonic() - started_at,
                    has_tools=has_tools,
                    response_diagnostics=diagnostics,
                )
                self._refresh_client()
                raise
            except self.RETRYABLE_ERRORS as exc:
                elapsed_seconds = time.monotonic() - started_at
                callback_result = self._emit_event(
                    "llm_request_failed",
                    kwargs,
                    attempt=attempt_number,
                    elapsed_seconds=elapsed_seconds,
                    has_tools=has_tools,
                    error=exc,
                )
                if attempt_number >= self.MAX_ATTEMPTS:
                    self._emit_event(
                        "llm_request_exhausted",
                        kwargs,
                        attempt=attempt_number,
                        elapsed_seconds=elapsed_seconds,
                        has_tools=has_tools,
                        error=exc,
                    )
                    raise

                delay = self.BASE_RETRY_DELAY_SECONDS * (2**attempt)
                self._refresh_client()
                if isinstance(callback_result, dict) and callback_result.get("retry_messages") is not None:
                    kwargs = {**kwargs, "messages": callback_result["retry_messages"]}
                self._emit_event(
                    "llm_retry_scheduled",
                    kwargs,
                    attempt=attempt_number,
                    elapsed_seconds=elapsed_seconds,
                    has_tools=has_tools,
                    error=exc,
                    client_refreshed=True,
                    slow_connection_recovery_injected=bool(
                        isinstance(callback_result, dict)
                        and callback_result.get("slow_connection_recovery_injected")
                    ),
                )
                time.sleep(delay + random.uniform(0, 0.25))
            except Exception as exc:
                self._emit_event(
                    "llm_request_failed",
                    kwargs,
                    attempt=attempt_number,
                    elapsed_seconds=time.monotonic() - started_at,
                    has_tools=has_tools,
                    error=exc,
                )
                raise

        raise RuntimeError("LLM retry loop exited unexpectedly")

    def _create_streaming_completion(self, kwargs: dict[str, Any]) -> Any:
        self._raise_if_interrupted()
        stream = self.client.chat.completions.create(**kwargs, stream=True)
        with self._request_lock:
            self._active_stream = stream
            self._cancel_requested = False
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason = None
        chunk_count = 0

        try:
            for chunk in stream:
                self._raise_if_interrupted()
                chunk_count += 1
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                finish_reason = getattr(choice, "finish_reason", None) or finish_reason
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                content = getattr(delta, "content", None)
                if content:
                    content_parts.append(content)
                    self._emit_stream_event("assistant_delta", {"content": content})

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_parts.append(reasoning)

                for tool_delta in getattr(delta, "tool_calls", None) or []:
                    index = int(getattr(tool_delta, "index", 0) or 0)
                    current = tool_calls.setdefault(
                        index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    tool_id = getattr(tool_delta, "id", None)
                    if tool_id:
                        current["id"] = tool_id
                    tool_type = getattr(tool_delta, "type", None)
                    if tool_type:
                        current["type"] = tool_type
                    function = getattr(tool_delta, "function", None)
                    if function is not None:
                        name = getattr(function, "name", None)
                        if name:
                            current["function"]["name"] += name
                        arguments = getattr(function, "arguments", None)
                        if arguments:
                            current["function"]["arguments"] += arguments
        except Exception as exc:
            if self._is_interrupted():
                raise LLMInterrupted("LLM request interrupted") from exc
            raise
        finally:
            with self._request_lock:
                if self._active_stream is stream:
                    self._active_stream = None
                self._cancel_requested = False
            self._close_resource(stream)

        aggregated_tool_calls = [
            SimpleNamespace(
                id=value["id"],
                type=value["type"],
                function=SimpleNamespace(
                    name=value["function"]["name"],
                    arguments=value["function"]["arguments"],
                ),
            )
            for _, value in sorted(tool_calls.items())
            if value["function"]["name"]
        ]
        message = SimpleNamespace(
            content="".join(content_parts) or None,
            reasoning_content="".join(reasoning_parts) or None,
            tool_calls=aggregated_tool_calls,
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
            _stream_diagnostics={"chunk_count": chunk_count},
        )

    def refresh_client(self) -> None:
        """Refresh the provider client before a bounded recovery attempt."""
        self._refresh_client()

    def _validate_completion(self, response: Any) -> dict[str, Any]:
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise LLMInvalidResponse("LLM returned no choices", choice_count=0)
        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            raise LLMInvalidResponse("LLM returned no assistant message", choice_count=len(choices))
        content = getattr(message, "content", None)
        tool_calls = getattr(message, "tool_calls", None) or []
        reasoning = getattr(message, "reasoning_content", None)
        finish_reason = getattr(choice, "finish_reason", None)
        diagnostics = {
            "choice_count": len(choices),
            "finish_reason": finish_reason,
            "content_chars": len(content) if isinstance(content, str) else 0,
            "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0,
            "tool_calls_count": len(tool_calls),
            **dict(getattr(response, "_stream_diagnostics", {}) or {}),
        }
        if not (isinstance(content, str) and content.strip()) and not tool_calls:
            raise LLMInvalidResponse("LLM returned an empty assistant response", **diagnostics)
        return diagnostics

    def _emit_stream_event(self, event_type: str, event: dict[str, Any]) -> None:
        if self.event_callback is None:
            return
        payload = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "model": self.model_name,
            "profile": getattr(self.profile, "name", None),
            "provider": getattr(self.profile, "provider", None),
            **event,
        }
        self.event_callback(payload)

    def _refresh_client(self) -> None:
        try:
            self._close_resource(self.client)
        except Exception:
            pass
        self.client = self._new_client()

    def _is_interrupted(self) -> bool:
        return self._cancel_requested or bool(self.interrupt_event is not None and self.interrupt_event.is_set())

    def _raise_if_interrupted(self) -> None:
        if self._is_interrupted():
            raise LLMInterrupted("LLM request interrupted")

    @staticmethod
    def _close_resource(resource: Any | None) -> None:
        if resource is None:
            return
        close = getattr(resource, "close", None)
        if close is not None:
            close()

    def _resolve_max_tokens(self, max_tokens: int | None) -> int:
        if max_tokens is not None:
            return max_tokens
        return self.profile.max_tokens if self.profile.max_tokens is not None else LLM_MAX_TOKENS

    def _emit_event(
        self,
        event_type: str,
        kwargs: dict[str, Any],
        *,
        attempt: int,
        elapsed_seconds: float,
        has_tools: bool,
        error: Exception | None = None,
        client_refreshed: bool = False,
        slow_connection_recovery_injected: bool = False,
        response_diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self.event_callback is None:
            return None
        event = self._build_event(
            event_type,
            kwargs,
            attempt=attempt,
            elapsed_seconds=elapsed_seconds,
            has_tools=has_tools,
            error=error,
            client_refreshed=client_refreshed,
            slow_connection_recovery_injected=slow_connection_recovery_injected,
            response_diagnostics=response_diagnostics,
        )
        return self.event_callback(event)

    def _build_event(
        self,
        event_type: str,
        kwargs: dict[str, Any],
        *,
        attempt: int,
        elapsed_seconds: float,
        has_tools: bool,
        error: Exception | None,
        client_refreshed: bool,
        slow_connection_recovery_injected: bool,
        response_diagnostics: dict[str, Any] | None,
    ) -> dict[str, Any]:
        messages = kwargs.get("messages") or []
        tools = kwargs.get("tools") or []
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "attempt": attempt,
            "max_attempts": self.MAX_ATTEMPTS,
            "elapsed_seconds": round(float(elapsed_seconds), 3),
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
            "model": self.model_name,
            "profile": getattr(self.profile, "name", None),
            "provider": getattr(self.profile, "provider", None),
            "base_url": getattr(self.profile, "base_url", None),
            "max_tokens": kwargs.get("max_tokens"),
            "has_tools": has_tools,
            "tool_count": len(tools),
            "message_count": len(messages),
            "estimated_input_chars": self._estimate_messages_chars(messages),
            "client_refreshed": client_refreshed,
            "slow_connection_recovery_injected": slow_connection_recovery_injected,
        }
        if response_diagnostics:
            event.update(response_diagnostics)
        if isinstance(error, LLMInvalidResponse):
            event.update(error.diagnostics)
        return event

    def _estimate_messages_chars(self, messages: Any) -> int:
        if not isinstance(messages, list):
            return len(str(messages))
        total = 0
        for message in messages:
            if isinstance(message, dict):
                total += len(str(message.get("role", "")))
                total += len(str(message.get("content", "")))
                if message.get("tool_calls"):
                    total += len(str(message.get("tool_calls")))
                if message.get("tool_call_id"):
                    total += len(str(message.get("tool_call_id")))
                continue
            total += len(str(message))
        return total
