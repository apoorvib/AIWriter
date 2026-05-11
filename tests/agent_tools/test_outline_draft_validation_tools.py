from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
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
            },
            producer=main_agent(),
        )
        committed = facade.commit_draft(work_result_id=str(submitted.data["work_result_id"]))
        draft = facade.stores.draft_store.load_latest("job1")

    assert prepared.ok is True
    assert prepared.data["commit_tool"] == "commit_draft"
    assert committed.ok is True
    assert committed.data["draft_id"].startswith("draft_")
    assert committed.next_suggested_tools == ["prepare_validation"]
    assert draft.section_source_map[0].note_ids == ["note_001"]


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
    assert committed.next_suggested_tools == ["prepare_validation"]


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
