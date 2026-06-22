import random
import time
from typing import Any, Optional

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from agent.api.llm_profiles import LLMProfile, load_llm_profile
from agent.core.config import LLM_MAX_TOKENS


class LLMClient:
    RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
    MAX_ATTEMPTS = 3
    BASE_RETRY_DELAY_SECONDS = 1.0

    def __init__(self, profile: LLMProfile):
        self.profile = profile
        self.client = self._new_client()
        self.model_name = profile.model

    @classmethod
    def from_profile(cls, profile_name: str | None = None) -> "LLMClient":
        return cls(load_llm_profile(profile_name))

    def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        completion = self._create_completion_with_retry(
            {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self._resolve_max_tokens(max_tokens),
            }
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

        return self._create_completion_with_retry(kwargs)

    def _new_client(self):
        return OpenAI(
            base_url=self.profile.base_url,
            api_key=self.profile.api_key,
            max_retries=0,
        )

    def _create_completion_with_retry(self, kwargs: dict[str, Any]) -> Any:
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                return self.client.chat.completions.create(**kwargs)
            except self.RETRYABLE_ERRORS:
                if attempt + 1 >= self.MAX_ATTEMPTS:
                    raise

                delay = self.BASE_RETRY_DELAY_SECONDS * (2**attempt)
                time.sleep(delay + random.uniform(0, 0.25))
                self._refresh_client()

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
