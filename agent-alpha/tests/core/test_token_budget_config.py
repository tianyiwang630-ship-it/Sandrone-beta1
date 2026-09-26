import json

from agent.api.llm_profiles import LLM_PROFILES_PATH
from agent.core.config import COMPRESSION_THRESHOLD, LLM_MAX_TOKENS, MAX_CONTEXT_TOKENS


def test_default_token_budgets_match_runtime_limits():
    assert MAX_CONTEXT_TOKENS == 600_000
    assert COMPRESSION_THRESHOLD == 0.8
    assert LLM_MAX_TOKENS == 300_000


def test_deepseek_profiles_use_300k_output_without_changing_other_providers():
    profiles = json.loads(LLM_PROFILES_PATH.read_text(encoding="utf-8"))["profiles"]

    assert profiles["deepseek-flash"]["max_tokens"] == 300_000
    assert profiles["deepseek-pro"]["max_tokens"] == 300_000
    assert profiles["glm"]["max_tokens"] == 32_000
    assert profiles["minimax"]["max_tokens"] == 32_000
