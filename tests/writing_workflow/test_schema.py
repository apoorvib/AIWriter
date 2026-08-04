from __future__ import annotations

from dataclasses import asdict

import pytest

from essay_writer.writing.schema import (
    DeliverableSpec,
    ResearchPolicy,
    SkillSelection,
    WriteMode,
    WritingBrief,
    WritingDraft,
    WritingOutput,
    WritingRun,
)


def _skill(skill_id: str = "anti-ai-detection") -> SkillSelection:
    return SkillSelection(skill_id=skill_id, version="1", sha256="sha256:abc")


def test_writing_run_defaults_to_active_auto_mode() -> None:
    run = WritingRun(writing_run_id="wrun-1", raw_request="Write a launch email")

    assert run.status == "active"
    assert run.mode_hint is None
    assert run.research_policy == ResearchPolicy.AUTO
    assert run.revision_rounds == {}


def test_writing_run_roundtrips_enum_values() -> None:
    original = WritingRun(
        writing_run_id="wrun-1",
        raw_request="Write a detailed launch email",
        mode_hint=WriteMode.DETAILED,
        research_policy=ResearchPolicy.REQUIRED,
    )

    loaded = WritingRun.from_dict(asdict(original))

    assert loaded.mode_hint is WriteMode.DETAILED
    assert loaded.research_policy is ResearchPolicy.REQUIRED


def test_brief_supports_multiple_bounded_deliverables() -> None:
    brief = WritingBrief(
        brief_id="wbrief-1",
        writing_run_id="wrun-1",
        version=1,
        mode=WriteMode.DETAILED,
        purpose="Announce launch",
        audience="customers",
        deliverables=[
            DeliverableSpec("d1", "email", "Launch email"),
            DeliverableSpec("d2", "linkedin", "Launch post"),
        ],
        selected_skills=[_skill()],
    )

    loaded = WritingBrief.from_dict(asdict(brief))

    assert len(loaded.deliverables) == 2
    assert loaded.deliverables[1].format == "linkedin"
    assert loaded.selected_skills[0].skill_id == "anti-ai-detection"


def test_brief_rejects_more_than_five_deliverables() -> None:
    deliverables = [
        DeliverableSpec(f"d{i}", "email", "Write email") for i in range(6)
    ]

    with pytest.raises(ValueError, match="at most 5"):
        WritingBrief(
            brief_id="wbrief-1",
            writing_run_id="wrun-1",
            version=1,
            mode=WriteMode.IMMEDIATE,
            purpose="Send updates",
            audience="customers",
            deliverables=deliverables,
            selected_skills=[_skill("email")],
        )


def test_brief_rejects_duplicate_deliverable_ids() -> None:
    with pytest.raises(ValueError, match="deliverable IDs must be unique"):
        WritingBrief(
            brief_id="wbrief-1",
            writing_run_id="wrun-1",
            version=1,
            mode=WriteMode.IMMEDIATE,
            purpose="Send updates",
            audience="customers",
            deliverables=[
                DeliverableSpec("same", "email", "Email"),
                DeliverableSpec("same", "linkedin", "Post"),
            ],
            selected_skills=[_skill("email")],
        )


def test_draft_and_output_roundtrip_nested_data() -> None:
    draft = WritingDraft(
        draft_id="wdraft-1",
        writing_run_id="wrun-1",
        deliverable_id="d1",
        version=1,
        content="Hello Maya, the release is ready.",
        selected_skills=[_skill("email")],
        assumptions=["Maya knows the project"],
        self_check=["Clear call to action"],
    )
    output = WritingOutput(
        output_id="woutput-1",
        writing_run_id="wrun-1",
        deliverables=[draft],
        selected_skills=[_skill("email")],
        assumptions=["Maya knows the project"],
    )

    loaded = WritingOutput.from_dict(asdict(output))

    assert loaded.deliverables[0].content.startswith("Hello Maya")
    assert loaded.selected_skills[0].skill_id == "email"


@pytest.mark.parametrize("value", ["", "   "])
def test_required_ids_must_be_nonempty(value: str) -> None:
    with pytest.raises(ValueError, match="writing_run_id"):
        WritingRun(writing_run_id=value, raw_request="Write something")
