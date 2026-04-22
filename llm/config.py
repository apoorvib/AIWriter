from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StageMaxTokensConfig:
    """Per-stage max_tokens overrides, each falling back to the hardcoded service default."""

    task_spec: int = 4096
    source_card: int = 2500
    topic_ideation: int = 5000
    research: int = 8000
    outlining: int = 6000
    drafting: int = 8000
    drafting_revision: int = 8000
    drafting_style: int = 8000
    validation: int = 4000

    @classmethod
    def from_env(cls) -> "StageMaxTokensConfig":
        def _int(key: str, default: int) -> int:
            val = os.environ.get(key)
            if val:
                try:
                    return int(val)
                except ValueError:
                    pass
            return default

        return cls(
            task_spec=_int("ESSAY_MAX_TOKENS_TASK_SPEC", cls.task_spec),
            source_card=_int("ESSAY_MAX_TOKENS_SOURCE_CARD", cls.source_card),
            topic_ideation=_int("ESSAY_MAX_TOKENS_TOPIC_IDEATION", cls.topic_ideation),
            research=_int("ESSAY_MAX_TOKENS_RESEARCH", cls.research),
            outlining=_int("ESSAY_MAX_TOKENS_OUTLINING", cls.outlining),
            drafting=_int("ESSAY_MAX_TOKENS_DRAFTING", cls.drafting),
            drafting_revision=_int("ESSAY_MAX_TOKENS_DRAFTING_REVISION", cls.drafting_revision),
            drafting_style=_int("ESSAY_MAX_TOKENS_DRAFTING_STYLE", cls.drafting_style),
            validation=_int("ESSAY_MAX_TOKENS_VALIDATION", cls.validation),
        )


@dataclass(frozen=True)
class StageModelConfig:
    """Per-stage model overrides, each falling back to LLM_MODEL then adapter default."""

    task_spec: str | None = None
    source_card: str | None = None
    topic_ideation: str | None = None
    research: str | None = None
    outlining: str | None = None
    drafting: str | None = None
    drafting_revision: str | None = None
    drafting_style: str | None = None
    validation: str | None = None

    @classmethod
    def from_env(cls) -> "StageModelConfig":
        default = os.environ.get("LLM_MODEL") or None
        return cls(
            task_spec=os.environ.get("ESSAY_MODEL_TASK_SPEC") or default,
            source_card=os.environ.get("ESSAY_MODEL_SOURCE_CARD") or default,
            topic_ideation=os.environ.get("ESSAY_MODEL_TOPIC_IDEATION") or default,
            research=os.environ.get("ESSAY_MODEL_RESEARCH") or default,
            outlining=os.environ.get("ESSAY_MODEL_OUTLINING") or default,
            drafting=os.environ.get("ESSAY_MODEL_DRAFTING") or default,
            drafting_revision=os.environ.get("ESSAY_MODEL_DRAFTING_REVISION") or default,
            drafting_style=os.environ.get("ESSAY_MODEL_DRAFTING_STYLE") or default,
            validation=os.environ.get("ESSAY_MODEL_VALIDATION") or default,
        )
