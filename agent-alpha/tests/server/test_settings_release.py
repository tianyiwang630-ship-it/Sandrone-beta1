from agent.server.routes import settings as settings_route


def test_update_settings_releases_cached_agents(monkeypatch):
    calls = {"released": 0}

    monkeypatch.setattr(
        settings_route.state_store,
        "update_settings",
        lambda updates: {
            "llm_provider": updates.get("llm_provider", "openai"),
            "llm_base_url": updates.get("llm_base_url", "https://api.openai.com/v1"),
            "llm_api_key": updates.get("llm_api_key", "secret"),
            "llm_model_name": updates.get("llm_model_name", "gpt-4.1"),
            "permission_mode": updates.get("permission_mode", "ask"),
            "theme": updates.get("theme", "light"),
        },
    )
    monkeypatch.setattr(settings_route.agent_manager, "release_all", lambda: calls.__setitem__("released", 1))

    payload = settings_route.update_settings(
        settings_route.SettingsPatch(
            llm_provider="openai",
            llm_base_url="https://api.openai.com/v1",
            llm_model_name="gpt-4.1",
        )
    )

    assert payload.llm_provider == "openai"
    assert calls["released"] == 1
