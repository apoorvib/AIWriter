from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from essay_writer.agent_tools.config import AgentToolConfig
from essay_writer.agent_tools.run_store import AgentRunStore
from essay_writer.agent_tools.schemas import (
    AgentRun,
    AgentRunEvent,
    ToolError,
    ToolResult,
)
from essay_writer.agent_tools.source_materialization import SourceMaterializationService
from essay_writer.agent_tools.stores import AgentStoreBundle
from essay_writer.agent_tools.work_store import AgentWorkStore
from essay_writer.sources.ingestion import FileTooLargeWithoutIndexError
from essay_writer.sources.schema import SourceIngestionConfig, SourceMaterializationResult


MODE_WARNING = "Agent Tool Mode only. Do not call Pipeline Mode tools."
MUST_REMEMBER = [
    "Use only Agent Tool Mode tools for persisted essay workflow actions.",
    "Do not call Pipeline Mode tools.",
    "Persisted AgentRun state is authoritative; chat memory is advisory.",
    "Recover the AgentRun after context compaction or uncertainty.",
]
START_NEXT_TOOLS = ["ingest_source_file", "prepare_source_card"]
CURRENTLY_CALLABLE_TOOLS = [
    "get_harness_instructions",
    "start_agent_run",
    "recover_agent_run",
    "get_agent_run_state",
    "list_agent_runs",
    "checkpoint_agent_run",
    "ingest_source_file",
]
PLANNED_WORKFLOW_TOOLS = [
    *CURRENTLY_CALLABLE_TOOLS,
    "ingest_source_file",
    "prepare_source_card",
    "submit_work_result",
    "commit_source_card",
    "prepare_task_spec",
    "commit_task_spec",
    "create_job_from_artifacts",
    "prepare_topics",
    "commit_topics",
    "select_topic",
    "reject_topic",
    "create_research_plan",
    "resolve_source_requests",
    "prepare_research_notes",
    "commit_research_notes",
    "prepare_outline",
    "commit_outline",
    "prepare_draft",
    "commit_draft",
    "prepare_validation",
    "commit_validation",
    "export_markdown",
]


@dataclass
class AgentToolFacade:
    config: AgentToolConfig
    stores: AgentStoreBundle
    work_store: AgentWorkStore
    run_store: AgentRunStore
    source_materializer: SourceMaterializationService
    llm_guard: object | None = None

    @classmethod
    def from_data_dir(
        cls,
        data_dir: str | Path,
        *,
        source_ingestion_config: SourceIngestionConfig | None = None,
        document_reader: object | None = None,
        ocr_extractor: object | None = None,
        llm_guard: object | None = None,
    ) -> "AgentToolFacade":
        os.environ["ESSAY_AGENT_TOOL_MODE"] = "1"
        config = AgentToolConfig.from_base_dir(data_dir)
        stores = AgentStoreBundle.from_data_dir(data_dir)
        work_store = AgentWorkStore(config.work_dir)
        run_store = AgentRunStore(config.run_dir)
        source_materializer = SourceMaterializationService(
            stores.source_store,
            config=source_ingestion_config,
            document_reader=document_reader,
            ocr_extractor=ocr_extractor,
        )
        return cls(
            config=config,
            stores=stores,
            work_store=work_store,
            run_store=run_store,
            source_materializer=source_materializer,
            llm_guard=llm_guard,
        )

    def get_harness_instructions(self) -> ToolResult:
        instructions_path = _repo_root() / "docs" / "agent-tool-mode-instructions.md"
        try:
            instructions = instructions_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            return _error_result(
                "get_harness_instructions",
                code="instructions_not_found",
                message=f"Agent Tool Mode instructions were not found: {instructions_path}",
                exc=exc,
            )
        return ToolResult(
            ok=True,
            tool_name="get_harness_instructions",
            data={
                "instructions": instructions,
                "mode_warning": MODE_WARNING,
                "must_remember": list(MUST_REMEMBER),
                "available_tools": list(PLANNED_WORKFLOW_TOOLS),
                "currently_callable_tools": list(CURRENTLY_CALLABLE_TOOLS),
                "planned_workflow_tools": list(PLANNED_WORKFLOW_TOOLS),
                "tool_availability_note": (
                    "available_tools is the planned Agent Tool Mode surface; "
                    "currently_callable_tools is the implemented bootstrap surface in this build."
                ),
            },
        )

    def start_agent_run(
        self,
        *,
        objective: str,
        job_id: str | None = None,
        user_constraints: list[str] | None = None,
    ) -> ToolResult:
        run = self.run_store.start_run(
            objective=objective,
            job_id=job_id,
            user_constraints=user_constraints,
        )
        if not run.next_suggested_tools:
            run = self.run_store.update_run(
                _run_with_next_tools(run, START_NEXT_TOOLS),
            )
        return ToolResult(
            ok=True,
            tool_name="start_agent_run",
            data={
                "agent_run_id": run.agent_run_id,
                "status": run.status,
                "current_phase": run.current_phase,
                "next_suggested_tools": list(run.next_suggested_tools),
                "must_remember": list(MUST_REMEMBER),
            },
        )

    def get_agent_run_state(self, *, agent_run_id: str) -> ToolResult:
        try:
            run = self.run_store.load_run(agent_run_id)
        except (KeyError, FileNotFoundError) as exc:
            return _missing_run_result("get_agent_run_state", agent_run_id, exc)
        return ToolResult(
            ok=True,
            tool_name="get_agent_run_state",
            data={**_run_state(run), "must_remember": list(MUST_REMEMBER)},
        )

    def list_agent_runs(
        self,
        *,
        job_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> ToolResult:
        runs = self.run_store.list_runs(job_id=job_id, status=status)[:limit]
        return ToolResult(
            ok=True,
            tool_name="list_agent_runs",
            data={
                "runs": [_run_summary(run) for run in runs],
                "must_remember": list(MUST_REMEMBER),
            },
        )

    def recover_agent_run(self, *, agent_run_id: str) -> ToolResult:
        try:
            recovery = self.run_store.recover(agent_run_id)
        except (KeyError, FileNotFoundError) as exc:
            return _missing_run_result("recover_agent_run", agent_run_id, exc)
        return ToolResult(
            ok=True,
            tool_name="recover_agent_run",
            data={
                "agent_run_id": recovery.agent_run_id,
                "current_phase": _recovered_current_phase(recovery),
                "status": recovery.run.status,
                "pending_work_packet_ids": list(recovery.pending_work_packet_ids),
                "completed_work_result_ids": list(recovery.completed_work_result_ids),
                "committed_artifact_refs": dict(recovery.committed_artifact_refs),
                "next_suggested_tools": list(recovery.next_suggested_tools),
                "recent_events": [_event_summary(event) for event in recovery.recent_events],
                "resume_instructions": recovery.resume_instructions,
                "must_remember": list(MUST_REMEMBER),
            },
        )

    def checkpoint_agent_run(
        self,
        *,
        agent_run_id: str,
        current_phase: str | None = None,
        decision: str | None = None,
        blocked_on: str | None = None,
        next_suggested_tools: list[str] | None = None,
    ) -> ToolResult:
        try:
            checkpoint = self.run_store.checkpoint(
                agent_run_id,
                current_phase=current_phase,
                decision=decision,
                blocked_on=blocked_on,
                next_suggested_tools=next_suggested_tools,
            )
        except (KeyError, FileNotFoundError) as exc:
            return _missing_run_result("checkpoint_agent_run", agent_run_id, exc)
        return ToolResult(
            ok=True,
            tool_name="checkpoint_agent_run",
            data={
                "agent_run_checkpoint_id": checkpoint.agent_run_checkpoint_id,
                "current_phase": checkpoint.current_phase,
                "blocked_on": checkpoint.blocked_on,
                "next_suggested_tools": list(checkpoint.next_suggested_tools),
                "must_remember": list(MUST_REMEMBER),
            },
        )

    def ingest_source_file(
        self,
        document_path: str | Path,
        *,
        source_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        path = Path(document_path)
        if not path.exists():
            return _error_result(
                "ingest_source_file",
                code="source_document_not_found",
                message=f"source document not found: {path}",
                exc=FileNotFoundError(path),
            )
        if not path.is_file():
            return _error_result(
                "ingest_source_file",
                code="source_document_not_file",
                message=f"source document is not a file: {path}",
                exc=IsADirectoryError(path),
            )
        suffix = path.suffix.lower()
        if suffix not in _SUPPORTED_SOURCE_SUFFIXES:
            return _error_result(
                "ingest_source_file",
                code="unsupported_source_type",
                message=(
                    f"unsupported source file type: {suffix or '<none>'}; "
                    f"supported suffixes: {', '.join(sorted(_SUPPORTED_SOURCE_SUFFIXES))}"
                ),
                exc=ValueError(suffix),
            )
        run = None
        if agent_run_id is not None:
            try:
                run = self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("ingest_source_file", agent_run_id, exc)

        try:
            result = self.source_materializer.materialize(path, source_id=source_id)
        except FileNotFoundError as exc:
            return _error_result(
                "ingest_source_file",
                code="source_document_not_found",
                message=str(exc),
                exc=exc,
            )
        except FileTooLargeWithoutIndexError as exc:
            return _error_result(
                "ingest_source_file",
                code="source_too_large_without_index",
                message=str(exc),
                exc=exc,
            )

        data = _source_materialization_data(self.stores.source_store, result)
        artifact_refs = data["artifact_refs"]
        if agent_run_id is not None:
            self.run_store.update_run(
                replace(
                    run,
                    artifact_refs={**run.artifact_refs, **dict(artifact_refs)},
                    next_suggested_tools=["prepare_source_card"],
                )
            )
            self.run_store.append_event(
                agent_run_id,
                "source_materialized",
                "Materialized source text artifacts.",
                data={"source_id": result.source.id, "artifact_refs": dict(artifact_refs)},
            )

        return ToolResult(
            ok=True,
            tool_name="ingest_source_file",
            data=data,
            warnings=list(result.warnings),
            next_suggested_tools=["prepare_source_card"],
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


_SUPPORTED_SOURCE_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown", ".notes"}


def _source_materialization_data(
    store: object,
    result: SourceMaterializationResult,
) -> dict[str, object]:
    source = result.source
    source_card_status = "committed" if store.has_source_card(source.id) else "pending"
    artifact_refs: dict[str, object] = {
        "source_id": source.id,
    }
    if result.source_map is not None:
        artifact_refs["source_map"] = f"essay://sources/{source.id}/map"
    if result.index_manifest is not None:
        artifact_refs["manifest"] = f"essay://sources/{source.id}/manifest"
    return {
        "source_id": source.id,
        "file_name": source.file_name,
        "source_type": source.source_type,
        "page_count": source.page_count,
        "char_count": source.char_count,
        "indexed": result.indexed,
        "full_text_available": result.full_text_available,
        "source_card_status": source_card_status,
        "artifact_refs": artifact_refs,
        "warnings": list(result.warnings),
    }


def _run_with_next_tools(run: AgentRun, next_tools: list[str]) -> AgentRun:
    return AgentRun(
        **{
            **asdict(run),
            "next_suggested_tools": list(next_tools),
        }
    )


def _run_state(run: AgentRun) -> dict[str, object]:
    return {
        "agent_run_id": run.agent_run_id,
        "objective": run.objective,
        "job_id": run.job_id,
        "status": run.status,
        "current_phase": run.current_phase,
        "artifact_refs": dict(run.artifact_refs),
        "pending_work_packet_ids": list(run.pending_work_packet_ids),
        "completed_work_result_ids": list(run.completed_work_result_ids),
        "committed_artifact_refs": dict(run.committed_artifact_refs),
        "next_suggested_tools": list(run.next_suggested_tools),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _run_summary(run: AgentRun) -> dict[str, object]:
    return {
        "agent_run_id": run.agent_run_id,
        "objective": run.objective,
        "job_id": run.job_id,
        "status": run.status,
        "current_phase": run.current_phase,
        "next_suggested_tools": list(run.next_suggested_tools),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _recovered_current_phase(recovery: object) -> str:
    latest_checkpoint = getattr(recovery, "latest_checkpoint")
    run = getattr(recovery, "run")
    if latest_checkpoint is not None and latest_checkpoint.created_at >= run.updated_at:
        return latest_checkpoint.current_phase
    return run.current_phase


def _event_summary(event: AgentRunEvent) -> dict[str, object]:
    return {
        "agent_run_event_id": event.agent_run_event_id,
        "event_type": event.event_type,
        "message": event.message,
        "data": dict(event.data),
        "created_at": event.created_at,
    }


def _missing_run_result(tool_name: str, agent_run_id: str, exc: Exception) -> ToolResult:
    return _error_result(
        tool_name,
        code="agent_run_not_found",
        message=f"AgentRun not found: {agent_run_id}",
        exc=exc,
    )


def _error_result(
    tool_name: str,
    *,
    code: str,
    message: str,
    exc: Exception,
) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=tool_name,
        error=ToolError(
            code=code,
            message=message,
            detail={"exception": type(exc).__name__},
        ),
    )
