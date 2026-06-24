import random
import time
from datetime import datetime
from typing import Any, Callable, Optional

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from agent.api.llm_profiles import LLMProfile, load_llm_profile
from agent.core.config import LLM_MAX_TOKENS


class LLMClient:
    RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
    MAX_ATTEMPTS = 2
    BASE_RETRY_DELAY_SECONDS = 1.0

    def __init__(self, profile: LLMProfile):
        self.profile = profile
        self.client = self._new_client()
        self.model_name = profile.model
        self.event_callback: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None

    @classmethod
    def from_profile(cls, profile_name: str | None = None) -> "LLMClient":
        return cls(load_llm_profile(profile_name))

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

    def _new_client(self):
        return OpenAI(
            base_url=self.profile.base_url,
            api_key=self.profile.api_key,
            max_retries=0,
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
                response = self.client.chat.completions.create(**kwargs)
                self._emit_event(
                    "llm_request_succeeded",
                    kwargs,
                    attempt=attempt_number,
                    elapsed_seconds=time.monotonic() - started_at,
                    has_tools=has_tools,
                )
                return response
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

    def _refresh_client(self) -> None:
        try:
            close = getattr(self.client, "close", None)
            if close is not None:
                close()
        except Exception:
            pass
        self.client = self._new_client()

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
