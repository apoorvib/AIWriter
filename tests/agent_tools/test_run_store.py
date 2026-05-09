from __future__ import annotations

from dataclasses import asdict

from essay_writer.agent_tools.json_io import write_json_atomic
from essay_writer.agent_tools.run_store import AgentRunStore

from ._tmp import LocalAgentTempDir


def test_run_store_tracks_checkpoints_work_and_recovery_state() -> None:
    with LocalAgentTempDir() as tmp:
        store = AgentRunStore(tmp / "agent_runs")

        run = store.start_run(
            objective="Create an outline.",
            job_id="job1",
            user_constraints=["No API-backed LLM calls."],
        )
        store.append_event(
            run.agent_run_id,
            "note",
            "Gathered context.",
            data={"source": "test"},
        )
        store.attach_work_packet(
            run.agent_run_id,
            "workpkt_job1_outline_001",
            current_phase="outline",
            next_suggested_tools=["submit_work_result"],
        )
        store.attach_work_result(
            run.agent_run_id,
            "workres_workpkt_job1_outline_001_abcd1234",
            work_packet_id="workpkt_job1_outline_001",
            next_suggested_tools=["commit_outline"],
        )
        store.attach_commit(
            run.agent_run_id,
            {"outline_id": "thesis_outline_v001"},
            next_suggested_tools=["checkpoint_run"],
        )
        checkpoint = store.checkpoint(
            run.agent_run_id,
            current_phase="drafting",
            decision="Outline accepted.",
            blocked_on=None,
            next_suggested_tools=["prepare_draft_packet"],
        )

        recovered = store.recover(run.agent_run_id)
        loaded = store.load_run(run.agent_run_id)
        job_runs = store.list_runs(job_id="job1")
        active_runs = store.list_runs(status="active")

    assert loaded.current_phase == "drafting"
    assert checkpoint.current_phase == "drafting"
    assert recovered.run.agent_run_id == run.agent_run_id
    assert recovered.latest_checkpoint is not None
    assert recovered.latest_checkpoint.decision == "Outline accepted."
    assert recovered.recent_events[-1].event_type == "checkpoint"
    assert recovered.pending_work_packet_ids == []
    assert recovered.completed_work_result_ids == [
        "workres_workpkt_job1_outline_001_abcd1234"
    ]
    assert recovered.committed_artifact_refs["outline_id"] == "thesis_outline_v001"
    assert recovered.next_suggested_tools == ["prepare_draft_packet"]
    assert "drafting" in recovered.resume_instructions
    assert "pending" in recovered.resume_instructions
    assert job_runs[0].agent_run_id == run.agent_run_id
    assert active_runs[0].agent_run_id == run.agent_run_id


def test_recovery_uses_newer_checkpoint_when_run_record_is_stale() -> None:
    with LocalAgentTempDir() as tmp:
        store = AgentRunStore(tmp / "agent_runs")

        run = store.start_run(objective="Create source cards.", job_id="job1")
        checkpoint = store.checkpoint(
            run.agent_run_id,
            current_phase="source_cards",
            decision="Materialized sources are ready.",
            next_suggested_tools=["prepare_source_card"],
        )
        write_json_atomic(store.runs_dir / f"{run.agent_run_id}.json", asdict(run))

        recovered = store.recover(run.agent_run_id)

    assert checkpoint.current_phase == "source_cards"
    assert recovered.latest_checkpoint is not None
    assert recovered.next_suggested_tools == ["prepare_source_card"]
    assert "source_cards" in recovered.resume_instructions


def test_recovery_uses_later_run_state_after_checkpoint() -> None:
    with LocalAgentTempDir() as tmp:
        store = AgentRunStore(tmp / "agent_runs")

        run = store.start_run(objective="Create an outline.", job_id="job1")
        store.checkpoint(
            run.agent_run_id,
            current_phase="outline",
            decision="Outline packet prepared.",
            next_suggested_tools=["submit_work_result"],
        )
        store.attach_commit(
            run.agent_run_id,
            {"outline_id": "thesis_outline_v001"},
            next_suggested_tools=["prepare_draft_packet"],
        )

        recovered = store.recover(run.agent_run_id)

    assert recovered.committed_artifact_refs["outline_id"] == "thesis_outline_v001"
    assert recovered.next_suggested_tools == ["prepare_draft_packet"]
    assert "prepare_draft_packet" in recovered.resume_instructions
