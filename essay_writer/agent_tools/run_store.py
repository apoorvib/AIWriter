from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from essay_writer.agent_tools.id_utils import short_hash, timestamp_id
from essay_writer.agent_tools.json_io import list_json_files, read_json, write_json_atomic
from essay_writer.agent_tools.schemas import (
    AgentRun,
    AgentRunCheckpoint,
    AgentRunEvent,
    AgentRunRecovery,
    utc_now_iso,
)


class AgentRunStore:
    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.runs_dir = self.base_dir / "runs"
        self.events_dir = self.base_dir / "events"
        self.checkpoints_dir = self.base_dir / "checkpoints"
        for directory in (self.runs_dir, self.events_dir, self.checkpoints_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def start_run(
        self,
        *,
        objective: str,
        job_id: str | None = None,
        user_constraints: list[str] | None = None,
        initial_phase: str | None = None,
        phase_mode: str | None = None,
    ) -> AgentRun:
        """Create a new agent run.

        ``initial_phase`` lets callers seed the run's phase from a job
        that already exists (so a run started against a mid-flight job
        does not start at ``"bootstrap"``).

        ``phase_mode`` lets callers opt into ``"legacy"`` mode where the
        phase gate is a no-op. New runs default to ``"strict"``.
        """
        kwargs: dict[str, object] = {
            "agent_run_id": timestamp_id("agrun", job_id, short_hash(objective)),
            "objective": objective,
            "job_id": job_id,
            "user_constraints": list(user_constraints or []),
        }
        if initial_phase is not None:
            kwargs["current_phase"] = initial_phase
        if phase_mode is not None:
            kwargs["phase_mode"] = phase_mode
        run = AgentRun(**kwargs)  # type: ignore[arg-type]
        self._write_run(run)
        self.append_event(run.agent_run_id, "start", "Started agent run.")
        return run

    def load_run(self, agent_run_id: str) -> AgentRun:
        return AgentRun.from_dict(read_json(self.runs_dir / f"{agent_run_id}.json"))

    def update_run(self, run: AgentRun) -> AgentRun:
        current = replace(run, updated_at=utc_now_iso())
        self._write_run(current)
        return current

    def append_event(
        self,
        agent_run_id: str,
        event_type: str,
        message: str,
        *,
        data: dict[str, object] | None = None,
    ) -> AgentRunEvent:
        event = AgentRunEvent(
            agent_run_event_id=timestamp_id(
                "agrevt",
                agent_run_id,
                event_type,
                short_hash({"message": message, "data": data or {}}),
            ),
            agent_run_id=agent_run_id,
            event_type=event_type,
            message=message,
            data=dict(data or {}),
        )
        write_json_atomic(self.events_dir / f"{event.agent_run_event_id}.json", asdict(event))
        return event

    def checkpoint(
        self,
        agent_run_id: str,
        *,
        current_phase: str | None = None,
        decision: str | None = None,
        blocked_on: str | None = None,
        next_suggested_tools: list[str] | None = None,
    ) -> AgentRunCheckpoint:
        run = self.load_run(agent_run_id)
        status = run.status
        if current_phase is not None:
            phase = current_phase
        else:
            phase = run.current_phase
        tools = run.next_suggested_tools
        if next_suggested_tools is not None:
            tools = list(next_suggested_tools)
        if blocked_on is not None:
            status = "blocked"
        elif status == "blocked":
            status = "active"
        # Increment the stale-harness counter on a real phase advance.
        # (mechanism C) and append to phase_history (Gap 7).
        advances = run.phase_advances_since_harness_read
        phase_history = list(run.phase_history)
        if current_phase is not None and current_phase != run.current_phase:
            advances += 1
            phase_history.append(current_phase)
        current = replace(
            run,
            current_phase=phase,
            next_suggested_tools=tools,
            status=status,
            phase_advances_since_harness_read=advances,
            phase_history=phase_history,
        )
        checkpoint = AgentRunCheckpoint(
            agent_run_checkpoint_id=timestamp_id(
                "agchk",
                agent_run_id,
                current.current_phase,
                short_hash(
                    {
                        "decision": decision,
                        "blocked_on": blocked_on,
                        "pending": current.pending_work_packet_ids,
                        "completed": current.completed_work_result_ids,
                    }
                ),
            ),
            agent_run_id=agent_run_id,
            current_phase=current.current_phase,
            decision=decision,
            blocked_on=blocked_on,
            artifact_refs=dict(current.artifact_refs),
            pending_work_packet_ids=list(current.pending_work_packet_ids),
            completed_work_result_ids=list(current.completed_work_result_ids),
            committed_artifact_refs=dict(current.committed_artifact_refs),
            next_suggested_tools=list(current.next_suggested_tools),
        )
        write_json_atomic(
            self.checkpoints_dir / f"{checkpoint.agent_run_checkpoint_id}.json",
            asdict(checkpoint),
        )
        self.update_run(current)
        self.append_event(
            agent_run_id,
            "checkpoint",
            "Saved agent run checkpoint.",
            data={
                "checkpoint_id": checkpoint.agent_run_checkpoint_id,
                "current_phase": checkpoint.current_phase,
                "decision": decision,
                "blocked_on": blocked_on,
            },
        )
        return checkpoint

    def attach_work_packet(
        self,
        agent_run_id: str,
        work_packet_id: str,
        *,
        current_phase: str | None = None,
        next_suggested_tools: list[str] | None = None,
    ) -> AgentRun:
        run = self.load_run(agent_run_id)
        pending_ids = list(run.pending_work_packet_ids)
        if work_packet_id not in pending_ids:
            pending_ids.append(work_packet_id)
        new_phase = current_phase if current_phase is not None else run.current_phase
        # Increment the stale-harness counter on any real phase advance.
        # (mechanism C) and append to phase_history (Gap 7).
        advances = run.phase_advances_since_harness_read
        phase_history = list(run.phase_history)
        if current_phase is not None and current_phase != run.current_phase:
            advances += 1
            phase_history.append(current_phase)
        current = replace(
            run,
            pending_work_packet_ids=pending_ids,
            current_phase=new_phase,
            phase_advances_since_harness_read=advances,
            phase_history=phase_history,
            next_suggested_tools=(
                list(next_suggested_tools)
                if next_suggested_tools is not None
                else run.next_suggested_tools
            ),
        )
        saved = self.update_run(current)
        self.append_event(
            agent_run_id,
            "work_packet_attached",
            "Attached work packet to run.",
            data={"work_packet_id": work_packet_id},
        )
        return saved

    def attach_work_result(
        self,
        agent_run_id: str,
        work_result_id: str,
        *,
        work_packet_id: str | None = None,
        next_suggested_tools: list[str] | None = None,
    ) -> AgentRun:
        run = self.load_run(agent_run_id)
        completed_ids = list(run.completed_work_result_ids)
        if work_result_id not in completed_ids:
            completed_ids.append(work_result_id)
        pending_ids = list(run.pending_work_packet_ids)
        if work_packet_id is not None:
            pending_ids = [item for item in pending_ids if item != work_packet_id]
        current = replace(
            run,
            pending_work_packet_ids=pending_ids,
            completed_work_result_ids=completed_ids,
            next_suggested_tools=(
                list(next_suggested_tools)
                if next_suggested_tools is not None
                else run.next_suggested_tools
            ),
        )
        saved = self.update_run(current)
        self.append_event(
            agent_run_id,
            "work_result_attached",
            "Attached work result to run.",
            data={"work_result_id": work_result_id, "work_packet_id": work_packet_id},
        )
        return saved

    def attach_commit(
        self,
        agent_run_id: str,
        artifact_refs: dict[str, object],
        *,
        next_suggested_tools: list[str] | None = None,
    ) -> AgentRun:
        run = self.load_run(agent_run_id)
        current = replace(
            run,
            artifact_refs={**run.artifact_refs, **artifact_refs},
            committed_artifact_refs={**run.committed_artifact_refs, **artifact_refs},
            next_suggested_tools=(
                list(next_suggested_tools)
                if next_suggested_tools is not None
                else run.next_suggested_tools
            ),
        )
        saved = self.update_run(current)
        self.append_event(
            agent_run_id,
            "commit_attached",
            "Attached committed artifact refs to run.",
            data={"artifact_refs": dict(artifact_refs)},
        )
        return saved

    def recover(self, agent_run_id: str) -> AgentRunRecovery:
        run = self.load_run(agent_run_id)
        checkpoints = [
            checkpoint
            for checkpoint in self._list_checkpoints()
            if checkpoint.agent_run_id == agent_run_id
        ]
        checkpoints.sort(
            key=lambda checkpoint: (
                checkpoint.created_at,
                checkpoint.agent_run_checkpoint_id,
            )
        )
        events = [event for event in self._list_events() if event.agent_run_id == agent_run_id]
        events.sort(key=lambda event: (event.created_at, event.agent_run_event_id))
        latest_checkpoint = checkpoints[-1] if checkpoints else None
        state = _recoverable_state(run, latest_checkpoint)
        resume_instructions = (
            f"Resume agent run {agent_run_id} from phase {state['current_phase']}. "
            "Inspect pending work packets, completed results, and committed artifact refs; "
            f"then call next suggested tools: {', '.join(state['next_suggested_tools']) or 'none'}."
        )
        return AgentRunRecovery(
            agent_run_id=agent_run_id,
            run=run,
            latest_checkpoint=latest_checkpoint,
            recent_events=events[-20:],
            pending_work_packet_ids=list(state["pending_work_packet_ids"]),
            completed_work_result_ids=list(state["completed_work_result_ids"]),
            committed_artifact_refs=dict(state["committed_artifact_refs"]),
            next_suggested_tools=list(state["next_suggested_tools"]),
            resume_instructions=resume_instructions,
        )

    def list_runs(
        self,
        *,
        job_id: str | None = None,
        status: str | None = None,
    ) -> list[AgentRun]:
        runs = [AgentRun.from_dict(read_json(path)) for path in list_json_files(self.runs_dir)]
        if job_id is not None:
            runs = [run for run in runs if run.job_id == job_id]
        if status is not None:
            runs = [run for run in runs if run.status == status]
        return sorted(runs, key=lambda run: (run.created_at, run.agent_run_id), reverse=True)

    def _write_run(self, run: AgentRun) -> None:
        write_json_atomic(self.runs_dir / f"{run.agent_run_id}.json", asdict(run))

    def _list_events(self) -> list[AgentRunEvent]:
        return [AgentRunEvent.from_dict(read_json(path)) for path in list_json_files(self.events_dir)]

    def _list_checkpoints(self) -> list[AgentRunCheckpoint]:
        return [
            AgentRunCheckpoint.from_dict(read_json(path))
            for path in list_json_files(self.checkpoints_dir)
        ]


def _recoverable_state(
    run: AgentRun,
    latest_checkpoint: AgentRunCheckpoint | None,
) -> dict[str, object]:
    if latest_checkpoint is not None and latest_checkpoint.created_at >= run.updated_at:
        return {
            "current_phase": latest_checkpoint.current_phase,
            "pending_work_packet_ids": latest_checkpoint.pending_work_packet_ids,
            "completed_work_result_ids": latest_checkpoint.completed_work_result_ids,
            "committed_artifact_refs": latest_checkpoint.committed_artifact_refs,
            "next_suggested_tools": latest_checkpoint.next_suggested_tools,
        }
    return {
        "current_phase": run.current_phase,
        "pending_work_packet_ids": run.pending_work_packet_ids,
        "completed_work_result_ids": run.completed_work_result_ids,
        "committed_artifact_refs": run.committed_artifact_refs,
        "next_suggested_tools": run.next_suggested_tools,
    }
