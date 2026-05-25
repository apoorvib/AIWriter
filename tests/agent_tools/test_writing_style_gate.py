"""Tests for the writing-style gate and skip-token plumbing (mechanism D).

The gate fires inside ``create_job_from_artifacts`` when:
- ``agent_run_id`` is set (the orchestrator is driving the workflow), AND
- no writing-style content is attached to the (existing or to-be-created) job, AND
- no valid ``writing_style_skip_token`` was supplied.

A valid skip token is issued by ``skip_writing_style_calibration`` and is
scoped to a specific job_id + scope. The token is persisted onto the job
so idempotent retries skip the gate.
"""
from __future__ import annotations

from pathlib import Path

from essay_writer.agent_tools.facade import AgentToolFacade

from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.test_job_and_recovery_tools import (
    _seed_materialized_source,
    _seed_source_card,
    _seed_task_spec,
)


def _ready_facade(tmp: Path) -> tuple[AgentToolFacade, str]:
    facade = AgentToolFacade.from_data_dir(tmp / "data")
    _seed_task_spec(facade, "task1", ["src1"])
    _seed_materialized_source(facade, "src1")
    _seed_source_card(facade, "src1")
    started = facade.start_agent_run(objective="writing-style gate test")
    agent_run_id = str(started.data["agent_run_id"])
    return facade, agent_run_id


def test_create_job_blocks_when_no_writing_style_and_no_token() -> None:
    """With ``agent_run_id`` set and neither writing-style content nor a
    skip token, ``create_job_from_artifacts`` must fail with the
    ``writing_style_required`` error code and surface a remediation."""
    with LocalAgentTempDir() as tmp:
        facade, agent_run_id = _ready_facade(tmp)
        result = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "writing_style_required"
    detail = result.error.detail
    assert detail["scope"] == "writing_style"
    assert "samples_directory" in detail
    assert "skip_writing_style_calibration" in result.next_suggested_tools


def test_skip_token_lets_create_job_proceed() -> None:
    """Calling ``skip_writing_style_calibration`` issues a token that the
    next ``create_job_from_artifacts`` call accepts."""
    with LocalAgentTempDir() as tmp:
        facade, agent_run_id = _ready_facade(tmp)
        skip = facade.skip_writing_style_calibration(
            job_id="job1",
            reason="not exercising voice calibration in this run",
            agent_run_id=agent_run_id,
        )
        token = str(skip.data["skip_token"])

        created = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
            writing_style_skip_token=token,
        )
    assert skip.ok is True
    assert created.ok is True
    assert created.data["job_id"] == "job1"


def test_idempotent_retry_remembers_skip_decision() -> None:
    """Once a job is created with a skip token, a subsequent
    ``create_job_from_artifacts`` for that same job (e.g. recovery
    retry without re-passing the token) must not re-fire the gate."""
    with LocalAgentTempDir() as tmp:
        facade, agent_run_id = _ready_facade(tmp)
        skip = facade.skip_writing_style_calibration(
            job_id="job1",
            reason="unit test does not exercise voice calibration",
            agent_run_id=agent_run_id,
        )
        first = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
            writing_style_skip_token=str(skip.data["skip_token"]),
        )
        # Note: no token on the retry. The job already recorded the
        # decision, so the gate must not re-fire.
        retry = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
        )
    assert first.ok is True
    assert retry.ok is True
    assert retry.data["already_existing"] is True


def test_skip_calibration_rejects_empty_reason() -> None:
    """The reason field is mandatory and must be non-empty."""
    with LocalAgentTempDir() as tmp:
        facade, agent_run_id = _ready_facade(tmp)
        result = facade.skip_writing_style_calibration(
            job_id="job1",
            reason="",
            agent_run_id=agent_run_id,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "reason_required"


def test_invalid_skip_token_returns_specific_error() -> None:
    """A skip token from a different job or a fabricated token must be
    rejected with ``writing_style_skip_token_invalid``."""
    with LocalAgentTempDir() as tmp:
        facade, agent_run_id = _ready_facade(tmp)
        # Issue a token for a DIFFERENT job, then try to use it on job1.
        other = facade.skip_writing_style_calibration(
            job_id="other-job",
            reason="for another job",
            agent_run_id=agent_run_id,
        )
        result = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
            writing_style_skip_token=str(other.data["skip_token"]),
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "writing_style_skip_token_invalid"


def test_gate_is_no_op_without_agent_run_id() -> None:
    """When ``create_job_from_artifacts`` is called without
    ``agent_run_id`` (e.g. an ad-hoc CLI call), the gate is a no-op so
    existing scripts and tests are not broken."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")
        # No agent_run_id and no skip token -- must still succeed.
        result = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
        )
    assert result.ok is True


def test_discovered_samples_are_surfaced_in_error(tmp_path: Path) -> None:
    """If samples already exist in ``inputs/writing_style/`` under the
    current working directory, the error response surfaces their paths
    so the orchestrator does not need to be told they exist."""
    import os

    sample_dir = tmp_path / "inputs" / "writing_style"
    sample_dir.mkdir(parents=True)
    (sample_dir / "sample.md").write_text("test sample", encoding="utf-8")
    prev_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        with LocalAgentTempDir() as agent_tmp:
            facade, agent_run_id = _ready_facade(agent_tmp)
            result = facade.create_job_from_artifacts(
                task_spec_id="task1",
                source_ids=["src1"],
                job_id="job1",
                agent_run_id=agent_run_id,
            )
    finally:
        os.chdir(prev_cwd)
    assert result.ok is False
    assert result.error.code == "writing_style_required"
    samples = result.error.detail["samples_discovered"]
    assert any("sample.md" in path for path in samples)
    assert "ingest_writing_style_sample" in result.next_suggested_tools
