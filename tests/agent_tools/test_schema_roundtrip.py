from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from essay_writer.agent_tools.config import AgentToolConfig
from essay_writer.agent_tools.schemas import (
    AgentRun,
    AgentRunCheckpoint,
    AgentRunEvent,
    AgentRunRecovery,
    CommitRecord,
    DelegationHint,
    PromptBlock,
    SourcePacketBundle,
    ToolError,
    ToolResult,
    WorkPacket,
    WorkProducer,
    WorkResult,
)

from .helpers import main_agent


def test_work_packet_roundtrips_nested_prompt_blocks_and_delegation() -> None:
    packet = WorkPacket(
        work_packet_id="workpkt_job1_outline_001",
        stage="outline",
        scope="job:job1",
        instructions="Create an outline.",
        system_prompt="Outline system prompt",
        prompt_blocks=[PromptBlock(text='{"topic":"AI"}', cacheable=True)],
        response_schema={"type": "object"},
        context={"job_id": "job1"},
        artifact_refs={"job_id": "job1"},
        commit_tool="commit_outline",
        delegation=DelegationHint(
            recommended=True,
            reason="The harness should draft the outline.",
            suggested_role="outline_subagent",
        ),
    )

    loaded = WorkPacket.from_dict(asdict(packet))

    assert loaded.work_packet_id == "workpkt_job1_outline_001"
    assert loaded.delegation.recommended is True
    assert loaded.prompt_blocks[0].text == '{"topic":"AI"}'


def test_tool_result_defaults_to_agent_tool_no_api_mode() -> None:
    result = ToolResult(ok=True, tool_name="get_harness_instructions")

    assert result.mode == "agent_tool_no_api"
    assert result.ok is True


def test_work_result_preserves_payload_and_explicit_hash() -> None:
    result = WorkResult(
        work_result_id="workres_job1_outline_001",
        work_packet_id="workpkt_job1_outline_001",
        status="submitted",
        producer=main_agent(),
        payload={"outline": ["Claim", "Evidence"]},
        payload_hash="sha256:abc",
    )

    assert result.payload["outline"] == ["Claim", "Evidence"]
    assert result.payload_hash.startswith("sha256:")


def test_agent_run_defaults_and_pending_ids_roundtrip() -> None:
    run = AgentRun(
        agent_run_id="agrun_job1_001",
        objective="Prepare an essay outline.",
        current_phase="outline",
        artifact_refs={"job_id": "job1"},
        pending_work_packet_ids=["workpkt_job1_outline_001"],
        next_suggested_tools=["submit_work_result"],
    )

    assert run.mode == "agent_tool_no_api"
    assert run.status == "active"
    assert run.pending_work_packet_ids == ["workpkt_job1_outline_001"]


def test_persisted_schema_dataclasses_roundtrip_from_dict() -> None:
    error = ToolError(code="bad_request", message="Invalid packet.", detail={"field": "payload"})
    producer = WorkProducer(type="subagent", role="source_card_writer", name="worker-1")
    commit = CommitRecord(
        commit_id="commit_job1_outline_001",
        scope="job:job1",
        stage="outline",
        work_packet_id="workpkt_job1_outline_001",
        work_result_id="workres_job1_outline_001",
        artifact_refs={"outline_id": "thesis_outline_v001"},
    )
    run = AgentRun(
        agent_run_id="agrun_job1_001",
        objective="Prepare an essay outline.",
        current_phase="outline",
    )
    event = AgentRunEvent(
        agent_run_event_id="agrevt_job1_001",
        agent_run_id=run.agent_run_id,
        event_type="checkpoint",
        message="Saved checkpoint.",
        data={"phase": "outline"},
    )
    checkpoint = AgentRunCheckpoint(
        agent_run_checkpoint_id="agchk_job1_001",
        agent_run_id=run.agent_run_id,
        current_phase="outline",
        pending_work_packet_ids=["workpkt_job1_outline_001"],
        next_suggested_tools=["submit_work_result"],
    )
    recovery = AgentRunRecovery(
        agent_run_id=run.agent_run_id,
        run=run,
        latest_checkpoint=checkpoint,
        recent_events=[event],
        pending_work_packet_ids=["workpkt_job1_outline_001"],
        completed_work_result_ids=[],
        committed_artifact_refs={},
        next_suggested_tools=["submit_work_result"],
        resume_instructions="Resume from outline.",
    )
    bundle = SourcePacketBundle(
        source_packet_bundle_id="spbundle_job1_research_001",
        scope="job:job1",
        packet_payloads=[{"packet_id": "src1-c1", "text": "Evidence text."}],
    )

    assert ToolError.from_dict(asdict(error)).detail["field"] == "payload"
    assert WorkProducer.from_dict(asdict(producer)).type == "subagent"
    assert CommitRecord.from_dict(asdict(commit)).artifact_refs["outline_id"] == "thesis_outline_v001"
    assert AgentRunEvent.from_dict(asdict(event)).data["phase"] == "outline"
    assert AgentRunCheckpoint.from_dict(asdict(checkpoint)).pending_work_packet_ids == [
        "workpkt_job1_outline_001"
    ]
    restored_recovery = AgentRunRecovery.from_dict(asdict(recovery))
    assert restored_recovery.latest_checkpoint is not None
    assert restored_recovery.recent_events[0].event_type == "checkpoint"
    assert SourcePacketBundle.from_dict(asdict(bundle)).packet_payloads[0]["packet_id"] == "src1-c1"


def test_agent_tool_config_defaults_to_derived_directories() -> None:
    config = AgentToolConfig(base_dir=Path("state"))
    from_base = AgentToolConfig.from_base_dir(Path("state"))

    assert config.base_dir == Path("state")
    assert config.work_dir == Path("state") / "agent_work"
    assert config.run_dir == Path("state") / "agent_runs"
    assert from_base == config
