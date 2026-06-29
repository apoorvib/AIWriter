"""Integration test for the four enforcement mechanisms.

Each gate is exercised in its own isolated facade instance so the
mechanisms cannot leak state between each other. The point is to
confirm that all four error codes still appear when they should after
all four mechanisms are wired together. A regression in any one
mechanism shows up as a failing test here without other tests masking
it.
"""
from __future__ import annotations

from dataclasses import replace

from essay_writer.agent_tools.config import STALE_HARNESS_AFTER_PHASE_ADVANCES
from essay_writer.agent_tools.facade import AgentToolFacade

from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import anti_ai_audit_payload, dispatched_subagent, main_agent
from tests.agent_tools.test_job_and_recovery_tools import (
    _seed_materialized_source,
    _seed_source_card,
    _seed_task_spec,
)
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


def test_phase_gate_fires_out_of_order() -> None:
    """(A) Phase gate."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="phase gate")
        agent_run_id = str(started.data["agent_run_id"])
        # prepare_draft requires outlining/drafting; we are at bootstrap.
        result = facade.prepare_draft("job1", agent_run_id=agent_run_id)
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "out_of_order"


def test_writing_style_gate_fires_at_create_job() -> None:
    """(D) Writing-style gate."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")
        started = facade.start_agent_run(objective="writing-style gate")
        agent_run_id = str(started.data["agent_run_id"])
        result = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "writing_style_required"


def test_stale_harness_gate_fires_then_resets() -> None:
    """(C) Stale-harness gate."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="stale harness")
        agent_run_id = str(started.data["agent_run_id"])
        # Read once to clear the never-read state, then bump the counter
        # beyond the staleness threshold without reading again.
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        facade.run_store.update_run(
            replace(
                facade.run_store.load_run(agent_run_id),
                phase_advances_since_harness_read=STALE_HARNESS_AFTER_PHASE_ADVANCES,
            )
        )
        stale = facade.prepare_task_spec(
            raw_text="A short prompt.",
            agent_run_id=agent_run_id,
        )
        assert stale.ok is False
        assert stale.error is not None
        assert stale.error.code == "harness_stale"

        # Reset by reading the harness, then confirm the next call is no
        # longer blocked for staleness.
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        after_reset = facade.prepare_task_spec(
            raw_text="A short prompt.",
            agent_run_id=agent_run_id,
        )
    if after_reset.error is not None:
        assert after_reset.error.code != "harness_stale"


def test_subagent_dispatch_gate_fires_for_audit_packet() -> None:
    """(B) Subagent dispatch gate."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        prepared = facade.prepare_anti_ai_audit("job1")
        draft = facade.stores.draft_store.find_by_id("job1", str(prepared.data["draft_id"]))
        audit_payload = anti_ai_audit_payload(draft_text=draft.content)
        # Without a dispatch token: rejected.
        no_token = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=audit_payload,
            producer=main_agent(),
        )
        assert no_token.ok is False
        assert no_token.error is not None
        assert no_token.error.code == "subagent_dispatch_required"

        # With a token: accepted.
        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        with_token = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=audit_payload,
            producer=producer,
        )
    assert with_token.ok is True
