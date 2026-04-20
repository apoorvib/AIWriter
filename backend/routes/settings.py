from __future__ import annotations

import os

from fastapi import APIRouter

from backend.deps import load_settings, save_settings, get_workflow_runner
from backend.schemas import AppSettings, AppSettingsResponse

router = APIRouter(prefix="/settings", tags=["settings"])

_PROVIDER_KEY_VARS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _provider_info() -> tuple[str, bool]:
    provider = os.environ.get("LLM_PROVIDER", "claude").lower()
    key_var = _PROVIDER_KEY_VARS.get(provider, f"{provider.upper()}_API_KEY")
    return provider, bool(os.environ.get(key_var))


@router.get("", response_model=AppSettingsResponse)
def get_settings():
    provider, api_key_configured = _provider_info()
    settings = load_settings()
    return AppSettingsResponse(
        **settings.model_dump(),
        llm_provider=provider,
        api_key_configured=api_key_configured,
    )


@router.put("", response_model=AppSettingsResponse)
def update_settings(body: AppSettings):
    save_settings(body)
    get_workflow_runner.cache_clear()
    provider, api_key_configured = _provider_info()
    return AppSettingsResponse(
        **body.model_dump(),
        llm_provider=provider,
        api_key_configured=api_key_configured,
    )
