"""Tests for the require-agent-run gate (Gap H1).

The dominant bypass identified in review: because every gate keys off
``agent_run_id`` and that parameter was optional, an orchestrator could
skip the phase / stale / writing-style gates entirely by never passing
a run id. With ``require_agent_run=True`` (the production default),
stateful tools refuse calls that omit ``agent_run_id``.

These tests construct the facade with the flag ON explicitly (overriding
the conftest default-off).
"""
from __future__ import annotations

from essay_writer.agent_tools.facade import (
    _RUN_REQUIRED_TOOLS,
    AgentToolFacade,
)

from tests.agent_tools._tmp import LocalAgentTempDir


def _enforced(tmp) -> AgentToolFacade:
    return AgentToolFacade.from_data_dir(
        tmp / "data",
        require_agent_run=True,
    )


def test_stateful_tool_without_run_is_rejected() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        # prepare_task_spec is a stateful tool; no agent_run_id supplied.
        result = facade.prepare_task_spec(raw_text="Explain something.")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "agent_run_required"
    assert "start_agent_run" in result.next_suggested_tools


def test_create_job_without_run_is_rejected() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        result = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "agent_run_required"


def test_stateful_tool_with_run_passes_the_requirement() -> None:
    """With a run supplied, the requirement is satisfied (the call may
    still fail later for other reasons, but not agent_run_required)."""
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        started = facade.start_agent_run(objective="enforced run")
        agent_run_id = str(started.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        result = facade.prepare_task_spec(
            raw_text="Explain something.",
            agent_run_id=agent_run_id,
        )
    if result.error is not None:
        assert result.error.code != "agent_run_required"


def test_read_only_tools_do_not_require_run() -> None:
    """Read-only / bootstrap tools are not in _RUN_REQUIRED_TOOLS and work
    without a run even under enforcement."""
    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        harness = facade.get_harness_instructions()
        runs = facade.list_agent_runs()
    assert harness.ok is True
    assert runs.ok is True


def test_required_tool_set_excludes_bootstrap_and_readonly() -> None:
    # Guard against accidentally requiring a run on tools that must work
    # before a run exists or that never mutate state.
    for tool in (
        "start_agent_run",
        "recover_agent_run",
        "get_agent_run_state",
        "get_harness_instructions",
        "list_agent_runs",
        "ingest_source_file",
        "ingest_writing_style_sample",
        "get_draft",
        "list_sources",
    ):
        assert tool not in _RUN_REQUIRED_TOOLS


def test_dispatch_subagent_without_run_is_rejected() -> None:
    # bug_006: dispatch_subagent is in _RUN_REQUIRED_TOOLS but used to wrap its
    # gate in `if agent_run_id is not None`, silently skipping the requirement.
    from essay_writer.agent_tools.schemas import DelegationHint, WorkPacket

    with LocalAgentTempDir() as tmp:
        facade = _enforced(tmp)
        packet = WorkPacket(
            work_packet_id="wp-1",
            stage="anti_ai_audit",
            scope="job:job1",
            instructions="x",
            system_prompt="x",
            prompt_blocks=[],
            response_schema={},
            context={},
            artifact_refs={"job_id": "job1"},
            commit_tool="commit_anti_ai_audit",
            delegation=DelegationHint(recommended=True),
            delegation_required=True,
        )
        facade.work_store.save_packet(packet)
        result = facade.dispatch_subagent(
            work_packet_id="wp-1",
            role="anti_ai_auditor",
            model_tier="opus",
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "agent_run_required"


def test_disabled_flag_allows_runless_calls() -> None:
    """With the flag off (conftest default), runless stateful calls are
    allowed for backward compatibility."""
    with LocalAgentTempDir() as tmp:
        # conftest forces require_agent_run=False here.
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        result = facade.prepare_task_spec(raw_text="Explain something.")
    # No agent_run_required error when the flag is off.
    if result.error is not None:
        assert result.error.code != "agent_run_required"
