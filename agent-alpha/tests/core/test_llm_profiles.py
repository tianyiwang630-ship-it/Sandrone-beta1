import json
from pathlib import Path

import pytest

from tests.conftest import cleanup_test_dir, make_test_dir
from agent.core.agent_loop import AgentLoop  # noqa: F401 - initialize the existing package import order
from agent.api.llm_profiles import LLMProfile, load_llm_profile


def test_load_llm_profile_uses_default_profile(monkeypatch):
    tmp_dir = make_test_dir("llm-profiles")
    try:
        config_dir = tmp_dir / "config"
        config_dir.mkdir(parents=True)
        profile_file = config_dir / "llm_profiles.json"
        profile_file.write_text(
            json.dumps(
                {
                    "default": "kimi-fast",
                    "profiles": {
                        "kimi-fast": {
                            "provider": "kimi",
                            "base_url": "https://kimi.example/v1",
                            "api_key_env": "TEST_KIMI_API_KEY",
                            "model": "kimi-k2",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("agent.api.llm_profiles.LLM_PROFILES_PATH", profile_file)
        monkeypatch.setenv("TEST_KIMI_API_KEY", "kimi-secret")

        profile = load_llm_profile()

        assert profile == LLMProfile(
            name="kimi-fast",
            provider="kimi",
            base_url="https://kimi.example/v1",
            api_key="kimi-secret",
            model="kimi-k2",
        )
    finally:
        cleanup_test_dir(tmp_dir)


def test_load_llm_profile_by_name(monkeypatch):
    tmp_dir = make_test_dir("llm-profile-select")
    try:
        config_dir = tmp_dir / "config"
        config_dir.mkdir(parents=True)
        profile_file = config_dir / "llm_profiles.json"
        profile_file.write_text(
            json.dumps(
                {
                    "default": "openai-main",
                    "profiles": {
                        "openai-main": {
                            "provider": "openai",
                            "base_url": "https://api.openai.com/v1",
                            "api_key_env": "TEST_OPENAI_API_KEY",
                            "model": "gpt-4.1",
                        },
                        "glm-main": {
                            "provider": "zhipu",
                            "base_url": "https://glm.example/v1",
                            "api_key_env": "TEST_GLM_API_KEY",
                            "model": "glm-4.5",
                            "max_tokens": 32000,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("agent.api.llm_profiles.LLM_PROFILES_PATH", profile_file)
        monkeypatch.setenv("TEST_OPENAI_API_KEY", "openai-secret")
        monkeypatch.setenv("TEST_GLM_API_KEY", "glm-secret")

        profile = load_llm_profile("glm-main")

        assert profile.name == "glm-main"
        assert profile.provider == "zhipu"
        assert profile.base_url == "https://glm.example/v1"
        assert profile.api_key == "glm-secret"
        assert profile.model == "glm-4.5"
        assert profile.max_tokens == 32000
    finally:
        cleanup_test_dir(tmp_dir)


def test_load_llm_profile_requires_api_key_env(monkeypatch):
    tmp_dir = make_test_dir("llm-profile-missing-key")
    try:
        config_dir = tmp_dir / "config"
        config_dir.mkdir(parents=True)
        profile_file = config_dir / "llm_profiles.json"
        profile_file.write_text(
            json.dumps(
                {
                    "default": "openai-main",
                    "profiles": {
                        "openai-main": {
                            "provider": "openai",
                            "base_url": "https://api.openai.com/v1",
                            "api_key_env": "MISSING_OPENAI_API_KEY",
                            "model": "gpt-4.1",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("agent.api.llm_profiles.LLM_PROFILES_PATH", profile_file)
        monkeypatch.delenv("MISSING_OPENAI_API_KEY", raising=False)

        with pytest.raises(ValueError, match="MISSING_OPENAI_API_KEY"):
            load_llm_profile()
    finally:
        cleanup_test_dir(tmp_dir)


def test_load_llm_profile_uses_global_token_fallback_when_omitted(monkeypatch):
    tmp_dir = make_test_dir("llm-profile-token-fallback")
    try:
        profile_file = tmp_dir / "llm_profiles.json"
        profile_file.write_text(
            json.dumps(
                {
                    "default": "fallback",
                    "profiles": {
                        "fallback": {
                            "provider": "openai",
                            "base_url": "https://example.test/v1",
                            "api_key_env": "TEST_FALLBACK_API_KEY",
                            "model": "fallback-model",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("agent.api.llm_profiles.LLM_PROFILES_PATH", profile_file)
        monkeypatch.setenv("TEST_FALLBACK_API_KEY", "secret")

        assert load_llm_profile().max_tokens is None
    finally:
        cleanup_test_dir(tmp_dir)


@pytest.mark.parametrize("invalid_value", [0, -1, True, "32000", 32.5, None])
def test_load_llm_profile_rejects_invalid_max_tokens(monkeypatch, invalid_value):
    tmp_dir = make_test_dir(f"llm-profile-invalid-token-{type(invalid_value).__name__}-{invalid_value}")
    try:
        profile_file = tmp_dir / "llm_profiles.json"
        profile_file.write_text(
            json.dumps(
                {
                    "default": "invalid",
                    "profiles": {
                        "invalid": {
                            "provider": "openai",
                            "base_url": "https://example.test/v1",
                            "api_key_env": "TEST_INVALID_API_KEY",
                            "model": "invalid-model",
                            "max_tokens": invalid_value,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("agent.api.llm_profiles.LLM_PROFILES_PATH", profile_file)
        monkeypatch.setenv("TEST_INVALID_API_KEY", "secret")

        with pytest.raises(ValueError, match="max_tokens"):
            load_llm_profile()
    finally:
        cleanup_test_dir(tmp_dir)


def test_shipped_profiles_all_set_32000_output_tokens():
    config_path = Path(__file__).resolve().parents[2] / "config" / "llm_profiles.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert len(config["profiles"]) == 4
    assert {profile["max_tokens"] for profile in config["profiles"].values()} == {32000}
