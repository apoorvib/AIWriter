"""Tests for the stale-harness check (mechanism C).

The counter starts at 0 for a fresh run. Every phase advance increments
it. After ``STALE_HARNESS_AFTER_PHASE_ADVANCES`` advances, a stateful
write call (``prepare_*`` or ``commit_*``) returns ``harness_stale``.
Calling ``get_harness_instructions(agent_run_id=...)`` resets the
counter.

The time-based threshold is harder to test deterministically without
clock control, so this file uses the phase-advance count as the lever.
"""
from __future__ import annotations

from dataclasses import replace

from essay_writer.agent_tools.config import STALE_HARNESS_AFTER_PHASE_ADVANCES
from essay_writer.agent_tools.facade import AgentToolFacade

from tests.agent_tools._tmp import LocalAgentTempDir


def _bump_advances(facade: AgentToolFacade, agent_run_id: str, n: int) -> None:
    run = facade.run_store.load_run(agent_run_id)
    facade.run_store.update_run(
        replace(run, phase_advances_since_harness_read=n)
    )


def test_fresh_run_blocks_prepare_with_harness_never_read() -> None:
    """Gap (1): a brand-new run has last_harness_read_at=None. The first
    stateful write must be blocked with ``harness_never_read`` so the
    orchestrator is forced to read the workflow at least once."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="fresh run")
        agent_run_id = str(started.data["agent_run_id"])
        result = facade.prepare_task_spec(
            raw_text="A short prompt.",
            agent_run_id=agent_run_id,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "harness_never_read"
    assert result.next_suggested_tools == ["get_harness_instructions"]


def test_first_read_unblocks_prepare() -> None:
    """After reading the harness once, the first stateful write is no
    longer blocked for never-read or staleness reasons."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="reads harness")
        agent_run_id = str(started.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        result = facade.prepare_task_spec(
            raw_text="A short prompt.",
            agent_run_id=agent_run_id,
        )
    if result.error is not None:
        assert result.error.code not in ("harness_never_read", "harness_stale")


def test_stale_run_blocks_prepare_with_harness_stale() -> None:
    """When the phase-advance counter exceeds the threshold AFTER a prior
    read, the next stateful write returns ``harness_stale``."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="stale run")
        agent_run_id = str(started.data["agent_run_id"])
        # Read once to clear the never-read state, then drive the counter
        # back up past the staleness threshold.
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        _bump_advances(facade, agent_run_id, STALE_HARNESS_AFTER_PHASE_ADVANCES)

        result = facade.prepare_task_spec(
            raw_text="A short prompt.",
            agent_run_id=agent_run_id,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "harness_stale"
    assert result.next_suggested_tools == ["get_harness_instructions"]
    detail = result.error.detail
    assert (
        detail["phase_advances_since_harness_read"]
        == STALE_HARNESS_AFTER_PHASE_ADVANCES
    )


def test_get_harness_instructions_resets_counter() -> None:
    """Calling ``get_harness_instructions(agent_run_id=...)`` zeros the
    advance counter and stamps the last-read timestamp, so the next
    prepare/commit call is no longer stale."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="reset counter")
        agent_run_id = str(started.data["agent_run_id"])
        _bump_advances(facade, agent_run_id, STALE_HARNESS_AFTER_PHASE_ADVANCES + 2)

        # Read the harness to reset.
        harness = facade.get_harness_instructions(agent_run_id=agent_run_id)
        run_after = facade.run_store.load_run(agent_run_id)

    assert harness.ok is True
    assert run_after.phase_advances_since_harness_read == 0
    assert run_after.last_harness_read_at is not None


def test_legacy_mode_bypasses_stale_harness_check() -> None:
    """Legacy-mode runs never trigger ``harness_stale``."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(
            objective="legacy stale",
            phase_mode="legacy",
        )
        agent_run_id = str(started.data["agent_run_id"])
        _bump_advances(facade, agent_run_id, STALE_HARNESS_AFTER_PHASE_ADVANCES * 5)

        result = facade.prepare_task_spec(
            raw_text="A short prompt.",
            agent_run_id=agent_run_id,
        )
    # Legacy bypasses both the phase gate and the stale-harness check.
    if result.error is not None:
        assert result.error.code != "harness_stale"


def test_read_only_tools_do_not_trigger_stale_check() -> None:
    """``get_agent_run_state`` and similar read-only tools never trigger
    the stale-harness check, even on a very stale run."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="read-only stale")
        agent_run_id = str(started.data["agent_run_id"])
        _bump_advances(facade, agent_run_id, STALE_HARNESS_AFTER_PHASE_ADVANCES * 5)

        state = facade.get_agent_run_state(agent_run_id=agent_run_id)
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)
    assert state.ok is True
    assert recovered.ok is True
