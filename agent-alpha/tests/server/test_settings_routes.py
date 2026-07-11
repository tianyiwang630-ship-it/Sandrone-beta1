from agent.server.routes import settings as settings_route


def test_settings_payload_hides_api_key_value():
    payload = settings_route._settings_payload(
        {
            "llm_provider": "openai",
            "llm_base_url": "https://api.openai.com/v1",
            "llm_api_key": "secret-key",
            "llm_model_name": "gpt-4.1",
            "permission_mode": "ask",
            "theme": "light",
        }
    )

    assert payload.has_api_key is True
    assert payload.llm_provider == "openai"
    assert payload.llm_model_name == "gpt-4.1"


def test_settings_accepts_deepseek_provider():
    payload = settings_route._settings_payload(
        {
            "llm_provider": "deepseek",
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_api_key": "secret-key",
            "llm_model_name": "deepseek-v4-flash",
        }
    )

    assert payload.llm_provider == "deepseek"


def test_settings_accepts_custom_provider_as_label():
    payload = settings_route._settings_payload(
        {
            "llm_provider": "custom",
            "llm_base_url": "http://127.0.0.1:11434/v1",
            "llm_api_key": "local-key",
            "llm_model_name": "local-model",
        }
    )

    assert payload.llm_provider == "custom"


def test_settings_patch_accepts_custom_provider():
    patch = settings_route.SettingsPatch(
        llm_provider="custom",
        llm_base_url="http://127.0.0.1:11434/v1",
        llm_model_name="local-model",
    )

    assert patch.llm_provider == "custom"


def test_settings_infers_deepseek_when_provider_is_empty():
    payload = settings_route._settings_payload(
        {
            "llm_provider": "",
            "llm_base_url": "https://api.deepseek.com",
            "llm_api_key": "secret-key",
            "llm_model_name": "deepseek-v4-pro",
        }
    )

    assert payload.llm_provider == "deepseek"


def test_normalize_settings_does_not_reuse_other_provider_key():
    normalized = settings_route.normalize_settings(
        {
            "llm_provider": "custom",
            "llm_base_url": "http://127.0.0.1:11434/v1",
            "llm_api_key": "legacy-key",
            "llm_api_keys": {"deepseek": "deepseek-key"},
            "llm_model_name": "local-model",
        }
    )

    assert normalized["llm_api_key"] == ""
