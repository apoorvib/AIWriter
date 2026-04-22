from __future__ import annotations

from backend import deps
from backend.schemas import AppSettings


_MODEL_ENV_VARS = [
    "LLM_MODEL",
    "ESSAY_MODEL_TASK_SPEC",
    "ESSAY_MODEL_SOURCE_CARD",
    "ESSAY_MODEL_TOPIC_IDEATION",
    "ESSAY_MODEL_RESEARCH",
    "ESSAY_MODEL_OUTLINING",
    "ESSAY_MODEL_DRAFTING",
    "ESSAY_MODEL_DRAFTING_REVISION",
    "ESSAY_MODEL_DRAFTING_STYLE",
    "ESSAY_MODEL_VALIDATION",
]


def _clear_model_env(monkeypatch) -> None:
    for key in _MODEL_ENV_VARS:
        monkeypatch.delenv(key, raising=False)


def test_settings_default_model_applies_to_all_backend_stages(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setattr(deps, "load_settings", lambda: AppSettings(llm_model="settings-default"))

    cfg = deps._model_config_from_settings()

    assert cfg.task_spec == "settings-default"
    assert cfg.source_card == "settings-default"
    assert cfg.topic_ideation == "settings-default"
    assert cfg.research == "settings-default"
    assert cfg.outlining == "settings-default"
    assert cfg.drafting == "settings-default"
    assert cfg.drafting_revision == "settings-default"
    assert cfg.drafting_style == "settings-default"
    assert cfg.validation == "settings-default"


def test_stage_env_overrides_settings_default_model(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("ESSAY_MODEL_DRAFTING", "env-drafting")
    monkeypatch.setattr(deps, "load_settings", lambda: AppSettings(llm_model="settings-default"))

    cfg = deps._model_config_from_settings()

    assert cfg.drafting == "env-drafting"
    assert cfg.validation == "settings-default"


def test_stage_setting_overrides_stage_env(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("ESSAY_MODEL_DRAFTING", "env-drafting")
    monkeypatch.setattr(
        deps,
        "load_settings",
        lambda: AppSettings(llm_model="settings-default", model_drafting="settings-drafting"),
    )

    cfg = deps._model_config_from_settings()

    assert cfg.drafting == "settings-drafting"


def test_llm_model_env_is_backend_fallback_when_settings_default_empty(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "env-default")
    monkeypatch.setattr(deps, "load_settings", lambda: AppSettings())

    cfg = deps._model_config_from_settings()

    assert cfg.outlining == "env-default"
    assert cfg.drafting_style == "env-default"
