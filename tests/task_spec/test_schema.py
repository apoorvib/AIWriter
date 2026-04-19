from __future__ import annotations

import pytest

from essay_writer.task_spec.prompts import TASK_SPEC_SCHEMA
from essay_writer.task_spec.schema import ChecklistItem, TaskSpecification


def test_checklist_confidence_bounds() -> None:
    with pytest.raises(ValueError):
        ChecklistItem(
            id="req_1",
            text="Use MLA.",
            category="citation",
            required=True,
            source_span="Use MLA.",
            confidence=1.5,
        )


def test_task_spec_version_must_be_positive() -> None:
    with pytest.raises(ValueError):
        TaskSpecification(id="task1", version=0, raw_text="x")


def test_llm_schema_excludes_unneeded_policy_fields() -> None:
    fields = set(TASK_SPEC_SCHEMA["properties"])

    assert "due_date" not in fields
    assert "collaboration_or_ai_policy" not in fields
    assert {"course_context", "academic_level", "topic_scope", "required_claims_or_questions"} <= fields
