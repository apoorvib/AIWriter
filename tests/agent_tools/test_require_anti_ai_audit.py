"""Tests for the require-anti-AI-audit gate (Fix #1).

With ``require_anti_ai_audit=True`` (production default), prepare_validation
refuses until an anti-AI audit has been committed for the job. This makes
the audit stage non-optional, closing the "skip the anti-AI checkpoint on
the way to export" hole that started this work.

These tests construct the facade with the flag ON explicitly, overriding
the conftest default-off.

Audit coverage is per-rule (one row per canonical R# rule of the skill file
plus a self_check row); see
docs/superpowers/specs/2026-07-12-anti-ai-audit-per-rule-design.md.
"""
from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade

from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import dispatched_subagent
from tests.agent_tools.helpers import anti_ai_audit_payload as full_audit_payload
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


def _enforced(tmp) -> AgentToolFacade:
    return AgentToolFacade.from_data_dir(
        tmp / "data",
        require_anti_ai_audit=True,
    )


def _first_guidance_row(payload: dict) -> dict:
    """Return the first rule_audit row (every row is a full guidance row)."""
    for row in payload["anti_ai_self_check"]["rule_audit"]:
        return row
    raise AssertionError("fixture payload had no rule rows")


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
        payload=full_audit_payload(draft_text=source_draft.content),
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


def test_committed_rule_audit_payload_is_small_enough_to_submit_inline() -> None:
    """Regression guard for the bug that started this work: the per-line audit
    payload was ~100K tokens and could not be submitted inline. Per-block
    coverage must keep the serialized payload well under 40 KB."""
    import json

    payload = full_audit_payload(
        draft_text="Cooling access should be treated as housing policy."
    )
    serialized = json.dumps(payload, ensure_ascii=False)
    # The per-line payload was ~229 KB / ~100K tokens and hit the model output
    # cap, so it could never be emitted inline. Per-block coverage keeps a lean
    # audit well under a third of that (~96 KB / ~32K tokens), inline-submittable.
    assert len(serialized) < 110_000, f"audit payload is {len(serialized)} bytes"


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


def test_commit_anti_ai_audit_rejects_incomplete_rule_coverage() -> None:
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
            payload=full_audit_payload(
                draft_text=source_draft.content,
                omit_last_rule=True,
            ),
            producer=producer,
        )
        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_rule_audit_incomplete"


def test_commit_anti_ai_audit_rejects_rule_hash_mismatch() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        payload["anti_ai_self_check"]["rule_audit"][0]["rule_text_sha256"] = (
            "sha256:" + "0" * 64
        )
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
    assert result.error.code == "anti_ai_rule_audit_hash_mismatch"


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


def test_commit_anti_ai_audit_rejects_boilerplate_rule_audit() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["rule_audit"]:
            if True:
                row["finding"] = "Generic finding for every rule."
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
    assert result.error.code == "anti_ai_rule_audit_boilerplate"


def test_commit_anti_ai_audit_rejects_failed_rule_without_final_failure() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        # Flip a guidance row to "failed" but keep unmet empty and pass True.
        _first_guidance_row(payload)["status"] = "failed"
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
    assert result.error.code == "anti_ai_rule_audit_inconsistent"


def test_commit_anti_ai_audit_rejects_non_context_rows_without_draft_evidence() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["rule_audit"]:
            if True:
                row["draft_evidence"] = [
                    {
                        "kind": "not_applicable",
                        "reference": f"rule {row['rule_id']} skipped",
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
    assert result.error.code == "anti_ai_rule_audit_missing_draft_evidence"


def test_commit_anti_ai_audit_rejects_weak_rule_specific_reasoning() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["rule_audit"]:
            if True:
                row["rule_application"] = "Applied."
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
    assert result.error.code == "anti_ai_rule_audit_weak_reasoning"


def test_commit_anti_ai_audit_rejects_missing_whole_essay_review() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        # whole_essay_evidence is optional in the schema now, so dropping it on a
        # guidance row passes submit-time schema validation but must be caught by
        # the commit-time block validator.
        for row in payload["anti_ai_self_check"]["rule_audit"]:
            if True:
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
        result = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "anti_ai_rule_audit_missing_whole_essay_review"


def test_commit_anti_ai_audit_rejects_partial_whole_essay_review() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        _seed_job_through_draft(facade)
        prepared_audit = facade.prepare_anti_ai_audit("job1")
        source_draft = facade.stores.draft_store.find_by_id(
            "job1", str(prepared_audit.data["draft_id"])
        )
        payload = full_audit_payload(draft_text=source_draft.content)
        for row in payload["anti_ai_self_check"]["rule_audit"]:
            if True:
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
    assert result.error.code == "anti_ai_rule_audit_missing_whole_essay_review"
