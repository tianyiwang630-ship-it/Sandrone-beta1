from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException

from agent.server.deps import agent_manager, state_store
from agent.server.models import SettingsInfo, SettingsPatch

router = APIRouter(prefix="/api/settings", tags=["settings"])

SUPPORTED_LLM_PROVIDERS = {"openai", "deepseek", "minimax", "zhipu", "kimi", "siliconflow", "custom"}


def _infer_provider(base_url: str | None) -> str:
    value = (base_url or "").strip()
    if not value:
        return "openai"
    try:
        host = (urlparse(value).netloc or value).lower()
    except Exception:
        host = value.lower()
    if "deepseek" in host:
        return "deepseek"
    if "minimaxi" in host:
        return "minimax"
    if "bigmodel" in host:
        return "zhipu"
    if "moonshot" in host or "kimi" in host:
        return "kimi"
    if "siliconflow" in host:
        return "siliconflow"
    return "openai"


def _normalize_provider(provider: str | None, base_url: str | None) -> str:
    normalized = str(provider or "").strip().lower()
    if not normalized:
        return _infer_provider(base_url)
    if normalized not in SUPPORTED_LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    return normalized


def _settings_payload(settings: dict[str, Any]) -> SettingsInfo:
    normalized = normalize_settings(settings)
    base_url = str(normalized.get("llm_base_url") or "")
    api_key = str(normalized.get("llm_api_key") or "")
    api_keys = {str(key): str(value) for key, value in dict(normalized.get("llm_api_keys") or {}).items()}
    return SettingsInfo(
        llm_provider=str(normalized.get("llm_provider") or "openai"),
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_api_keys=api_keys,
        llm_model_name=str(normalized.get("llm_model_name") or ""),
        has_api_key=bool(api_key.strip()),
        permission_mode=str(normalized.get("permission_mode") or "ask"),
        theme=str(normalized.get("theme") or "light"),
    )


def normalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(settings)
    base_url = str(settings.get("llm_base_url") or "")
    normalized["llm_provider"] = _normalize_provider(settings.get("llm_provider"), base_url)
    api_keys = dict(settings.get("llm_api_keys") or {})
    provider_key = str(api_keys.get(str(normalized["llm_provider"])) or "")
    fallback_key = str(settings.get("llm_api_key") or "")
    normalized["llm_api_keys"] = api_keys
    normalized["llm_api_key"] = provider_key or (fallback_key if not api_keys else "")
    return normalized


@router.get("", response_model=SettingsInfo)
def get_settings():
    return _settings_payload(state_store.get_settings())


@router.patch("", response_model=SettingsInfo)
def update_settings(body: SettingsPatch):
    updates = body.model_dump(exclude_none=True)
    if "llm_base_url" in updates and not str(updates["llm_base_url"]).strip():
        raise HTTPException(status_code=400, detail="llm_base_url cannot be empty")
    if "llm_model_name" in updates and not str(updates["llm_model_name"]).strip():
        raise HTTPException(status_code=400, detail="llm_model_name cannot be empty")
    if "llm_provider" in updates:
        updates["llm_provider"] = _normalize_provider(updates["llm_provider"], updates.get("llm_base_url"))
    elif "llm_base_url" in updates:
        current = state_store.get_settings()
        updates["llm_provider"] = _normalize_provider(current.get("llm_provider"), updates.get("llm_base_url"))
    payload = _settings_payload(state_store.update_settings(updates))
    agent_manager.release_all()
    return payload
