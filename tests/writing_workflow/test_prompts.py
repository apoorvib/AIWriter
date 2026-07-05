from __future__ import annotations

from essay_writer.writing.prompts import (
    WRITING_BRIEF_SCHEMA,
    WRITING_DRAFT_SCHEMA,
    WRITING_REVIEW_SCHEMA,
    build_brief_user_message,
    build_draft_user_message,
)
from essay_writer.writing.schema import (
    DeliverableSpec, SkillSelection, WriteMode, WritingBrief,
)


def test_brief_schema_requires_routing_and_disclosure_fields() -> None:
    required = set(WRITING_BRIEF_SCHEMA["required"])
    assert {
        "mode", "purpose", "audience", "deliverables", "selected_skill_ids",
        "research_needed", "research_reasons", "assumptions", "blocking_questions",
    } <= required


def test_brief_message_preserves_explicit_overrides() -> None:
    message = build_brief_user_message(
        raw_request="Write a launch email",
        available_skills=[{"id": "email"}, {"id": "anti-ai-detection"}],
        mode_hint="immediate",
        research_policy="off",
        include_skill_ids=["email"],
        exclude_skill_ids=["anti-ai-detection"],
        context=[],
    )
    assert message["explicit_overrides"] == {
        "mode": "immediate",
        "research_policy": "off",
        "include_skill_ids": ["email"],
        "exclude_skill_ids": ["anti-ai-detection"],
    }


def test_draft_message_embeds_exact_skill_prompt_and_sources() -> None:
    brief = WritingBrief(
        brief_id="brief-1", writing_run_id="run1", version=1,
        mode=WriteMode.DETAILED, purpose="Announce launch", audience="customers",
        deliverables=[DeliverableSpec("email", "email", "Launch email")],
        selected_skills=[SkillSelection("email", "1", "sha256:abc")],
    )
    message = build_draft_user_message(
        brief=brief,
        deliverable=brief.deliverables[0],
        skill_prompt="SKILL email v1 sha256:abc\nExact guidance",
        context=[{"label": "launch", "text": "Ships Friday"}],
        research={"facts": [{"fact_id": "f1", "claim": "Market grew"}]},
        plan={"sections": ["Opening", "CTA"]},
    )
    assert "sha256:abc" in message["selected_skill_prompt"]
    assert message["research"]["facts"][0]["fact_id"] == "f1"
    assert set(WRITING_DRAFT_SCHEMA["required"]) >= {
        "content", "assumptions", "research_fact_ids", "self_check"
    }


def test_review_schema_requires_actionable_skill_bound_issues() -> None:
    issue = WRITING_REVIEW_SCHEMA["properties"]["issues"]["items"]
    assert set(issue["required"]) >= {
        "issue_id", "severity", "location", "skill_id", "evidence", "correction"
    }
