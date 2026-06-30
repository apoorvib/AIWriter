from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.drafting.anti_ai_skill import ANTI_AI_SKILL_DOCUMENT
from essay_writer.validation.schema import (
    AssignmentFit,
    DeterministicCheckResult,
    LLMJudgmentResult,
    LengthCheck,
    UnsupportedClaim,
    ValidationDiagnostic,
    ValidationReport,
)
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import main_agent
from tests.agent_tools.test_research_tools import _research_payload, _seed_job_with_selected_topic


def test_prepare_commit_outline_records_outline_ready() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_research(facade)

        prepared = facade.prepare_outline("job1")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "working_thesis": "Cooling access should be treated as housing policy.",
                "sections": [
                    {
                        "heading": "Introduction",
                        "purpose": "introduce thesis",
                        "key_points": ["Frame cooling access as housing policy."],
                        "note_ids": ["note_001"],
                        "target_words": 150,
                    }
                ],
            },
            producer=main_agent(),
        )
        committed = facade.commit_outline(work_result_id=str(submitted.data["work_result_id"]))
        outline = facade.stores.outline_store.load_latest("job1")

    assert prepared.ok is True
    assert prepared.data["commit_tool"] == "commit_outline"
    assert prepared.data["next_suggested_tools"] == ["submit_work_result"]
    assert committed.ok is True
    assert committed.data["outline_id"] == "thesis_outline_v001"
    assert committed.next_suggested_tools == ["prepare_draft"]
    assert outline.sections[0].note_ids == ["note_001"]


def test_prepare_commit_draft_records_validation_ready() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_outline(facade)

        prepared = facade.prepare_draft("job1")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "content": (
                    "Cooling access should be treated as housing policy because "
                    "the source shows uneven access."
                ),
                "section_source_map": [
                    {
                        "section_id": "section_001",
                        "heading": "Introduction",
                        "note_ids": ["note_001"],
                        "source_ids": ["src1"],
                    }
                ],
                "bibliography_candidates": ["Uploaded Source."],
                "known_weak_spots": [],
                "anti_ai_self_check": {
                    "paragraph_count": 1,
                    "paragraph_first_sentences": [],
                    "first_sentence_chain_summarizes_essay": False,
                    "paragraphs_under_50_words": 1,
                    "paragraphs_opening_with_topic_sentence": 0,
                    "filler_phrases_used": [],
                    "significance_inflation_phrases": [],
                    "vague_attributions_used": [],
                    "concrete_source_handles": [],
                    "style_guidance_grades": [],
                    "self_check_notes": [],
                },
            },
            producer=main_agent(),
        )
        committed = facade.commit_draft(work_result_id=str(submitted.data["work_result_id"]))
        draft = facade.stores.draft_store.load_latest("job1")

    assert prepared.ok is True
    assert prepared.data["commit_tool"] == "commit_draft"
    assert committed.ok is True
    assert committed.data["draft_id"].startswith("draft_")
    assert committed.next_suggested_tools == ["prepare_style_revision", "prepare_validation"]
    assert draft.section_source_map[0].note_ids == ["note_001"]


def test_prepare_style_revision_ships_anti_ai_skill_in_system_prompt() -> None:
    """prepare_style_revision must embed STYLE_REVISION_SYSTEM_PROMPT verbatim.
    That prompt carries the anti-AI skill, which is the whole point of the
    stage. Regressing this would silently strip the skill from the workflow."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)

        prepared = facade.prepare_style_revision("job1")

    assert prepared.ok is True
    assert prepared.data["commit_tool"] == "commit_style_revision"
    system_prompt = prepared.data["system_prompt"]
    assert "<anti_ai_detection_skill>" in system_prompt
    assert "</anti_ai_detection_skill>" in system_prompt
    # A specific sentence from the skill document, so a swapped skill is caught.
    assert "Never use em dashes. Zero. Not one." in system_prompt
    # And the actual skill body must be present, not just the wrapper tags.
    assert ANTI_AI_SKILL_DOCUMENT.split("\n", 1)[0] in system_prompt


def test_prepare_commit_style_revision_records_new_draft_version() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        previous_draft = facade.stores.draft_store.load_latest("job1")

        prepared = facade.prepare_style_revision("job1")
        assert prepared.data["source_draft_id"] == previous_draft.id
        assert prepared.data["source_draft_version"] == previous_draft.version
        assert prepared.data["deterministic"]["word_count"] > 0

        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "content": (
                    "Cooling access is uneven in older rental stock. "
                    "Treating it as housing policy fixes that."
                ),
                "style_changes": ["Removed em dashes.", "Broke uniform paragraph rhythm."],
                "preservation_notes": ["Kept all source citations and section structure."],
                "known_risks": [],
            },
            producer=main_agent(),
        )
        committed = facade.commit_style_revision(
            work_result_id=str(submitted.data["work_result_id"])
        )
        revised = facade.stores.draft_store.load_latest("job1")

    assert committed.ok is True
    assert revised.version == previous_draft.version + 1
    assert revised.origin == "style_revision"
    assert revised.parent_draft_id == previous_draft.id
    assert revised.created_by == "system"
    # Section source map and bibliography are inherited verbatim from the parent.
    assert revised.section_source_map == previous_draft.section_source_map
    assert revised.bibliography_candidates == previous_draft.bibliography_candidates
    # Content is the rewrite.
    assert "Cooling access is uneven" in revised.content
    assert "em dashes" not in revised.content
    assert committed.next_suggested_tools == [
        "prepare_anti_ai_audit",
        "prepare_validation",
    ]


def test_commit_style_revision_is_idempotent_for_same_work_result() -> None:
    """Re-committing the same work_result_id must not create a second draft
    version. It should return the already-committed artifact instead."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)

        prepared = facade.prepare_style_revision("job1")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "content": "Cooling access remains uneven in older rental housing.",
                "style_changes": [],
                "preservation_notes": [],
                "known_risks": [],
            },
            producer=main_agent(),
        )
        first = facade.commit_style_revision(
            work_result_id=str(submitted.data["work_result_id"])
        )
        versions_after_first = len(facade.stores.draft_store.list_versions("job1"))
        second = facade.commit_style_revision(
            work_result_id=str(submitted.data["work_result_id"])
        )
        versions_after_second = len(facade.stores.draft_store.list_versions("job1"))

    assert first.ok is True
    assert second.ok is True
    assert versions_after_first == versions_after_second
    assert first.data["draft_id"] == second.data["draft_id"]
    assert second.data["already_committed"] is True


def test_commit_style_revision_rejects_wrong_stage_packet() -> None:
    """commit_style_revision must reject a result that came from a different
    prepare_* tool. Otherwise a draft payload could be silently promoted to a
    new draft version under the style-revision origin."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_outline(facade)

        prepared = facade.prepare_draft("job1")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "content": "Cooling access should be treated as housing policy.",
                "section_source_map": [
                    {
                        "section_id": "section_001",
                        "heading": "Introduction",
                        "note_ids": ["note_001"],
                        "source_ids": ["src1"],
                    }
                ],
                "bibliography_candidates": ["Uploaded Source."],
                "known_weak_spots": [],
                "anti_ai_self_check": {
                    "paragraph_count": 1,
                    "paragraph_first_sentences": [],
                    "first_sentence_chain_summarizes_essay": False,
                    "paragraphs_under_50_words": 1,
                    "paragraphs_opening_with_topic_sentence": 0,
                    "filler_phrases_used": [],
                    "significance_inflation_phrases": [],
                    "vague_attributions_used": [],
                    "concrete_source_handles": [],
                    "style_guidance_grades": [],
                    "self_check_notes": [],
                },
            },
            producer=main_agent(),
        )
        rejected = facade.commit_style_revision(
            work_result_id=str(submitted.data["work_result_id"])
        )

    assert rejected.ok is False
    assert rejected.error.code == "wrong_commit_tool"


def test_prepare_style_revision_errors_when_no_draft_committed() -> None:
    """Without a committed draft, the prerequisite check must fail clearly and
    point the orchestrator back to prepare_draft."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_outline(facade)

        result = facade.prepare_style_revision("job1")

    assert result.ok is False
    assert result.error.code == "style_revision_artifacts_missing"
    assert "prepare_draft" in result.next_suggested_tools


def test_prepare_commit_revision_records_new_draft_version() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        previous_draft = facade.stores.draft_store.load_latest("job1")
        facade.stores.validation_store.save(
            "job1",
            _validation_report(previous_draft.id),
            version=1,
        )

        prepared = facade.prepare_revision("job1", user_instruction="Tighten the evidence.")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "content": "Cooling access is uneven, so housing policy should address it.",
                "section_source_map": [
                    {
                        "section_id": "section_001",
                        "heading": "Introduction",
                        "note_ids": ["note_001"],
                        "source_ids": ["src1"],
                    }
                ],
                "bibliography_candidates": ["Uploaded Source."],
                "known_weak_spots": [],
                "anti_ai_self_check": {
                    "paragraph_count": 1,
                    "paragraph_first_sentences": [],
                    "first_sentence_chain_summarizes_essay": False,
                    "paragraphs_under_50_words": 1,
                    "paragraphs_opening_with_topic_sentence": 0,
                    "filler_phrases_used": [],
                    "significance_inflation_phrases": [],
                    "vague_attributions_used": [],
                    "concrete_source_handles": [],
                    "style_guidance_grades": [],
                    "self_check_notes": [],
                },
            },
            producer=main_agent(),
        )
        committed = facade.commit_revision(work_result_id=str(submitted.data["work_result_id"]))
        revised = facade.stores.draft_store.load_latest("job1")

    assert prepared.ok is True
    assert prepared.data["commit_tool"] == "commit_revision"
    assert committed.ok is True
    assert revised.version == 2
    assert revised.origin == "system_revision"
    assert revised.parent_draft_id == previous_draft.id
    # A revision resets anti_ai_self_check, so the audit must run before
    # validation (the require_anti_ai_audit gate refuses validation otherwise).
    assert committed.next_suggested_tools == ["prepare_anti_ai_audit", "prepare_validation"]


def test_prepare_commit_validation_records_validation_complete() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)

        prepared = facade.prepare_validation("job1")
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "unsupported_claims": [],
                "citation_issues": [],
                "rubric_scores": [
                    {"criterion": "Uses evidence", "score": 0.9, "note": "Grounded."}
                ],
                "assignment_fit": {"passes": True, "explanation": "Answers the prompt."},
                "length_check": {"actual_words": 12, "target_words": None, "passes": True},
                "style_issues": [],
                "diagnostics": [],
                "revision_suggestions": [],
                "overall_quality": 0.9,
            },
            producer=main_agent(),
        )
        committed = facade.commit_validation(work_result_id=str(submitted.data["work_result_id"]))

    assert prepared.ok is True
    assert prepared.data["commit_tool"] == "commit_validation"
    assert committed.ok is True
    assert committed.data["passes"] is True
    assert committed.next_suggested_tools == ["export_markdown"]


def _seed_job_through_validation(facade: AgentToolFacade) -> None:
    _seed_job_through_draft(facade)
    prepared = facade.prepare_validation("job1")
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload={
            "unsupported_claims": [],
            "citation_issues": [],
            "rubric_scores": [],
            "assignment_fit": {"passes": True, "explanation": "Answers the prompt."},
            "length_check": {"actual_words": 12, "target_words": None, "passes": True},
            "style_issues": [],
            "diagnostics": [],
            "revision_suggestions": [],
            "overall_quality": 0.9,
        },
        producer=main_agent(),
    )
    committed = facade.commit_validation(work_result_id=str(submitted.data["work_result_id"]))
    assert committed.ok is True


def _seed_job_through_research(facade: AgentToolFacade) -> None:
    _seed_job_with_selected_topic(
        facade,
        source_text="Cooling access is uneven in rental housing.",
    )
    plan_result = facade.create_research_plan(job_id="job1")
    assert plan_result.ok is True
    bundle_result = facade.resolve_source_requests(
        job_id="job1",
        research_plan_id=str(plan_result.data["research_plan_id"]),
    )
    packet_id = str(bundle_result.data["packet_ids"][0])
    prepared = facade.prepare_research_notes(
        job_id="job1",
        source_packet_bundle_id=str(bundle_result.data["source_packet_bundle_id"]),
    )
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload=_research_payload(packet_id=packet_id, quote="Cooling access is uneven"),
        producer=main_agent(),
    )
    committed = facade.commit_research_notes(work_result_id=str(submitted.data["work_result_id"]))
    assert committed.ok is True


def _seed_job_through_outline(facade: AgentToolFacade) -> None:
    _seed_job_through_research(facade)
    prepared = facade.prepare_outline("job1")
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload={
            "working_thesis": "Cooling access should be treated as housing policy.",
            "sections": [
                {
                    "heading": "Introduction",
                    "purpose": "introduce thesis",
                    "key_points": ["Frame cooling access as housing policy."],
                    "note_ids": ["note_001"],
                    "target_words": 150,
                }
            ],
        },
        producer=main_agent(),
    )
    committed = facade.commit_outline(work_result_id=str(submitted.data["work_result_id"]))
    assert committed.ok is True


def _seed_job_through_draft(facade: AgentToolFacade) -> None:
    _seed_job_through_outline(facade)
    prepared = facade.prepare_draft("job1")
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload={
            "content": "Cooling access should be treated as housing policy.",
            "section_source_map": [
                {
                    "section_id": "section_001",
                    "heading": "Introduction",
                    "note_ids": ["note_001"],
                    "source_ids": ["src1"],
                }
            ],
            "bibliography_candidates": ["Uploaded Source."],
            "known_weak_spots": [],
            "anti_ai_self_check": {
                "paragraph_count": 1,
                "paragraph_first_sentences": [],
                "first_sentence_chain_summarizes_essay": False,
                "paragraphs_under_50_words": 1,
                "paragraphs_opening_with_topic_sentence": 0,
                "filler_phrases_used": [],
                "significance_inflation_phrases": [],
                "vague_attributions_used": [],
                "concrete_source_handles": [],
                "style_guidance_grades": [],
                "self_check_notes": [],
            },
        },
        producer=main_agent(),
    )
    committed = facade.commit_draft(work_result_id=str(submitted.data["work_result_id"]))
    assert committed.ok is True


def _validation_report(draft_id: str) -> ValidationReport:
    return ValidationReport(
        draft_id=draft_id,
        task_spec_id="task1",
        deterministic=DeterministicCheckResult(
            word_count=12,
            em_dash_count=0,
            tier1_vocab_hits=[],
            bad_conclusion_opener=False,
            consecutive_similar_sentence_runs=[],
            participial_phrase_count=0,
            participial_phrase_rate=0.0,
            contrastive_negation_count=0,
            signposting_hits=[],
        ),
        llm_judgment=LLMJudgmentResult(
            unsupported_claims=[UnsupportedClaim(claim="Weak claim.", paragraph=1)],
            citation_issues=[],
            rubric_scores=[],
            assignment_fit=AssignmentFit(passes=True, explanation="Fits."),
            length_check=LengthCheck(actual_words=12, target_words=None, passes=True),
            style_issues=[],
            diagnostics=[
                ValidationDiagnostic(
                    location="paragraph 1",
                    issue_type="unsupported_claim",
                    evidence="Weak claim.",
                    severity="medium",
                    action="strengthen_grounding",
                )
            ],
            revision_suggestions=["Strengthen source grounding."],
            overall_quality=0.7,
        ),
    )
