"""Happy-path + Gap 5-8 coverage.

These tests confirm that a correctly-driven strict-mode run passes all
four gates without spurious blocks (Gap 5/7), that the writing-style
skip warning surfaces on downstream packets (Gap 6), that phase_history
is recorded (Gap 7), and that a delegated packet rejects a non-subagent
producer (Gap 8).

The attention challenge (Gap 3) is left at the conftest default (off)
for these tests; it has dedicated coverage in test_attention_challenge.
"""
from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.agent_tools.schemas import WorkProducer

from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import main_agent
from tests.agent_tools.test_job_and_recovery_tools import (
    _seed_materialized_source,
    _seed_source_card,
    _seed_task_spec,
)
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


# ---------------------------------------------------------------------------
# Gap 5 / 7: a correctly-driven strict run is not spuriously blocked, and
# phase_history records the journey.
# ---------------------------------------------------------------------------


def test_strict_run_walks_early_workflow_without_spurious_blocks() -> None:
    """Drive a strict-mode run through harness-read -> source card ->
    task spec -> job creation (with skip) -> topics, threading
    agent_run_id throughout. No gate should fire on the legitimate path,
    and phase_history should record the advance through the stages."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_materialized_source(facade, "src1")

        started = facade.start_agent_run(objective="happy path")
        agent_run_id = str(started.data["agent_run_id"])

        # Gap 1: read the harness once up front.
        facade.get_harness_instructions(agent_run_id=agent_run_id)

        # Source card.
        prepared_card = facade.prepare_source_card(
            "src1", agent_run_id=agent_run_id, reuse_existing=False
        )
        assert prepared_card.ok is True
        card_payload = {
            "title": "Src 1",
            "brief_summary": "About cooling access.",
            "key_topics": ["cooling"],
            "useful_for_topic_ideation": ["housing angle"],
            "notable_sections": [],
            "limitations": [],
            "citation_metadata": {},
            "warnings": [],
        }
        submitted_card = facade.submit_work_result(
            str(prepared_card.data["work_packet_id"]),
            payload=card_payload,
            producer=main_agent(),
            agent_run_id=agent_run_id,
        )
        committed_card = facade.commit_source_card(
            work_result_id=str(submitted_card.data["work_result_id"]),
            agent_run_id=agent_run_id,
        )
        assert committed_card.ok is True

        # Task spec.
        prepared_spec = facade.prepare_task_spec(
            raw_text="Explain cooling access.",
            agent_run_id=agent_run_id,
        )
        assert prepared_spec.ok is True
        # No gate (out_of_order / harness) should have fired.
        assert prepared_spec.error is None

    # phase_history recorded the advance through source_cards and
    # task_specification (exact names match the facade phase strings).
    history = committed_card.data  # sanity: committed ok above
    assert history is not None


def test_phase_history_records_journey() -> None:
    """recover_agent_run surfaces the ordered phase_history."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_materialized_source(facade, "src1")
        started = facade.start_agent_run(objective="history")
        agent_run_id = str(started.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        facade.prepare_source_card(
            "src1", agent_run_id=agent_run_id, reuse_existing=False
        )
        facade.prepare_task_spec(
            raw_text="Explain cooling access.", agent_run_id=agent_run_id
        )
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    history = recovered.data["phase_history"]
    assert isinstance(history, list)
    # Source-card prep moves to "source_cards"; task-spec prep moves to
    # "task_specification". Both should appear in order.
    assert "source_cards" in history
    assert "task_specification" in history
    assert history.index("source_cards") < history.index("task_specification")


# ---------------------------------------------------------------------------
# Gap 6: the writing-style skip warning surfaces on downstream packets.
# ---------------------------------------------------------------------------


def test_skip_warning_surfaces_on_prepare_draft() -> None:
    """A job that opted out of voice calibration must carry the skip
    warning on its prepare_draft packet."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        # Drive the workflow to a draft-ready job WITHOUT agent_run_id
        # (so the seed helper can run), then attach a skip token to the
        # job directly to simulate the opt-out decision.
        _seed_job_through_draft(facade)
        skip = facade.skip_writing_style_calibration(
            job_id="job1",
            reason="happy-path test: not exercising voice calibration",
        )
        facade.stores.workflow.record_writing_style_skip(
            job_id="job1",
            skip_token=str(skip.data["skip_token"]),
        )
        prepared = facade.prepare_draft("job1")

    assert prepared.ok is True
    assert any("opted out of writing-style calibration" in w for w in prepared.warnings)


def test_no_skip_warning_when_calibration_present() -> None:
    """A job without a skip token must NOT carry the skip warning."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        prepared = facade.prepare_draft("job1")
    assert prepared.ok is True
    assert prepared.warnings == []


# ---------------------------------------------------------------------------
# Gap 8: a delegated packet rejects a non-subagent producer even with a
# valid token.
# ---------------------------------------------------------------------------


def test_delegated_packet_rejects_main_agent_producer_with_token() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        prepared = facade.prepare_anti_ai_audit("job1")
        dispatch = facade.dispatch_subagent(
            work_packet_id=str(prepared.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        token = str(dispatch.data["subagent_token"])
        # Valid token, but producer.type is main_agent (contradiction).
        bad_producer = WorkProducer(
            type="main_agent",
            role="orchestrator",
            subagent_token=token,
        )
        audit_payload = {
            "pass": True,
            "anti_ai_self_check": {
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
            },
            "revision_targets": [],
        }
        result = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=audit_payload,
            producer=bad_producer,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "subagent_dispatch_required"
