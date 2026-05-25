"""Facade-level tests for the phase gate.

These cover the wiring done in mechanism (A2): each ``facade`` tool that
takes ``agent_run_id`` runs the phase gate at the top of its body and
returns an ``out_of_order`` ``ToolResult`` when the call is not allowed
in the current phase.

Legacy-mode runs (created with ``phase_mode="legacy"``) bypass the gate;
new strict-mode runs do not.
"""
from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade

from tests.agent_tools._tmp import LocalAgentTempDir


def test_strict_run_blocks_out_of_order_tool_call() -> None:
    """A strict-mode run sitting at phase=bootstrap must reject any
    tool that requires a later phase, and must surface the correct
    error code, current phase, and expected phases."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="strict mode test")
        agent_run_id = str(started.data["agent_run_id"])

        # prepare_draft requires the run to be in {outlining, drafting};
        # a brand-new run is at "bootstrap" so this must fail closed.
        result = facade.prepare_draft("job1", agent_run_id=agent_run_id)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "out_of_order"
    assert result.error.detail["current_phase"] == "bootstrap"
    expected = result.error.detail["expected_phases"]
    assert "drafting" in expected
    assert "outlining" in expected
    assert result.error.detail["wrong_call"] == "prepare_draft"
    # next_suggested_tools must steer the orchestrator toward tools that
    # ARE legal from the current phase.
    assert any(
        tool in result.next_suggested_tools
        for tool in ("ingest_source_file", "prepare_source_card", "prepare_task_spec")
    )


def test_legacy_run_bypasses_phase_gate() -> None:
    """A run started in legacy mode must NOT have the gate applied,
    so the same out-of-order call that fails in strict mode succeeds
    here (or at least fails for a different reason)."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(
            objective="legacy mode test",
            phase_mode="legacy",
        )
        agent_run_id = str(started.data["agent_run_id"])

        result = facade.prepare_draft("job1", agent_run_id=agent_run_id)

    # The result may still fail (job1 does not exist) but it must NOT
    # fail with code="out_of_order".
    if result.error is not None:
        assert result.error.code != "out_of_order"


def test_no_agent_run_id_bypasses_phase_gate() -> None:
    """Tools called without agent_run_id have no run to check, so the
    gate is a no-op. The call may fail for other reasons (missing job
    artifact, missing source, etc.) but never with out_of_order."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        result = facade.prepare_draft("job1")
    if result.error is not None:
        assert result.error.code != "out_of_order"


def test_strict_mode_is_default_for_new_runs() -> None:
    """New runs default to strict mode. We can confirm this by observing
    the gate fire on an unrelated out-of-order call."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="default mode")
        agent_run_id = str(started.data["agent_run_id"])
        result = facade.prepare_validation("job1", agent_run_id=agent_run_id)
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "out_of_order"


def test_start_agent_run_inherits_phase_from_existing_job() -> None:
    """When ``start_agent_run`` is called with a ``job_id`` for a job
    that already exists, the run inherits the job's current_stage as
    its initial phase. The gate then allows tools that are valid for
    that mid-flight job."""
    from tests.agent_tools.test_job_and_recovery_tools import (
        _seed_materialized_source,
        _seed_source_card,
        _seed_task_spec,
    )

    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")
        facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
        )

        # Job1 is now in "topic_ideation" stage. A fresh run linked to
        # job1 should inherit that phase and allow prepare_topics.
        started = facade.start_agent_run(
            objective="continue an existing job",
            job_id="job1",
        )
        assert started.data["current_phase"] == "topic_ideation"


def test_resuming_run_on_odd_stage_job_is_not_bricked() -> None:
    """Tier-1 fix: a job whose current_stage uses the job-store
    vocabulary ('source_ingestion') must not brick a run started against
    it. The inherited phase is normalized to a valid run phase, so a
    legitimate next tool is allowed rather than every tool returning
    out_of_order."""
    from dataclasses import replace as _replace

    from tests.agent_tools.test_job_and_recovery_tools import (
        _seed_materialized_source,
        _seed_source_card,
        _seed_task_spec,
    )

    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")
        facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
        )
        # Force the job into the job-store-vocabulary stage that is NOT a
        # run-phase string.
        job = facade.stores.workflow.load_job("job1")
        facade.stores.workflow._job_store.save(
            _replace(job, current_stage="source_ingestion")
        )

        started = facade.start_agent_run(
            objective="resume odd-stage job",
            job_id="job1",
        )
        # The inherited phase must be a valid run phase, not the raw
        # 'source_ingestion' job stage.
        assert started.data["current_phase"] == "source_cards"


def test_read_only_tools_pass_through_gate() -> None:
    """Read-only tools (get_harness_instructions, get_agent_run_state,
    etc.) are always allowed regardless of phase."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="read-only test")
        agent_run_id = str(started.data["agent_run_id"])

        # Both should succeed from phase=bootstrap.
        harness = facade.get_harness_instructions()
        state = facade.get_agent_run_state(agent_run_id=agent_run_id)

    assert harness.ok is True
    assert state.ok is True
