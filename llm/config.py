from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StageModelConfig:
    """Per-stage model overrides, each falling back to LLM_MODEL then adapter default."""

    task_spec: str | None = None
    source_card: str | None = None
    topic_ideation: str | None = None
    research: str | None = None
    drafting: str | None = None
    drafting_revision: str | None = None
    validation: str | None = None

    @classmethod
    def from_env(cls) -> "StageModelConfig":
        default = os.environ.get("LLM_MODEL") or None
        return cls(
            task_spec=os.environ.get("ESSAY_MODEL_TASK_SPEC") or default,
            source_card=os.environ.get("ESSAY_MODEL_SOURCE_CARD") or default,
            topic_ideation=os.environ.get("ESSAY_MODEL_TOPIC_IDEATION") or default,
            research=os.environ.get("ESSAY_MODEL_RESEARCH") or default,
            drafting=os.environ.get("ESSAY_MODEL_DRAFTING") or default,
            drafting_revision=os.environ.get("ESSAY_MODEL_DRAFTING_REVISION") or default,
            validation=os.environ.get("ESSAY_MODEL_VALIDATION") or default,
        )
