from __future__ import annotations

import pytest

from llm.config import StageModelConfig


def test_all_stages_none_when_no_env_set(monkeypatch):
    for var in [
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
    ]:
        monkeypatch.delenv(var, raising=False)

    cfg = StageModelConfig.from_env()

    assert cfg.task_spec is None
    assert cfg.source_card is None
    assert cfg.topic_ideation is None
    assert cfg.research is None
    assert cfg.outlining is None
    assert cfg.drafting is None
    assert cfg.drafting_revision is None
    assert cfg.drafting_style is None
    assert cfg.validation is None


def test_llm_model_is_fallback_for_all_unset_stages(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-4-6")
    for var in [
        "ESSAY_MODEL_TASK_SPEC",
        "ESSAY_MODEL_SOURCE_CARD",
        "ESSAY_MODEL_TOPIC_IDEATION",
        "ESSAY_MODEL_RESEARCH",
        "ESSAY_MODEL_OUTLINING",
        "ESSAY_MODEL_DRAFTING",
        "ESSAY_MODEL_DRAFTING_REVISION",
        "ESSAY_MODEL_DRAFTING_STYLE",
        "ESSAY_MODEL_VALIDATION",
    ]:
        monkeypatch.delenv(var, raising=False)

    cfg = StageModelConfig.from_env()

    assert cfg.task_spec == "claude-sonnet-4-6"
    assert cfg.source_card == "claude-sonnet-4-6"
    assert cfg.topic_ideation == "claude-sonnet-4-6"
    assert cfg.research == "claude-sonnet-4-6"
    assert cfg.outlining == "claude-sonnet-4-6"
    assert cfg.drafting == "claude-sonnet-4-6"
    assert cfg.drafting_revision == "claude-sonnet-4-6"
    assert cfg.drafting_style == "claude-sonnet-4-6"
    assert cfg.validation == "claude-sonnet-4-6"


def test_stage_specific_env_overrides_llm_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("ESSAY_MODEL_DRAFTING", "claude-opus-4-7")
    monkeypatch.setenv("ESSAY_MODEL_VALIDATION", "claude-sonnet-4-6")

    cfg = StageModelConfig.from_env()

    assert cfg.drafting == "claude-opus-4-7"
    assert cfg.validation == "claude-sonnet-4-6"
    assert cfg.research == "claude-haiku-4-5-20251001"
    assert cfg.outlining == "claude-haiku-4-5-20251001"
    assert cfg.drafting_style == "claude-haiku-4-5-20251001"


def test_all_stages_can_be_set_independently(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("ESSAY_MODEL_TASK_SPEC", "m-task")
    monkeypatch.setenv("ESSAY_MODEL_SOURCE_CARD", "m-card")
    monkeypatch.setenv("ESSAY_MODEL_TOPIC_IDEATION", "m-topic")
    monkeypatch.setenv("ESSAY_MODEL_RESEARCH", "m-research")
    monkeypatch.setenv("ESSAY_MODEL_OUTLINING", "m-outline")
    monkeypatch.setenv("ESSAY_MODEL_DRAFTING", "m-draft")
    monkeypatch.setenv("ESSAY_MODEL_DRAFTING_REVISION", "m-revision")
    monkeypatch.setenv("ESSAY_MODEL_DRAFTING_STYLE", "m-style")
    monkeypatch.setenv("ESSAY_MODEL_VALIDATION", "m-validation")

    cfg = StageModelConfig.from_env()

    assert cfg.task_spec == "m-task"
    assert cfg.source_card == "m-card"
    assert cfg.topic_ideation == "m-topic"
    assert cfg.research == "m-research"
    assert cfg.outlining == "m-outline"
    assert cfg.drafting == "m-draft"
    assert cfg.drafting_revision == "m-revision"
    assert cfg.drafting_style == "m-style"
    assert cfg.validation == "m-validation"


def test_empty_string_env_falls_back_to_llm_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ESSAY_MODEL_DRAFTING", "")

    cfg = StageModelConfig.from_env()

    assert cfg.drafting == "claude-sonnet-4-6"
