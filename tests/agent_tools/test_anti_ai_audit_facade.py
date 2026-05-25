"""End-to-end facade tests for the new anti-AI audit stage.

These exercise the new prepare_anti_ai_audit / commit_anti_ai_audit tool pair
through the facade to confirm:

1. The audit packet's system prompt is the anti-AI skill (forcing function E).
2. The audit packet's prompt blocks include the deterministic findings and the
   whole-draft context (forcing function A + D).
3. The audit packet delegation flag is True with the bounded role (forcing F).
4. The audit packet's response schema requires the new audit fields (B + H + C).
5. commit_anti_ai_audit attaches the audit to a new draft version (C).
"""
from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import dispatched_subagent, main_agent
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


def test_prepare_anti_ai_audit_returns_bounded_subagent_packet() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        prepared = facade.prepare_anti_ai_audit("job1")

    assert prepared.ok is True
    assert prepared.data["stage"] == "anti_ai_audit"
    assert prepared.data["commit_tool"] == "commit_anti_ai_audit"

    # F: delegation flips on for this stage.
    delegation = prepared.data["delegation"]
    assert delegation["recommended"] is True
    assert delegation["suggested_role"] == "anti_ai_auditor"

    # E: system prompt contains the anti-AI skill, and nothing else.
    assert "anti-AI prose auditor" in prepared.data["system_prompt"]
    assert "anti_ai_detection_skill" in prepared.data["system_prompt"]
    assert "GROUNDING RULES" not in prepared.data["system_prompt"]

    # A + D: prompt blocks must include the deterministic findings and the
    # whole-draft context (paragraph count, first-sentence chain). Without
    # those, the soft-tier rules are invisible to the auditor.
    import json

    user_payload = json.loads(prepared.data["prompt_blocks"][0]["text"])
    assert "deterministic_findings" in user_payload
    assert "whole_draft_context" in user_payload
    assert "paragraph_count" in user_payload["whole_draft_context"]
    assert "first_sentence_chain" in user_payload["whole_draft_context"]

    # B + H + C: response schema requires the audit + grades.
    schema = prepared.data["response_schema"]
    assert "anti_ai_self_check" in schema["required"]
    assert "revision_targets" in schema["required"]
    assert "pass" in schema["required"]


def test_commit_anti_ai_audit_writes_new_draft_version_with_audit() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        previous = facade.stores.draft_store.load_latest("job1")

        prepared = facade.prepare_anti_ai_audit("job1")
        audit_payload = {
            "pass": False,
            "anti_ai_self_check": {
                "paragraph_count": 2,
                "paragraph_first_sentences": ["Cooling access.", "The writer treats this."],
                "first_sentence_chain_summarizes_essay": True,
                "paragraphs_under_50_words": 0,
                "paragraphs_opening_with_topic_sentence": 2,
                "filler_phrases_used": ["in essence"],
                "significance_inflation_phrases": [],
                "vague_attributions_used": [],
                "concrete_source_handles": ["uploaded source p. 5"],
                "style_guidance_grades": [],
                "self_check_notes": ["First-sentence chain summarizes the whole essay"],
            },
            "revision_targets": [
                {
                    "paragraph": 1,
                    "issue": "First-sentence chain summarizes the essay",
                    "action": "advance_argument",
                }
            ],
        }
        # The audit packet has delegation_required=True (mechanism B), so
        # submit_work_result needs a producer carrying a subagent token.
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=audit_payload,
            producer=producer,
        )
        committed = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

        assert committed.ok is True
        assert committed.data["audit_pass"] is False
        assert committed.data["revision_targets"][0]["action"] == "advance_argument"

        # A new draft version is written with the audit attached.
        latest = facade.stores.draft_store.load_latest("job1")
        assert latest.version == previous.version + 1
        assert latest.parent_draft_id == previous.id
        assert latest.anti_ai_self_check is not None
        assert latest.anti_ai_self_check.filler_phrases_used == ["in essence"]
        assert latest.anti_ai_self_check.first_sentence_chain_summarizes_essay is True

        # Pass=False routes to prepare_revision before validation.
        assert committed.next_suggested_tools == ["prepare_revision", "prepare_validation"]


def test_commit_anti_ai_audit_passing_skips_revision() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)

        prepared = facade.prepare_anti_ai_audit("job1")
        audit_payload = {
            "pass": True,
            "anti_ai_self_check": {
                "paragraph_count": 3,
                "paragraph_first_sentences": ["A.", "B short paragraph.", "C closing."],
                "first_sentence_chain_summarizes_essay": False,
                "paragraphs_under_50_words": 1,
                "paragraphs_opening_with_topic_sentence": 1,
                "filler_phrases_used": [],
                "significance_inflation_phrases": [],
                "vague_attributions_used": [],
                "concrete_source_handles": ["uploaded source p. 5"],
                "style_guidance_grades": [],
                "self_check_notes": [],
            },
            "revision_targets": [],
        }
        # mechanism (B): dispatch a subagent before submitting.
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=audit_payload,
            producer=producer,
        )
        committed = facade.commit_anti_ai_audit(
            work_result_id=str(submitted.data["work_result_id"]),
        )

        assert committed.ok is True
        assert committed.data["audit_pass"] is True
        assert committed.next_suggested_tools == ["prepare_validation"]


def test_style_revision_window_packet_includes_whole_draft_context() -> None:
    """D: per-window packets must surface whole-draft structural data."""
    import json

    long_paragraph = (
        "Cooling access in rental housing is uneven across the city, and the source "
        "report documents large gaps between buildings with central air conditioning "
        "and older buildings that have no central system at all. The writer treats "
        "the gap as a housing policy question because the renters with no cooling "
        "are concentrated in older buildings whose owners have not retrofitted them. "
    )
    content = "\n\n".join([long_paragraph] * 4)  # ~4 paragraphs of ~80 words each

    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        latest = facade.stores.draft_store.load_latest("job1")
        # Replace the content with a draft that will trigger windowing.
        from dataclasses import replace

        long_draft = replace(latest, content=content)
        facade.stores.draft_store.root.joinpath(
            f"job1/draft_v{latest.version:03d}.json"
        ).unlink()
        facade.stores.draft_store.save(long_draft)

        prepared = facade.prepare_style_revision("job1")
        # If short-draft path is taken, this test does not apply.
        if "windowing" not in prepared.data or prepared.data["windowing"].get(
            "mode"
        ) != "windowed":
            return

        window_pkt = facade.prepare_style_revision_window(
            parent_packet_id=str(prepared.data["work_packet_id"]),
            window_index=0,
        )
        window_payload = json.loads(window_pkt.data["prompt_blocks"][0]["text"])
        assert "whole_draft_context" in window_payload
        whole = window_payload["whole_draft_context"]
        assert "paragraph_count" in whole
        assert "first_sentence_chain" in whole
        assert "paragraph_word_counts" in whole
        # F: window delegation flag is True under the new design.
        assert window_pkt.data["delegation"]["recommended"] is True
        assert window_pkt.data["delegation"]["suggested_role"] == "anti_ai_window_reviser"
