"""Tests for the require-anti-AI-audit gate (Fix #1).

With ``require_anti_ai_audit=True`` (production default), prepare_validation
refuses until an anti-AI audit has been committed for the job. This makes
the audit stage non-optional, closing the "skip the anti-AI checkpoint on
the way to export" hole that started this work.

These tests construct the facade with the flag ON explicitly, overriding
the conftest default-off.
"""
from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.drafting.anti_ai_skill import anti_ai_skill_manifest, draft_sha256

from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import dispatched_subagent, main_agent
from tests.agent_tools.helpers import anti_ai_audit_payload as full_audit_payload
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


def _enforced(tmp) -> AgentToolFacade:
    return AgentToolFacade.from_data_dir(
        tmp / "data",
        require_anti_ai_audit=True,
    )


def _line_audit_payload(
    *,
    draft_text: str,
    omit_last_line: bool = False,
) -> list[dict[str, object]]:
    manifest = anti_ai_skill_manifest()
    lines = manifest["lines"][:-1] if omit_last_line else manifest["lines"]
    draft_quote = draft_text.strip().splitlines()[0][:120] if draft_text.strip() else ""
    paragraph_count_reviewed = len([part for part in draft_text.split("\n\n") if part.strip()])
    return [
        {
            "line_number": line["line_number"],
            "line_text_sha256": line["sha256"],
            "requirement": f"Line {line['line_number']} requirement: {str(line['text']).strip()[:80] or '<blank>'}",
            "status": "context" if not str(line["text"]).strip() else "passed",
            "evidence": f"Line {line['line_number']} checked against the draft.",
            "draft_evidence": [
                {
                    "kind": "not_applicable" if not str(line["text"]).strip() else "draft_quote",
                    "reference": (
                        f"line {line['line_number']} is context-only"
                        if not str(line["text"]).strip()
                        else draft_quote
                    ),
                    "explanation": (
                        f"Line {line['line_number']} is context-only."
                        if not str(line["text"]).strip()
                        else f"Line {line['line_number']} was compared to this exact draft sentence."
                    ),
                }
            ],
            "whole_essay_evidence": {
                "scope": "whole_essay",
                "paragraph_count_reviewed": paragraph_count_reviewed,
                "method": (
                    f"Reviewed all {paragraph_count_reviewed} draft paragraphs for "
                    f"skill line {line['line_number']}."
                ),
                "finding": (
                    f"Whole-essay review for line {line['line_number']} found the "
                    "fixture draft acceptable or context-only."
                ),
            },
            "line_application": (
                f"Line {line['line_number']} was applied to the fixture draft or classified as context."
            ),
            "action_taken": f"Classified line {line['line_number']}.",
        }
        for line in lines
    ]


def _audit_payload(
    *,
    draft_text: str = "Cooling access should be treated as housing policy.",
    omit_last_line: bool = False,
) -> dict[str, object]:
    manifest = anti_ai_skill_manifest()
    return {
        "pass": True,
        "anti_ai_self_check": {
            "skill_file": manifest["path"],
            "skill_sha256": manifest["sha256"],
            "skill_line_count": manifest["line_count"],
            "draft_sha256": draft_sha256(draft_text),
            "line_audit": _line_audit_payload(
                draft_text=draft_text,
                omit_last_line=omit_last_line,
            ),
            "paragraph_count": 1,
            "paragraph_first_sentences": ["A."],
            "first_sentence_chain_summarizes_essay": False,
            "paragraphs_under_50_words": 1,
            "paragraphs_opening_with_topic_sentence": 1,
            "filler_phrases_used": [],
            "significance_inflation_phrases": [],
            "vague_attributions_used": [],
            "concrete_source_handles": ["source p. 1"],
            "style_guidance_grades": [],
            "self_check_notes": [],
            "unmet_requirements": [],
            "final_decision": {
                "hard_rules_pass": True,
                "soft_rules_pass": True,
                "safe_to_claim_detector_reduction": True,
                "reason": "Line-level skill audit passed for the tested draft.",
            },
        },
        "revision_targets": [],
    }


def _commit_audit(facade: AgentToolFacade, *, draft_id: str | None = None):
    prepared_audit = facade.prepare_anti_ai_audit("job1", draft_id=draft_id)
    source_draft = facade.stores.draft_store.find_by_id(
        "job1", str(prepared_audit.data["draft_id"])
    )
    producer = dispatched_subagent(
        facade,
        work_packet_id=str(prepared_audit.data["work_packet_id"]),
        role="anti_ai_auditor",
    )
    submitted = facade.submit_work_result(
        str(prepared_audit.data["work_packet_id"]),
        payload=_audit_payload(draft_text=source_draft.content),
        producer=producer,
    )
    return facade.commit_anti_ai_audit(
        work_result_id=str(submitted.data["work_result_id"]),
    )


def test_validation_blocked_without_committed_audit() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        result = facade.prepare_validation("job1")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_audit_required"
    assert "prepare_anti_ai_audit" in result.next_suggested_tools


def test_validation_allowed_after_audit_committed() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)

        _commit_audit(facade)

        # Now validation must be allowed (no anti_ai_audit_required).
        result = facade.prepare_validation("job1")
    assert result.ok is True
    assert result.data["stage"] == "validation"


def test_save_user_edit_clears_inherited_anti_ai_audit_metadata() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        committed = _commit_audit(facade)
        audited_draft_id = str(committed.data["draft_id"])

        edited = facade.save_user_edit(
            "job1",
            audited_draft_id,
            "Cooling access should be treated as housing policy, with a new sentence.",
        )
        edited_draft = facade.stores.draft_store.find_by_id(
            "job1", str(edited.data["draft_id"])
        )

    assert edited.ok is True
    assert edited_draft.anti_ai_self_check is None
    assert edited.next_suggested_tools == ["prepare_anti_ai_audit"]


def test_validation_rejects_user_edit_until_exact_draft_is_audited() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        committed = _commit_audit(facade)
        edited = facade.save_user_edit(
            "job1",
            str(committed.data["draft_id"]),
            "Cooling access should be treated as housing policy, with a new sentence.",
        )

        result = facade.prepare_validation("job1", draft_id=str(edited.data["draft_id"]))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_audit_required"
    assert "prepare_anti_ai_audit" in result.next_suggested_tools


def test_commit_anti_ai_audit_rejects_incomplete_line_coverage() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared_audit.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared_audit.data["work_packet_id"]),
            payload=_audit_payload(
                draft_text=source_draft.content,
                omit_last_line=True,
            ),
            producer=producer,
        )
        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_skill_line_audit_incomplete"


def test_commit_anti_ai_audit_rejects_wrong_skill_file() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        payload["anti_ai_self_check"]["skill_file"] = "different-SKILL.md"
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared_audit.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared_audit.data["work_packet_id"]),
            payload=payload,
            producer=producer,
        )
        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_skill_file_mismatch"


def test_commit_anti_ai_audit_rejects_boilerplate_line_audit() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["line_audit"]:
            row["requirement"] = "Generic line was reviewed."
            row["evidence"] = "Generic evidence."
            row["action_taken"] = "Generic action."
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared_audit.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared_audit.data["work_packet_id"]),
            payload=payload,
            producer=producer,
        )
        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_skill_line_audit_boilerplate"


def test_commit_anti_ai_audit_rejects_failed_line_without_final_failure() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        payload["anti_ai_self_check"]["line_audit"][0]["status"] = "failed"
        payload["anti_ai_self_check"]["unmet_requirements"] = []
        payload["anti_ai_self_check"]["final_decision"]["hard_rules_pass"] = True
        payload["pass"] = True
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared_audit.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared_audit.data["work_packet_id"]),
            payload=payload,
            producer=producer,
        )
        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_skill_line_audit_inconsistent"


def test_commit_anti_ai_audit_rejects_non_context_rows_without_draft_evidence() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = _audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["line_audit"]:
            if row["status"] != "context":
                row["draft_evidence"] = [
                    {
                        "kind": "not_applicable",
                        "reference": f"line {row['line_number']} skipped",
                        "explanation": "No draft-specific evidence supplied.",
                    }
                ]
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared_audit.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared_audit.data["work_packet_id"]),
            payload=payload,
            producer=producer,
        )

        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_skill_line_audit_missing_draft_evidence"


def test_commit_anti_ai_audit_rejects_weak_line_specific_reasoning() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = _audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["line_audit"]:
            row["line_application"] = "Applied."
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared_audit.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared_audit.data["work_packet_id"]),
            payload=payload,
            producer=producer,
        )

        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_skill_line_audit_weak_reasoning"


def test_commit_anti_ai_audit_rejects_missing_whole_essay_review() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = _audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["line_audit"]:
            row.pop("whole_essay_evidence", None)
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared_audit.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared_audit.data["work_packet_id"]),
            payload=payload,
            producer=producer,
        )

    assert submitted.ok is False
    assert submitted.error is not None
    assert submitted.error.code == "work_result_payload_invalid"


def test_commit_anti_ai_audit_rejects_partial_whole_essay_review() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = _audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["line_audit"]:
            row["whole_essay_evidence"] = {
                "scope": "whole_essay",
                "paragraph_count_reviewed": 0,
                "method": "Reviewed only one paragraph instead of the whole audited essay.",
                "finding": "This deliberately under-counts the whole essay paragraph review.",
            }
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared_audit.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared_audit.data["work_packet_id"]),
            payload=payload,
            producer=producer,
        )

        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_skill_line_audit_missing_whole_essay_review"
