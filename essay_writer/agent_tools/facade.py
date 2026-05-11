from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from essay_writer.agent_tools.config import AgentToolConfig
from essay_writer.agent_tools.run_store import AgentRunStore
from essay_writer.agent_tools.id_utils import safe_slug, short_hash, timestamp_id
from essay_writer.agent_tools.schemas import (
    AgentRun,
    AgentRunEvent,
    DelegationHint,
    PromptBlock,
    SourcePacketBundle,
    ToolError,
    ToolResult,
    WorkPacket,
    WorkProducer,
)
from essay_writer.agent_tools.source_materialization import SourceMaterializationService
from essay_writer.agent_tools.stores import AgentStoreBundle
from essay_writer.agent_tools.work_store import AgentWorkStore
from essay_writer.drafting.prompts import DRAFTING_SCHEMA, DRAFTING_SYSTEM_PROMPT
from essay_writer.exporting.service import FinalExportService
from essay_writer.jobs import TopicSelectionError
from essay_writer.outlining.service import OUTLINE_SCHEMA, OUTLINE_SYSTEM_PROMPT
from essay_writer.research.prompts import FINAL_TOPIC_RESEARCH_SCHEMA, FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT
from essay_writer.research_planning.service import ResearchPlanningService
from essay_writer.sources import summary as source_summary
from essay_writer.sources.access_schema import SourceLocator, SourceTextPacket, locator_from_payload
from essay_writer.sources.ingestion import FileTooLargeWithoutIndexError
from essay_writer.sources.schema import SourceIngestionConfig, SourceMaterializationResult
from essay_writer.task_spec.parser import stable_task_id, task_spec_from_payload
from essay_writer.task_spec.prompts import (
    TASK_SPEC_SCHEMA,
    TASK_SPEC_SYSTEM_PROMPT,
    build_task_spec_user_message,
)
from essay_writer.task_spec.schema import AdversarialFlag
from essay_writer.task_spec.security import scan_adversarial_text
from essay_writer.topic_ideation.prompts import TOPIC_IDEATION_SCHEMA, TOPIC_IDEATION_SYSTEM_PROMPT
from essay_writer.validation.checks import run_deterministic_checks as run_validation_deterministic_checks
from essay_writer.validation.citations import check_bibliography_against_source_cards
from essay_writer.validation.prompts import VALIDATION_SCHEMA, VALIDATION_SYSTEM_PROMPT
from essay_writer.validation.schema import (
    AssignmentFit,
    CitationMetadataWarning,
    DeterministicCheckResult,
    LLMJudgmentResult,
    LengthCheck,
    ParagraphLengthProfile,
    SentenceRun,
    ValidationReport,
    VocabHit,
)


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
    "prepare_research_notes",
    "commit_research_notes",
    "prepare_outline",
    "commit_outline",
    "prepare_draft",
    "commit_draft",
    "prepare_revision",
    "commit_revision",
    "run_deterministic_checks",
    "prepare_validation",
    "commit_validation",
    "save_user_edit",
    "export_markdown",
    "list_drafts",
    "get_draft",
    "get_job_summary",
    "list_sources",
    "get_source_card",
    "list_work_packets",
    "get_work_packet",
    "list_work_results",
    "get_work_result",
    "search_source",
    "read_source_packet",
    "resolve_source_requests",
    "get_source_packet_bundle",
]
PLANNED_WORKFLOW_TOOLS = [
    *CURRENTLY_CALLABLE_TOOLS,
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
                    "currently_callable_tools is the implemented tool surface in this build."
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
                "artifact_refs": _recovered_artifact_refs(recovery),
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

    def create_job_from_artifacts(
        self,
        task_spec_id: str,
        source_ids: list[str],
        *,
        job_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        run = None
        if agent_run_id is not None:
            try:
                run = self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("create_job_from_artifacts", agent_run_id, exc)

        try:
            task_spec = self.stores.task_store.load_latest(task_spec_id)
        except KeyError as exc:
            return _error_result_with_next(
                "create_job_from_artifacts",
                code="task_spec_not_found",
                message=f"TaskSpecification not found: {task_spec_id}",
                exc=exc,
                next_suggested_tools=["prepare_task_spec"],
            )

        effective_source_ids = [str(source_id) for source_id in source_ids]
        if not effective_source_ids:
            return _error_result_with_next(
                "create_job_from_artifacts",
                code="source_ids_required",
                message="create_job_from_artifacts requires at least one source_id with committed text and card artifacts",
                exc=ValueError("source_ids"),
                next_suggested_tools=["ingest_source_file", "prepare_source_card"],
            )
        for source_id in effective_source_ids:
            if not self.stores.source_store.has_text_artifacts(source_id):
                return _error_result_with_next(
                    "create_job_from_artifacts",
                    code="source_text_artifacts_missing",
                    message=f"source text artifacts are missing for source: {source_id}",
                    exc=FileNotFoundError(source_id),
                    next_suggested_tools=["ingest_source_file"],
                )
            if not self.stores.source_store.has_source_card(source_id):
                return _error_result_with_next(
                    "create_job_from_artifacts",
                    code="source_card_missing",
                    message=f"source card is missing for source: {source_id}",
                    exc=FileNotFoundError(source_id),
                    next_suggested_tools=["prepare_source_card"],
                )

        already_existing = False
        if job_id is not None:
            try:
                existing = self.stores.workflow.load_job(job_id)
            except KeyError:
                existing = None
            if existing is not None:
                if (
                    existing.task_spec_id == task_spec.id
                    and existing.source_ids == effective_source_ids
                ):
                    job = existing
                    already_existing = True
                else:
                    return _error_result(
                        "create_job_from_artifacts",
                        code="job_id_conflict",
                        message=(
                            f"job_id {job_id} already exists with different task/source artifacts"
                        ),
                        exc=ValueError(job_id),
                    )
            else:
                job = self.stores.workflow.create_job(
                    task_spec_id=task_spec.id,
                    source_ids=effective_source_ids,
                    job_id=job_id,
                )
        else:
            job = self.stores.workflow.create_job(
                task_spec_id=task_spec.id,
                source_ids=effective_source_ids,
            )

        next_tools = ["prepare_topics"]
        artifact_refs = {
            "job_id": job.id,
            "task_spec_id": task_spec.id,
            "source_ids": list(effective_source_ids),
        }
        if agent_run_id is not None and run is not None:
            self.run_store.update_run(
                replace(
                    run,
                    job_id=job.id,
                    current_phase=job.current_stage,
                )
            )
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase=job.current_stage,
                decision="job_created" if not already_existing else "job_recovered",
                next_suggested_tools=next_tools,
            )

        return ToolResult(
            ok=True,
            tool_name="create_job_from_artifacts",
            data={
                "job_id": job.id,
                "status": job.status,
                "current_stage": job.current_stage,
                "task_spec_id": job.task_spec_id,
                "source_ids": list(job.source_ids),
                "already_existing": already_existing,
                "artifact_refs": artifact_refs,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def get_job_summary(self, job_id: str) -> ToolResult:
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "get_job_summary",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        next_tools = _job_next_tools(job.status, job.current_stage)
        return ToolResult(
            ok=True,
            tool_name="get_job_summary",
            data={
                "job": _job_summary(job),
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def list_sources(self) -> ToolResult:
        sources = []
        for source_dir in sorted(self.stores.source_store.root.iterdir(), key=lambda path: path.name):
            if not source_dir.is_dir():
                continue
            source_id = source_dir.name
            try:
                source = self.stores.source_store.load_source(source_id)
            except (KeyError, FileNotFoundError):
                continue
            sources.append(_source_summary(self.stores.source_store, source))
        return ToolResult(
            ok=True,
            tool_name="list_sources",
            data={"sources": sources},
        )

    def get_source_card(self, source_id: str) -> ToolResult:
        try:
            card = self.stores.source_store.load_source_card(source_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "get_source_card",
                code="source_card_not_found",
                message=f"SourceCard not found: {source_id}",
                exc=exc,
                next_suggested_tools=["prepare_source_card"],
            )
        return ToolResult(
            ok=True,
            tool_name="get_source_card",
            data={"source_card": asdict(card)},
        )

    def list_work_packets(
        self,
        *,
        scope: str | None = None,
        status: str | None = None,
    ) -> ToolResult:
        packets = self.work_store.list_packets(scope=scope, status=status)
        return ToolResult(
            ok=True,
            tool_name="list_work_packets",
            data={"work_packets": [_work_packet_summary(packet) for packet in packets]},
        )

    def get_work_packet(self, work_packet_id: str) -> ToolResult:
        try:
            packet = self.work_store.load_packet(work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "get_work_packet",
                code="work_packet_not_found",
                message=f"WorkPacket not found: {work_packet_id}",
                exc=exc,
            )
        return ToolResult(
            ok=True,
            tool_name="get_work_packet",
            data={"work_packet": asdict(packet)},
        )

    def list_work_results(
        self,
        *,
        scope: str | None = None,
        status: str | None = None,
    ) -> ToolResult:
        results = self.work_store.list_results(scope=scope, status=status)
        return ToolResult(
            ok=True,
            tool_name="list_work_results",
            data={"work_results": [_work_result_summary(result) for result in results]},
        )

    def get_work_result(self, work_result_id: str) -> ToolResult:
        try:
            result = self.work_store.load_result(work_result_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "get_work_result",
                code="work_result_not_found",
                message=f"WorkResult not found: {work_result_id}",
                exc=exc,
            )
        return ToolResult(
            ok=True,
            tool_name="get_work_result",
            data={"work_result": asdict(result)},
        )

    def search_source(self, source_id: str, query: str, limit: int = 5) -> ToolResult:
        try:
            locators = self.stores.source_access.search_source(
                source_id,
                query,
                limit=limit,
            )
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "search_source",
                code="source_not_found",
                message=f"Source not found: {source_id}",
                exc=exc,
                next_suggested_tools=["ingest_source_file"],
            )
        except ValueError as exc:
            return _error_result(
                "search_source",
                code="invalid_search_request",
                message=str(exc),
                exc=exc,
            )
        return ToolResult(
            ok=True,
            tool_name="search_source",
            data={
                "source_id": source_id,
                "query": query,
                "locators": [source_locator_to_payload(locator) for locator in locators],
            },
            next_suggested_tools=["read_source_packet", "resolve_source_requests"],
        )

    def read_source_packet(
        self,
        locator_payload: dict[str, object],
        max_chars: int | None = None,
    ) -> ToolResult:
        max_chars_error = _validate_max_chars(max_chars, tool_name="read_source_packet")
        if max_chars_error is not None:
            return max_chars_error
        locator_result = _locator_from_payload_result(
            locator_payload,
            tool_name="read_source_packet",
            next_suggested_tools=["search_source", "create_research_plan"],
        )
        if isinstance(locator_result, ToolResult):
            return locator_result
        try:
            packets = self.stores.source_access.resolve_locators([locator_result])
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "read_source_packet",
                code="source_packet_not_found",
                message=f"Could not resolve source locator for source: {locator_result.source_id}",
                exc=exc,
                next_suggested_tools=["search_source"],
            )
        packet = packets[0] if packets else None
        if packet is None:
            return _error_result_with_next(
                "read_source_packet",
                code="source_packet_not_found",
                message="Source locator did not resolve to a packet.",
                exc=KeyError(locator_result.source_id),
                next_suggested_tools=["search_source"],
            )
        if max_chars is not None:
            packet = _trim_source_packet(packet, max_chars=max_chars)
        return ToolResult(
            ok=True,
            tool_name="read_source_packet",
            data={"source_packet": source_packet_to_payload(packet)},
            next_suggested_tools=["resolve_source_requests", "prepare_research_notes"],
        )

    def resolve_source_requests(
        self,
        job_id: str,
        locators: list[dict[str, object]] | None = None,
        research_plan_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        run = None
        if agent_run_id is not None:
            try:
                run = self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("resolve_source_requests", agent_run_id, exc)

        source_requests: list[SourceLocator] = []
        if locators:
            for payload in locators:
                locator_result = _locator_from_payload_result(
                    payload,
                    tool_name="resolve_source_requests",
                    next_suggested_tools=["search_source", "create_research_plan"],
                )
                if isinstance(locator_result, ToolResult):
                    return locator_result
                source_requests.append(locator_result)
        elif research_plan_id is not None:
            try:
                research_plan = _load_research_plan_for_job(
                    self.stores.research_plan_store,
                    job_id=job_id,
                    research_plan_id=research_plan_id,
                )
            except (KeyError, ValueError) as exc:
                return _error_result_with_next(
                    "resolve_source_requests",
                    code="research_plan_not_found",
                    message=f"ResearchPlan not found for job {job_id}: {research_plan_id}",
                    exc=exc,
                    next_suggested_tools=["create_research_plan"],
                )
            source_requests = list(research_plan.source_requests)

        if not source_requests:
            return _error_result_with_next(
                "resolve_source_requests",
                code="source_requests_required",
                message=(
                    "resolve_source_requests requires explicit locators or a research_plan_id "
                    "with source_requests."
                ),
                exc=ValueError("source_requests"),
                next_suggested_tools=["search_source", "create_research_plan"],
            )

        try:
            packets = self.stores.source_access.resolve_locators(source_requests)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "resolve_source_requests",
                code="source_packet_resolution_failed",
                message="One or more source locators could not be resolved.",
                exc=exc,
                next_suggested_tools=["search_source"],
            )
        if not packets:
            return _error_result_with_next(
                "resolve_source_requests",
                code="source_packets_empty",
                message="Source requests did not resolve to any source text packets.",
                exc=LookupError("source packets"),
                next_suggested_tools=["search_source", "read_source_packet"],
            )
        packet_payloads = [source_packet_to_payload(packet) for packet in packets]
        warnings = _aggregate_packet_warnings(packets)
        bundle_id = timestamp_id(
            "srcbundle",
            "job",
            job_id,
            research_plan_id,
            short_hash({"locators": [source_locator_to_payload(item) for item in source_requests]}),
        )
        bundle = self.work_store.save_source_packet_bundle(
            SourcePacketBundle(
                source_packet_bundle_id=bundle_id,
                scope=f"job:{job_id}",
                packet_payloads=packet_payloads,
                warnings=warnings,
            )
        )
        next_tools = ["prepare_research_notes"]
        artifact_refs = {
            "job_id": job_id,
            "source_packet_bundle_id": bundle.source_packet_bundle_id,
        }
        if research_plan_id is not None:
            artifact_refs["research_plan_id"] = research_plan_id
        recovery: dict[str, object] | None = None
        if agent_run_id is not None and run is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="research_notes",
                decision="source_requests_resolved",
                next_suggested_tools=next_tools,
            )
            recovery_result = self.recover_agent_run(agent_run_id=agent_run_id)
            if recovery_result.ok:
                recovery = dict(recovery_result.data)

        data: dict[str, object] = {
            "source_packet_bundle_id": bundle.source_packet_bundle_id,
            "scope": bundle.scope,
            "packet_count": len(bundle.packet_payloads),
            "packet_ids": [packet.packet_id for packet in packets],
            "warnings": list(bundle.warnings),
            "artifact_refs": artifact_refs,
            "next_suggested_tools": next_tools,
        }
        if recovery is not None:
            data["recovery"] = recovery
        return ToolResult(
            ok=True,
            tool_name="resolve_source_requests",
            data=data,
            warnings=list(bundle.warnings),
            next_suggested_tools=next_tools,
        )

    def get_source_packet_bundle(self, source_packet_bundle_id: str) -> ToolResult:
        try:
            bundle = self.work_store.load_source_packet_bundle(source_packet_bundle_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "get_source_packet_bundle",
                code="source_packet_bundle_not_found",
                message=f"SourcePacketBundle not found: {source_packet_bundle_id}",
                exc=exc,
                next_suggested_tools=["resolve_source_requests"],
            )
        return ToolResult(
            ok=True,
            tool_name="get_source_packet_bundle",
            data={"source_packet_bundle": asdict(bundle)},
            next_suggested_tools=["prepare_research_notes"],
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

    def prepare_source_card(
        self,
        source_id: str,
        *,
        agent_run_id: str | None = None,
        reuse_existing: bool = True,
    ) -> ToolResult:
        run = None
        if agent_run_id is not None:
            try:
                run = self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("prepare_source_card", agent_run_id, exc)
        if not self.stores.source_store.has_text_artifacts(source_id):
            return _error_result(
                "prepare_source_card",
                code="source_text_artifacts_missing",
                message=f"source text artifacts are missing for source: {source_id}",
                exc=FileNotFoundError(source_id),
            )
        if reuse_existing and self.stores.source_store.has_source_card(source_id):
            artifact_refs = {
                "source_id": source_id,
                "source_card_id": source_id,
            }
            if agent_run_id is not None and run is not None:
                self.run_store.attach_commit(
                    agent_run_id,
                    _merge_recovery_refs(artifact_refs, run.committed_artifact_refs),
                    next_suggested_tools=["prepare_task_spec"],
                )
            return ToolResult(
                ok=True,
                tool_name="prepare_source_card",
                data={
                    "source_id": source_id,
                    "source_card_status": "committed",
                    "artifact_refs": artifact_refs,
                    "next_suggested_tools": ["prepare_task_spec"],
                },
                next_suggested_tools=["prepare_task_spec"],
            )

        source = self.stores.source_store.load_source(source_id)
        chunks = self.stores.source_store.load_chunks(source_id)
        config = self.source_materializer._config
        excerpts = source_summary.select_source_card_excerpts(
            chunks,
            char_budget=config.source_card_input_char_budget,
        )
        user_message = source_summary.build_source_card_user_message(
            source,
            excerpts,
            config.source_card_summary_char_limit,
        )
        packet_id = timestamp_id(
            "workpkt",
            "source",
            source_id,
            "source_card",
            short_hash(user_message),
        )
        artifact_refs = {
            "source_id": source_id,
            "source": f"essay://sources/{source_id}",
        }
        delegation = _source_card_delegation(
            source_id=source_id,
            selected_excerpt_chars=sum(chunk.char_count for chunk in excerpts),
            pending_source_card_packets=_pending_source_card_packet_count(
                self.work_store,
                self.run_store.load_run(agent_run_id) if agent_run_id is not None else None,
            ),
        )
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="source_card",
                scope=f"source:{source_id}",
                instructions=(
                    "Create a source-card JSON object using only the provided uploaded-source "
                    "excerpts. Return JSON matching response_schema."
                ),
                system_prompt=source_summary.SOURCE_CARD_SYSTEM_PROMPT,
                prompt_blocks=[PromptBlock(text=user_message, cacheable=False)],
                response_schema=dict(source_summary.SOURCE_CARD_SCHEMA),
                context={
                    "source_id": source_id,
                    "summary_char_limit": config.source_card_summary_char_limit,
                    "selected_excerpt_chars": sum(chunk.char_count for chunk in excerpts),
                    "selected_chunk_ids": [chunk.id for chunk in excerpts],
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_source_card",
                delegation=delegation,
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="source_cards",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_source_card",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "source_id": source_id,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt": user_message,
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "source_card_status": "pending",
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def submit_work_result(
        self,
        work_packet_id: str,
        *,
        payload: dict[str, object],
        producer: WorkProducer,
        agent_run_id: str | None = None,
        warnings: list[str] | None = None,
    ) -> ToolResult:
        if not isinstance(payload, dict):
            return _error_result(
                "submit_work_result",
                code="work_result_payload_not_object",
                message="work result payload must be a JSON object",
                exc=TypeError(type(payload).__name__),
            )
        try:
            packet = self.work_store.load_packet(work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "submit_work_result",
                code="work_packet_not_found",
                message=f"WorkPacket not found: {work_packet_id}",
                exc=exc,
            )
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("submit_work_result", agent_run_id, exc)
        validation_error = _validate_work_payload(
            payload,
            packet.response_schema,
            tool_name="submit_work_result",
        )
        if validation_error is not None:
            return validation_error

        existing_ids = {result.work_result_id for result in self.work_store.list_results()}
        result = self.work_store.submit_result(
            packet.work_packet_id,
            payload=payload,
            producer=producer,
            warnings=warnings,
        )
        duplicate = result.work_result_id in existing_ids
        next_tools = [packet.commit_tool] if packet.commit_tool else []
        if agent_run_id is not None:
            self.run_store.attach_work_result(
                agent_run_id,
                result.work_result_id,
                work_packet_id=packet.work_packet_id,
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="submit_work_result",
            data={
                "work_result_id": result.work_result_id,
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "commit_tool": packet.commit_tool,
                "duplicate": duplicate,
                "already_existing": duplicate,
                "next_suggested_tools": next_tools,
            },
            warnings=list(result.warnings),
            next_suggested_tools=next_tools,
        )

    def commit_source_card(
        self,
        *,
        work_result_id: str | None = None,
        source_id: str | None = None,
        payload: dict[str, object] | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("commit_source_card", agent_run_id, exc)
        if work_result_id is None:
            direct = self._direct_source_card_work_result(source_id=source_id, payload=payload)
            if not direct.ok:
                return direct
            work_result_id = str(direct.data["work_result_id"])

        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_source_card",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.stage != "source_card":
            return _error_result(
                "commit_source_card",
                code="wrong_work_packet_stage",
                message=f"expected source_card packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )
        packet_source_id = packet.artifact_refs.get("source_id")
        if not isinstance(packet_source_id, str) or not packet_source_id:
            return _error_result(
                "commit_source_card",
                code="source_id_missing",
                message="source-card packet is missing artifact_refs.source_id",
                exc=ValueError("source_id"),
            )
        if source_id is not None and source_id != packet_source_id:
            return _error_result(
                "commit_source_card",
                code="source_id_mismatch",
                message=f"source_id {source_id} does not match packet source_id {packet_source_id}",
                exc=ValueError(source_id),
            )

        scope = f"source:{packet_source_id}"
        artifact_refs = {
            "source_id": packet_source_id,
            "source_card_id": packet_source_id,
        }
        already_committed = any(
            commit.work_result_id == result.work_result_id
            for commit in self.work_store.list_commits(scope=scope, stage="source_card")
        )
        if not already_committed:
            source = self.stores.source_store.load_source(packet_source_id)
            summary_limit = int(packet.context.get("summary_char_limit", 1200))
            card = source_summary.source_card_from_payload(source, result.payload, summary_limit)
            self.stores.source_store.save_source_card(packet_source_id, card)
        commit = self.work_store.save_commit(
            scope=scope,
            stage="source_card",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs=artifact_refs,
        )
        if agent_run_id is not None:
            run = self.run_store.load_run(agent_run_id)
            self.run_store.attach_commit(
                agent_run_id,
                _merge_recovery_refs(artifact_refs, run.committed_artifact_refs),
                next_suggested_tools=["prepare_task_spec"],
            )
        return ToolResult(
            ok=True,
            tool_name="commit_source_card",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "source_id": packet_source_id,
                "source_card_id": packet_source_id,
                "source_card_status": "committed",
                "artifact_refs": dict(commit.artifact_refs),
                "already_committed": already_committed,
                "next_suggested_tools": ["prepare_task_spec"],
            },
            next_suggested_tools=["prepare_task_spec"],
        )

    def prepare_task_spec(
        self,
        raw_text: str,
        *,
        task_id: str | None = None,
        source_document_ids: list[str] | None = None,
        selected_prompt: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("prepare_task_spec", agent_run_id, exc)

        effective_task_id = task_id or stable_task_id(raw_text)
        sources = list(source_document_ids or [])
        deterministic_flags = scan_adversarial_text(raw_text)
        user_message = build_task_spec_user_message(raw_text)
        packet_id = timestamp_id(
            "workpkt",
            "task",
            effective_task_id,
            "task_spec",
            short_hash(user_message),
        )
        artifact_refs: dict[str, object] = {
            "task_spec_id": effective_task_id,
            "source_document_ids": sources,
        }
        if selected_prompt is not None:
            artifact_refs["selected_prompt"] = selected_prompt
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="task_spec",
                scope=f"task:{effective_task_id}",
                instructions=(
                    "Extract a task-specification JSON object from the untrusted assignment text. "
                    "Return JSON matching response_schema; do not commit it."
                ),
                system_prompt=TASK_SPEC_SYSTEM_PROMPT,
                prompt_blocks=[PromptBlock(text=user_message, cacheable=False)],
                response_schema=dict(TASK_SPEC_SCHEMA),
                context={
                    "raw_text": raw_text,
                    "task_id": effective_task_id,
                    "requested_task_id": task_id,
                    "version": 1,
                    "source_document_ids": sources,
                    "selected_prompt": selected_prompt,
                    "deterministic_flags": [asdict(flag) for flag in deterministic_flags],
                    "parser_version": "task-spec-v1",
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_task_spec",
                delegation=DelegationHint(
                    recommended=False,
                    reason=(
                        "assignment interpretation is globally important and usually small "
                        "enough for the orchestrator"
                    ),
                    allowed_tools=["submit_work_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not commit it; "
                        "the orchestrator will submit and commit the result."
                    ),
                ),
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="task_specification",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_task_spec",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "task_spec_id": effective_task_id,
                "version": 1,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt": user_message,
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_task_spec(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("commit_task_spec", agent_run_id, exc)
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_task_spec",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.stage != "task_spec":
            return _error_result(
                "commit_task_spec",
                code="wrong_work_packet_stage",
                message=f"expected task_spec packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )

        try:
            deterministic_flags = _adversarial_flags_from_context(packet.context)
            raw_text = str(packet.context.get("raw_text", ""))
            task_id = _optional_context_str(packet.context.get("task_id"))
            version = int(packet.context.get("version", 1))
            source_document_ids = _string_list(packet.context.get("source_document_ids"))
            selected_prompt = _optional_context_str(packet.context.get("selected_prompt"))
            parser_version = str(packet.context.get("parser_version", "task-spec-v1"))
        except (TypeError, ValueError) as exc:
            return _error_result(
                "commit_task_spec",
                code="task_spec_context_invalid",
                message=f"task-spec packet context is invalid: {exc}",
                exc=exc,
            )
        task_spec = task_spec_from_payload(
            result.payload,
            raw_text=raw_text,
            task_id=task_id,
            version=version,
            source_document_ids=source_document_ids,
            selected_prompt=selected_prompt,
            deterministic_flags=deterministic_flags,
            parser_version=parser_version,
        )

        existing_commits = self.work_store.list_commits(scope=packet.scope, stage="task_spec")
        existing_commit = next(
            (
                commit
                for commit in existing_commits
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None
        if already_committed:
            commit = existing_commit
            try:
                task_spec = self.stores.task_store.load(task_spec.id, task_spec.version)
            except KeyError:
                self.stores.task_store.save(task_spec)
        else:
            try:
                existing_task_spec = self.stores.task_store.load(task_spec.id, task_spec.version)
            except KeyError:
                self.stores.task_store.save(task_spec)
            else:
                if _task_spec_stable_payload(existing_task_spec) != _task_spec_stable_payload(task_spec):
                    return _error_result(
                        "commit_task_spec",
                        code="task_spec_version_conflict",
                        message=(
                            f"task spec {task_spec.id} v{task_spec.version} already exists "
                            "with different content"
                        ),
                        exc=ValueError(f"{task_spec.id} v{task_spec.version}"),
                    )
                task_spec = existing_task_spec
            artifact_refs = _task_spec_artifact_refs(task_spec)
            commit = self.work_store.save_commit(
                scope=packet.scope,
                stage="task_spec",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )
        artifact_refs = dict(commit.artifact_refs)

        blocking = list(task_spec.blocking_questions)
        next_tools = [] if blocking else ["create_job_from_artifacts"]
        if agent_run_id is not None:
            self.run_store.attach_work_result(
                agent_run_id,
                result.work_result_id,
                work_packet_id=packet.work_packet_id,
                next_suggested_tools=next_tools,
            )
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="task_specification" if blocking else "job_creation",
                decision="task_spec_committed",
                blocked_on="task_specification" if blocking else None,
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_task_spec",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "task_spec_id": task_spec.id,
                "version": task_spec.version,
                "blocking_questions": blocking,
                "risk_flags": list(task_spec.risk_flags),
                "adversarial_flags": [asdict(flag) for flag in task_spec.adversarial_flags],
                "source_document_ids": list(task_spec.source_document_ids),
                "artifact_refs": dict(commit.artifact_refs),
                "already_committed": already_committed,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def prepare_topics(
        self,
        job_id: str,
        *,
        user_instruction: str | None = None,
        max_candidates: int = 8,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        max_candidates_result = _validate_topic_max_candidates(
            max_candidates,
            tool_name="prepare_topics",
        )
        if isinstance(max_candidates_result, ToolResult):
            return max_candidates_result
        max_candidates = max_candidates_result

        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("prepare_topics", agent_run_id, exc)
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "prepare_topics",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        if job.task_spec_id is None:
            return _error_result_with_next(
                "prepare_topics",
                code="job_task_spec_missing",
                message=f"job {job_id} does not have a committed task_spec_id",
                exc=ValueError("task_spec_id"),
                next_suggested_tools=["prepare_task_spec"],
            )
        if not job.source_ids:
            return _error_result_with_next(
                "prepare_topics",
                code="job_sources_missing",
                message=f"job {job_id} does not have committed source_ids",
                exc=ValueError("source_ids"),
                next_suggested_tools=["ingest_source_file", "prepare_source_card"],
            )
        readiness_error = _topic_job_readiness_error(
            self.stores,
            job,
            tool_name="prepare_topics",
        )
        if readiness_error is not None:
            return readiness_error

        try:
            task_spec = self.stores.task_store.load_latest(job.task_spec_id)
            source_cards = [
                self.stores.source_store.load_source_card(source_id)
                for source_id in job.source_ids
            ]
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "prepare_topics",
                code="job_artifacts_not_ready",
                message=f"job {job_id} is missing task or source-card artifacts",
                exc=exc,
                next_suggested_tools=["prepare_task_spec", "prepare_source_card"],
            )

        index_manifests = []
        source_maps = []
        for source_id in job.source_ids:
            source_dir = self.stores.source_store.source_dir(source_id)
            if (source_dir / "index_manifest.json").exists():
                index_manifests.append(self.stores.source_store.load_index_manifest(source_id))
            if (source_dir / "source_map.json").exists():
                source_maps.append(self.stores.source_store.load_source_map(source_id))

        previous_candidates = self.stores.workflow.get_previous_candidates(job_id)
        rejected_topics = self.stores.workflow.get_rejected_topics(job_id)
        from essay_writer.topic_ideation.service import build_topic_ideation_user_blocks

        topic_prompt_blocks = build_topic_ideation_user_blocks(
            task_spec,
            source_cards=source_cards,
            index_manifests=index_manifests,
            source_maps=source_maps,
            previous_candidates=previous_candidates,
            rejected_topics=rejected_topics,
            user_instruction=user_instruction,
            max_candidates=max_candidates,
        )
        prompt_blocks = [
            PromptBlock(text=block.text, cacheable=block.cacheable)
            for block in topic_prompt_blocks
        ]
        packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "topic_ideation",
            short_hash([block.text for block in prompt_blocks]),
        )
        artifact_refs = {
            "job_id": job_id,
            "task_spec_id": job.task_spec_id,
            "source_ids": list(job.source_ids),
        }
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="topic_ideation",
                scope=f"job:{job_id}",
                instructions=(
                    "Generate topic-ideation candidates using only the supplied task "
                    "specification and uploaded-source artifacts. Return JSON matching "
                    "response_schema; do not commit it."
                ),
                system_prompt=TOPIC_IDEATION_SYSTEM_PROMPT,
                prompt_blocks=prompt_blocks,
                response_schema=dict(TOPIC_IDEATION_SCHEMA),
                context={
                    "job_id": job_id,
                    "task_spec_id": job.task_spec_id,
                    "user_instruction": user_instruction,
                    "max_candidates": max_candidates,
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_topics",
                delegation=DelegationHint(
                    recommended=False,
                    reason="topic selection is a global planning step",
                    allowed_tools=["submit_work_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not commit it; "
                        "the orchestrator will submit and commit the result."
                    ),
                ),
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="topic_ideation",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_topics",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "job_id": job_id,
                "task_spec_id": job.task_spec_id,
                "source_ids": list(job.source_ids),
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_topics(
        self,
        *,
        work_result_id: str | None = None,
        payload: dict[str, object] | None = None,
        job_id: str | None = None,
        user_instruction: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("commit_topics", agent_run_id, exc)
        if work_result_id is None:
            direct = self._direct_topic_work_result(
                job_id=job_id,
                payload=payload,
                user_instruction=user_instruction,
            )
            if not direct.ok:
                return direct
            work_result_id = str(direct.data["work_result_id"])

        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_topics",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.commit_tool != "commit_topics":
            return _error_result(
                "commit_topics",
                code="wrong_commit_tool",
                message=f"expected commit_topics packet, got {packet.commit_tool}",
                exc=ValueError(packet.commit_tool),
            )
        validation_error = _validate_work_payload(
            result.payload,
            TOPIC_IDEATION_SCHEMA,
            tool_name="commit_topics",
        )
        if validation_error is not None:
            return validation_error

        packet_job_id = packet.context.get("job_id") or packet.artifact_refs.get("job_id")
        if not isinstance(packet_job_id, str) or not packet_job_id:
            return _error_result(
                "commit_topics",
                code="job_id_missing",
                message="topic packet is missing job_id",
                exc=ValueError("job_id"),
            )
        if job_id is not None and job_id != packet_job_id:
            return _error_result(
                "commit_topics",
                code="job_id_mismatch",
                message=f"job_id {job_id} does not match packet job_id {packet_job_id}",
                exc=ValueError(job_id),
            )
        try:
            job = self.stores.workflow.load_job(packet_job_id)
        except KeyError as exc:
            return _error_result(
                "commit_topics",
                code="job_not_found",
                message=f"EssayJob not found: {packet_job_id}",
                exc=exc,
            )
        if job.task_spec_id is None:
            return _error_result_with_next(
                "commit_topics",
                code="job_task_spec_missing",
                message=f"job {packet_job_id} does not have a committed task_spec_id",
                exc=ValueError("task_spec_id"),
                next_suggested_tools=["prepare_task_spec"],
            )
        readiness_error = _topic_job_readiness_error(
            self.stores,
            job,
            tool_name="commit_topics",
        )
        if readiness_error is not None:
            return readiness_error
        max_candidates_result = _validate_topic_max_candidates(
            packet.context.get("max_candidates", 8),
            tool_name="commit_topics",
        )
        if isinstance(max_candidates_result, ToolResult):
            return max_candidates_result
        max_candidates = max_candidates_result
        from essay_writer.topic_ideation.service import topic_ideation_result_from_payload

        topic_result = topic_ideation_result_from_payload(
            task_spec_id=job.task_spec_id,
            payload=result.payload,
            max_candidates=max_candidates,
        )
        candidate_topic_ids = [candidate.id for candidate in topic_result.candidates]
        blocking = list(topic_result.blocking_questions)
        warnings = list(topic_result.warnings)
        scope = f"job:{packet_job_id}"
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="topic_ideation")
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None

        if blocking or not topic_result.candidates:
            next_tools = ["prepare_topics"]
            artifact_refs = {
                "job_id": packet_job_id,
                "task_spec_id": job.task_spec_id,
                "candidate_topic_ids": candidate_topic_ids,
                "blocking_questions": blocking,
            }
            commit = existing_commit or self.work_store.save_commit(
                scope=scope,
                stage="topic_ideation",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )
            if agent_run_id is not None:
                self.run_store.attach_work_result(
                    agent_run_id,
                    result.work_result_id,
                    work_packet_id=packet.work_packet_id,
                    next_suggested_tools=next_tools,
                )
                self.run_store.attach_commit(
                    agent_run_id,
                    dict(commit.artifact_refs),
                    next_suggested_tools=next_tools,
                )
                self.run_store.checkpoint(
                    agent_run_id,
                    current_phase="topic_ideation",
                    decision="topic_ideation_blocked",
                    blocked_on="topic_selection",
                    next_suggested_tools=next_tools,
                )
            return ToolResult(
                ok=True,
                tool_name="commit_topics",
                data={
                    "commit_id": commit.commit_id,
                    "work_result_id": result.work_result_id,
                    "job_id": packet_job_id,
                    "round_number": None,
                    "topic_round_id": None,
                    "candidate_topic_ids": candidate_topic_ids,
                    "blocking_questions": blocking,
                    "warnings": warnings,
                    "already_committed": already_committed,
                    "next_suggested_tools": next_tools,
                },
                warnings=warnings,
                next_suggested_tools=next_tools,
            )

        previous_candidates = self.stores.workflow.get_previous_candidates(packet_job_id)
        packet_user_instruction = _optional_context_str(packet.context.get("user_instruction"))
        effective_instruction = user_instruction if user_instruction is not None else packet_user_instruction
        matching_round = None
        if existing_commit is not None:
            round_id = existing_commit.artifact_refs.get("topic_round_id")
            round_number = existing_commit.artifact_refs.get("round_number")
            if isinstance(round_number, int):
                try:
                    matching_round = self.stores.topic_store.load_round(packet_job_id, round_number)
                except KeyError:
                    matching_round = None
            if matching_round is None and isinstance(round_id, str):
                matching_round = next(
                    (
                        round_
                        for round_ in self.stores.topic_store.list_rounds(packet_job_id)
                        if round_.id == round_id
                    ),
                    None,
                )
            if matching_round is None:
                return _error_result(
                    "commit_topics",
                    code="topic_round_commit_missing",
                    message="existing topic commit does not reference an available topic round",
                    exc=KeyError(existing_commit.commit_id),
                )
        if matching_round is None:
            try:
                matching_round = self.stores.workflow.record_topic_round(
                    job_id=packet_job_id,
                    topic_result=topic_result,
                    user_instruction=effective_instruction,
                    previous_candidates=previous_candidates,
                )
            except (TopicSelectionError, FileExistsError) as exc:
                return _error_result(
                    "commit_topics",
                    code="topic_round_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
        artifact_refs = {
            "job_id": packet_job_id,
            "task_spec_id": job.task_spec_id,
            "topic_round_id": matching_round.id,
            "round_number": matching_round.round_number,
            "candidate_topic_ids": candidate_topic_ids,
        }
        commit = existing_commit or self.work_store.save_commit(
            scope=scope,
            stage="topic_ideation",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs=artifact_refs,
        )
        next_tools = ["select_topic", "reject_topic"]
        if agent_run_id is not None:
            self.run_store.attach_work_result(
                agent_run_id,
                result.work_result_id,
                work_packet_id=packet.work_packet_id,
                next_suggested_tools=next_tools,
            )
            self.run_store.attach_commit(
                agent_run_id,
                dict(commit.artifact_refs),
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="topic_selection",
                decision="topic_round_committed",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_topics",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "job_id": packet_job_id,
                "round_number": matching_round.round_number,
                "topic_round_id": matching_round.id,
                "candidate_topic_ids": candidate_topic_ids,
                "blocking_questions": blocking,
                "warnings": warnings,
                "artifact_refs": dict(commit.artifact_refs),
                "already_committed": already_committed,
                "next_suggested_tools": next_tools,
            },
            warnings=warnings,
            next_suggested_tools=next_tools,
        )

    def select_topic(
        self,
        job_id: str,
        round_number: int,
        topic_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("select_topic", agent_run_id, exc)
        try:
            selected = self.stores.workflow.select_topic(
                job_id=job_id,
                round_number=round_number,
                topic_id=topic_id,
            )
        except (KeyError, FileExistsError, TopicSelectionError) as exc:
            return _error_result_with_next(
                "select_topic",
                code="topic_selection_failed",
                message=str(exc),
                exc=exc,
                next_suggested_tools=["select_topic", "reject_topic"],
            )
        artifact_refs = {
            "job_id": job_id,
            "topic_round_id": selected.round_id,
            "selected_topic_id": selected.topic_id,
        }
        next_tools = ["create_research_plan"]
        if agent_run_id is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="research_planning",
                decision="topic_selected",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="select_topic",
            data={
                "job_id": job_id,
                "round_number": round_number,
                "selected_topic_id": selected.topic_id,
                "selected_topic": asdict(selected),
                "artifact_refs": artifact_refs,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def reject_topic(
        self,
        job_id: str,
        round_number: int,
        topic_id: str,
        reason: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("reject_topic", agent_run_id, exc)
        try:
            rejected = self.stores.workflow.reject_topic(
                job_id=job_id,
                round_number=round_number,
                topic_id=topic_id,
                reason=reason,
            )
        except (KeyError, FileExistsError, TopicSelectionError) as exc:
            return _error_result_with_next(
                "reject_topic",
                code="topic_rejection_failed",
                message=str(exc),
                exc=exc,
                next_suggested_tools=["prepare_topics", "select_topic"],
            )
        rejected_topic_id = f"{rejected.round_id}:{rejected.topic_id}"
        artifact_refs = {
            "job_id": job_id,
            "topic_round_id": rejected.round_id,
            "rejected_topic_id": rejected_topic_id,
            "topic_id": rejected.topic_id,
        }
        next_tools = ["prepare_topics", "select_topic"]
        if agent_run_id is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="topic_selection",
                decision="topic_rejected",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="reject_topic",
            data={
                "job_id": job_id,
                "round_number": round_number,
                "rejected_topic_id": rejected_topic_id,
                "topic_id": rejected.topic_id,
                "rejected_topic": asdict(rejected),
                "artifact_refs": artifact_refs,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def create_research_plan(
        self,
        job_id: str,
        *,
        external_search_allowed: bool = False,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("create_research_plan", agent_run_id, exc)
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "create_research_plan",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        if job.task_spec_id is None:
            return _error_result_with_next(
                "create_research_plan",
                code="job_task_spec_missing",
                message=f"job {job_id} does not have a committed task_spec_id",
                exc=ValueError("task_spec_id"),
                next_suggested_tools=["prepare_task_spec"],
            )
        if job.selected_topic_id is None:
            return _error_result_with_next(
                "create_research_plan",
                code="selected_topic_missing",
                message=f"job {job_id} does not have a selected topic",
                exc=ValueError("selected_topic_id"),
                next_suggested_tools=["select_topic"],
            )
        try:
            task_spec = self.stores.task_store.load_latest(job.task_spec_id)
            selected_topic = self.stores.topic_store.load_selected_topic(job_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "create_research_plan",
                code="research_planning_artifacts_missing",
                message=f"job {job_id} is missing task-spec or selected-topic artifacts",
                exc=exc,
                next_suggested_tools=["prepare_task_spec", "select_topic"],
            )

        existing_plan = None
        try:
            latest_plan = self.stores.research_plan_store.load_latest(job_id)
            if (
                latest_plan.selected_topic_id == selected_topic.topic_id
                and latest_plan.external_search_allowed == external_search_allowed
            ):
                existing_plan = latest_plan
        except KeyError:
            existing_plan = None

        if existing_plan is None:
            index_manifests = []
            source_maps = []
            for source_id in job.source_ids:
                source_dir = self.stores.source_store.source_dir(source_id)
                if (source_dir / "index_manifest.json").exists():
                    index_manifests.append(self.stores.source_store.load_index_manifest(source_id))
                if (source_dir / "source_map.json").exists():
                    source_maps.append(self.stores.source_store.load_source_map(source_id))
            version = self.stores.research_plan_store.next_version(job_id)
            plan = ResearchPlanningService().create_plan(
                job=job,
                task_spec=task_spec,
                selected_topic=selected_topic,
                index_manifests=index_manifests,
                source_maps=source_maps,
                source_access_config=self.stores.source_access.config,
                version=version,
                external_search_allowed=external_search_allowed,
            )
            try:
                self.stores.research_plan_store.save(plan)
            except FileExistsError as exc:
                return _error_result(
                    "create_research_plan",
                    code="research_plan_save_failed",
                    message=str(exc),
                    exc=exc,
                )
            already_existing = False
        else:
            plan = existing_plan
            already_existing = True

        updated_job = self.stores.workflow.load_job(job_id)
        if updated_job.research_plan_id != plan.id:
            try:
                self.stores.workflow.record_research_plan_complete(
                    job_id=job_id,
                    research_plan=plan,
                )
            except TopicSelectionError as exc:
                return _error_result(
                    "create_research_plan",
                    code="research_plan_record_failed",
                    message=str(exc),
                    exc=exc,
                )

        next_tools = ["resolve_source_requests"]
        artifact_refs = {
            "job_id": job_id,
            "research_plan_id": plan.id,
            "selected_topic_id": selected_topic.topic_id,
        }
        if agent_run_id is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="source_resolution",
                decision="research_plan_created" if not already_existing else "research_plan_recovered",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="create_research_plan",
            data={
                "research_plan_id": plan.id,
                "job_id": job_id,
                "selected_topic_id": selected_topic.topic_id,
                "source_requests": [
                    source_locator_to_payload(locator)
                    for locator in plan.source_requests
                ],
                "uploaded_source_priorities": [
                    asdict(priority)
                    for priority in plan.uploaded_source_priorities
                ],
                "warnings": list(plan.warnings),
                "artifact_refs": artifact_refs,
                "already_existing": already_existing,
                "next_suggested_tools": next_tools,
            },
            warnings=list(plan.warnings),
            next_suggested_tools=next_tools,
        )

    def prepare_research_notes(
        self,
        job_id: str,
        source_packet_bundle_id: str,
        *,
        max_notes: int = 80,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        max_notes_result = _validate_research_max_notes(
            max_notes,
            tool_name="prepare_research_notes",
        )
        if isinstance(max_notes_result, ToolResult):
            return max_notes_result
        max_notes = max_notes_result
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("prepare_research_notes", agent_run_id, exc)
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "prepare_research_notes",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        if job.task_spec_id is None:
            return _error_result_with_next(
                "prepare_research_notes",
                code="job_task_spec_missing",
                message=f"job {job_id} does not have a committed task_spec_id",
                exc=ValueError("task_spec_id"),
                next_suggested_tools=["prepare_task_spec"],
            )
        if job.selected_topic_id is None:
            return _error_result_with_next(
                "prepare_research_notes",
                code="selected_topic_missing",
                message=f"job {job_id} does not have a selected topic",
                exc=ValueError("selected_topic_id"),
                next_suggested_tools=["select_topic"],
            )
        try:
            task_spec = self.stores.task_store.load_latest(job.task_spec_id)
            selected_topic = self.stores.topic_store.load_selected_topic(job_id)
            bundle = self.work_store.load_source_packet_bundle(source_packet_bundle_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "prepare_research_notes",
                code="research_artifacts_missing",
                message=f"job {job_id} is missing task, topic, or source packet bundle artifacts",
                exc=exc,
                next_suggested_tools=["create_research_plan", "resolve_source_requests"],
            )
        if bundle.scope != f"job:{job_id}":
            return _error_result(
                "prepare_research_notes",
                code="source_packet_bundle_job_mismatch",
                message=f"source packet bundle {source_packet_bundle_id} does not belong to job {job_id}",
                exc=ValueError(source_packet_bundle_id),
            )
        packets_result = _source_text_packets_from_bundle(
            bundle,
            tool_name="prepare_research_notes",
        )
        if isinstance(packets_result, ToolResult):
            return packets_result
        from essay_writer.research.service import (
            build_final_topic_research_user_message,
            topic_evidence_chunks_from_packets,
        )

        chunks = topic_evidence_chunks_from_packets(packets_result)
        if not chunks:
            return _error_result_with_next(
                "prepare_research_notes",
                code="source_packet_bundle_empty",
                message=f"source packet bundle {source_packet_bundle_id} has no readable text packets",
                exc=ValueError(source_packet_bundle_id),
                next_suggested_tools=["resolve_source_requests", "read_source_packet"],
            )
        user_message = build_final_topic_research_user_message(
            job,
            task_spec,
            selected_topic,
            chunks,
            max_notes,
        )
        total_packet_chars = sum(len(packet.text) for packet in packets_result)
        delegation = _research_notes_delegation(total_packet_chars=total_packet_chars)
        packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "research_notes",
            short_hash([source_packet_bundle_id, user_message]),
        )
        artifact_refs = {
            "job_id": job_id,
            "task_spec_id": job.task_spec_id,
            "selected_topic_id": selected_topic.topic_id,
            "source_packet_bundle_id": source_packet_bundle_id,
        }
        if job.research_plan_id is not None:
            artifact_refs["research_plan_id"] = job.research_plan_id
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="research_notes",
                scope=f"job:{job_id}",
                instructions=(
                    "Extract source-grounded research notes from the supplied packet bundle. "
                    "Return JSON matching response_schema; do not commit it."
                ),
                system_prompt=FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT,
                prompt_blocks=[PromptBlock(text=user_message, cacheable=True)],
                response_schema=dict(FINAL_TOPIC_RESEARCH_SCHEMA),
                context={
                    "job_id": job_id,
                    "task_spec_id": job.task_spec_id,
                    "selected_topic_id": selected_topic.topic_id,
                    "source_packet_bundle_id": source_packet_bundle_id,
                    "research_plan_id": job.research_plan_id,
                    "max_notes": max_notes,
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_research_notes",
                delegation=delegation,
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="research_notes",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_research_notes",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "job_id": job_id,
                "source_packet_bundle_id": source_packet_bundle_id,
                "packet_count": len(packets_result),
                "total_packet_chars": total_packet_chars,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_research_notes(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("commit_research_notes", agent_run_id, exc)
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_research_notes",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.commit_tool != "commit_research_notes":
            return _error_result(
                "commit_research_notes",
                code="wrong_commit_tool",
                message=f"expected commit_research_notes packet, got {packet.commit_tool}",
                exc=ValueError(packet.commit_tool),
            )
        validation_error = _validate_work_payload(
            result.payload,
            FINAL_TOPIC_RESEARCH_SCHEMA,
            tool_name="commit_research_notes",
        )
        if validation_error is not None:
            return validation_error

        packet_job_id = packet.context.get("job_id") or packet.artifact_refs.get("job_id")
        if not isinstance(packet_job_id, str) or not packet_job_id:
            return _error_result(
                "commit_research_notes",
                code="job_id_missing",
                message="research packet is missing job_id",
                exc=ValueError("job_id"),
            )
        try:
            job = self.stores.workflow.load_job(packet_job_id)
            selected_topic = self.stores.topic_store.load_selected_topic(packet_job_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "commit_research_notes",
                code="research_artifacts_missing",
                message=f"job {packet_job_id} is missing job or selected-topic artifacts",
                exc=exc,
                next_suggested_tools=["select_topic"],
            )
        source_packet_bundle_id = packet.context.get("source_packet_bundle_id")
        if not isinstance(source_packet_bundle_id, str) or not source_packet_bundle_id:
            return _error_result(
                "commit_research_notes",
                code="source_packet_bundle_id_missing",
                message="research packet is missing source_packet_bundle_id",
                exc=ValueError("source_packet_bundle_id"),
            )
        try:
            bundle = self.work_store.load_source_packet_bundle(source_packet_bundle_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "commit_research_notes",
                code="source_packet_bundle_not_found",
                message=f"SourcePacketBundle not found: {source_packet_bundle_id}",
                exc=exc,
                next_suggested_tools=["resolve_source_requests"],
            )
        if bundle.scope != f"job:{packet_job_id}":
            return _error_result(
                "commit_research_notes",
                code="source_packet_bundle_job_mismatch",
                message=(
                    f"source packet bundle {source_packet_bundle_id} "
                    f"does not belong to job {packet_job_id}"
                ),
                exc=ValueError(source_packet_bundle_id),
            )
        packets_result = _source_text_packets_from_bundle(
            bundle,
            tool_name="commit_research_notes",
        )
        if isinstance(packets_result, ToolResult):
            return packets_result
        max_notes_result = _validate_research_max_notes(
            packet.context.get("max_notes", 80),
            tool_name="commit_research_notes",
        )
        if isinstance(max_notes_result, ToolResult):
            return max_notes_result
        max_notes = max_notes_result

        scope = f"job:{packet_job_id}"
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="research_notes")
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None
        if existing_commit is not None:
            evidence_map_id = existing_commit.artifact_refs.get("evidence_map_id")
            research_version = existing_commit.artifact_refs.get("research_version")
            if isinstance(research_version, int):
                try:
                    research_result = self.stores.research_store.load(packet_job_id, research_version)
                except KeyError as exc:
                    return _error_result(
                        "commit_research_notes",
                        code="research_commit_artifact_missing",
                        message=f"Committed research artifact is missing: {evidence_map_id}",
                        exc=exc,
                    )
            else:
                return _error_result(
                    "commit_research_notes",
                    code="research_commit_artifact_missing",
                    message="Committed research artifact is missing research_version",
                    exc=KeyError(existing_commit.commit_id),
                )
            commit = existing_commit
        else:
            from essay_writer.research.service import (
                final_topic_research_result_from_payload,
                topic_evidence_chunks_from_packets,
            )

            chunks = topic_evidence_chunks_from_packets(packets_result)
            if not chunks:
                return _error_result_with_next(
                    "commit_research_notes",
                    code="source_packet_bundle_empty",
                    message=f"source packet bundle {source_packet_bundle_id} has no readable text packets",
                    exc=ValueError(source_packet_bundle_id),
                    next_suggested_tools=["resolve_source_requests", "read_source_packet"],
                )
            research_version = self.stores.research_store.next_version(packet_job_id)
            research_result = final_topic_research_result_from_payload(
                job=job,
                selected_topic=selected_topic,
                chunks=chunks,
                payload=result.payload,
                evidence_map_version=research_version,
                max_notes=max_notes,
            )
            try:
                self.stores.research_store.save_result(
                    research_result,
                    version=research_version,
                )
                self.stores.workflow.record_research_complete(
                    job_id=packet_job_id,
                    research_result=research_result,
                )
            except (FileExistsError, TopicSelectionError) as exc:
                return _error_result(
                    "commit_research_notes",
                    code="research_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
            artifact_refs = {
                "job_id": packet_job_id,
                "selected_topic_id": selected_topic.topic_id,
                "source_packet_bundle_id": source_packet_bundle_id,
                "evidence_map_id": research_result.evidence_map.id,
                "research_version": research_version,
            }
            if job.research_plan_id is not None:
                artifact_refs["research_plan_id"] = job.research_plan_id
            commit = self.work_store.save_commit(
                scope=scope,
                stage="research_notes",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )

        next_tools = ["prepare_outline"]
        if agent_run_id is not None:
            self.run_store.attach_work_result(
                agent_run_id,
                result.work_result_id,
                work_packet_id=packet.work_packet_id,
                next_suggested_tools=next_tools,
            )
            self.run_store.attach_commit(
                agent_run_id,
                dict(commit.artifact_refs),
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="outlining",
                decision="research_notes_committed",
                next_suggested_tools=next_tools,
            )
        warnings = list(research_result.report.warnings)
        return ToolResult(
            ok=True,
            tool_name="commit_research_notes",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "job_id": packet_job_id,
                "evidence_map_id": research_result.evidence_map.id,
                "research_report": asdict(research_result.report),
                "artifact_refs": dict(commit.artifact_refs),
                "already_committed": already_committed,
                "next_suggested_tools": next_tools,
            },
            warnings=warnings,
            next_suggested_tools=next_tools,
        )

    def prepare_outline(
        self,
        job_id: str,
        source_packet_bundle_id: str | None = None,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("prepare_outline", agent_run_id, exc)
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "prepare_outline",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        if job.task_spec_id is None:
            return _error_result_with_next(
                "prepare_outline",
                code="job_task_spec_missing",
                message=f"job {job_id} does not have a committed task_spec_id",
                exc=ValueError("task_spec_id"),
                next_suggested_tools=["prepare_task_spec"],
            )
        if job.selected_topic_id is None:
            return _error_result_with_next(
                "prepare_outline",
                code="selected_topic_missing",
                message=f"job {job_id} does not have a selected topic",
                exc=ValueError("selected_topic_id"),
                next_suggested_tools=["select_topic"],
            )
        try:
            task_spec = self.stores.task_store.load_latest(job.task_spec_id)
            selected_topic = self.stores.topic_store.load_selected_topic(job_id)
            research_plan = self.stores.research_plan_store.load_latest(job_id)
            research_result = self.stores.research_store.load_latest(job_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "prepare_outline",
                code="outline_artifacts_missing",
                message=f"job {job_id} is missing task, topic, research-plan, or evidence-map artifacts",
                exc=exc,
                next_suggested_tools=["create_research_plan", "prepare_research_notes"],
            )

        effective_bundle_id = source_packet_bundle_id or _latest_source_packet_bundle_id_for_stage(
            self.work_store,
            scope=f"job:{job_id}",
            stage="research_notes",
        )
        source_packets: list[SourceTextPacket] = []
        if effective_bundle_id is not None:
            try:
                bundle = self.work_store.load_source_packet_bundle(effective_bundle_id)
            except (KeyError, FileNotFoundError) as exc:
                return _error_result_with_next(
                    "prepare_outline",
                    code="source_packet_bundle_not_found",
                    message=f"SourcePacketBundle not found: {effective_bundle_id}",
                    exc=exc,
                    next_suggested_tools=["resolve_source_requests"],
                )
            if bundle.scope != f"job:{job_id}":
                return _error_result(
                    "prepare_outline",
                    code="source_packet_bundle_job_mismatch",
                    message=f"source packet bundle {effective_bundle_id} does not belong to job {job_id}",
                    exc=ValueError(effective_bundle_id),
                )
            packets_result = _source_text_packets_from_bundle(
                bundle,
                tool_name="prepare_outline",
            )
            if isinstance(packets_result, ToolResult):
                return packets_result
            source_packets = packets_result

        from essay_writer.outlining.service import build_outline_user_message

        user_message = build_outline_user_message(
            task_spec=task_spec,
            selected_topic=selected_topic,
            research_plan=research_plan,
            evidence_map=research_result.evidence_map,
            source_packets=source_packets,
        )
        packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "outline",
            short_hash([effective_bundle_id, user_message]),
        )
        artifact_refs = {
            "job_id": job_id,
            "task_spec_id": task_spec.id,
            "selected_topic_id": selected_topic.topic_id,
            "research_plan_id": research_plan.id,
            "evidence_map_id": research_result.evidence_map.id,
        }
        if effective_bundle_id is not None:
            artifact_refs["source_packet_bundle_id"] = effective_bundle_id
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="outline",
                scope=f"job:{job_id}",
                instructions=(
                    "Create a thesis-grounded outline from the task specification, selected topic, "
                    "research plan, evidence map, and source packets. Return JSON matching "
                    "response_schema; do not commit it."
                ),
                system_prompt=OUTLINE_SYSTEM_PROMPT,
                prompt_blocks=[
                    PromptBlock(text=user_message, cacheable=True),
                    PromptBlock(text="\n\nProduce a thesis-grounded outline using the inputs above."),
                ],
                response_schema=dict(OUTLINE_SCHEMA),
                context={
                    "job_id": job_id,
                    "task_spec_id": task_spec.id,
                    "selected_topic_id": selected_topic.topic_id,
                    "research_plan_id": research_plan.id,
                    "evidence_map_id": research_result.evidence_map.id,
                    "source_packet_bundle_id": effective_bundle_id,
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_outline",
                delegation=DelegationHint(
                    recommended=False,
                    reason="outline assembly is a global planning step",
                    allowed_tools=["submit_work_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not commit it; "
                        "the orchestrator will submit and commit the result."
                    ),
                ),
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="outlining",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_outline",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "job_id": job_id,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_outline(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("commit_outline", agent_run_id, exc)
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_outline",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.commit_tool != "commit_outline":
            return _error_result(
                "commit_outline",
                code="wrong_commit_tool",
                message=f"expected commit_outline packet, got {packet.commit_tool}",
                exc=ValueError(packet.commit_tool),
            )
        validation_error = _validate_work_payload(
            result.payload,
            OUTLINE_SCHEMA,
            tool_name="commit_outline",
        )
        if validation_error is not None:
            return validation_error

        packet_job_id = packet.context.get("job_id") or packet.artifact_refs.get("job_id")
        if not isinstance(packet_job_id, str) or not packet_job_id:
            return _error_result(
                "commit_outline",
                code="job_id_missing",
                message="outline packet is missing job_id",
                exc=ValueError("job_id"),
            )
        try:
            job = self.stores.workflow.load_job(packet_job_id)
            task_spec = self.stores.task_store.load_latest(str(packet.context["task_spec_id"]))
            selected_topic = self.stores.topic_store.load_selected_topic(packet_job_id)
            research_plan = _load_research_plan_for_job(
                self.stores.research_plan_store,
                job_id=packet_job_id,
                research_plan_id=str(packet.context["research_plan_id"]),
            )
            research_result = self.stores.research_store.load_latest(packet_job_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "commit_outline",
                code="outline_artifacts_missing",
                message=f"job {packet_job_id} is missing outline prerequisite artifacts",
                exc=exc,
                next_suggested_tools=["prepare_outline"],
            )

        scope = f"job:{packet_job_id}"
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="outline")
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None
        if existing_commit is not None:
            outline_version = existing_commit.artifact_refs.get("outline_version")
            if isinstance(outline_version, int):
                try:
                    outline = self.stores.outline_store.load(packet_job_id, outline_version)
                except KeyError as exc:
                    return _error_result(
                        "commit_outline",
                        code="outline_commit_artifact_missing",
                        message="Committed outline artifact is missing",
                        exc=exc,
                    )
            else:
                return _error_result(
                    "commit_outline",
                    code="outline_commit_artifact_missing",
                    message="Committed outline artifact is missing outline_version",
                    exc=KeyError(existing_commit.commit_id),
                )
            commit = existing_commit
        else:
            from essay_writer.outlining.service import thesis_outline_from_payload

            outline_version = self.stores.outline_store.next_version(packet_job_id)
            outline = thesis_outline_from_payload(
                result.payload,
                job=job,
                task_spec=task_spec,
                selected_topic=selected_topic,
                research_plan=research_plan,
                evidence_map=research_result.evidence_map,
                version=outline_version,
            )
            try:
                self.stores.outline_store.save(outline)
                self.stores.workflow.record_outline_ready(
                    job_id=packet_job_id,
                    outline=outline,
                )
            except (FileExistsError, TopicSelectionError) as exc:
                return _error_result(
                    "commit_outline",
                    code="outline_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
            artifact_refs = {
                "job_id": packet_job_id,
                "selected_topic_id": selected_topic.topic_id,
                "research_plan_id": research_plan.id,
                "evidence_map_id": research_result.evidence_map.id,
                "outline_id": outline.id,
                "outline_version": outline_version,
            }
            source_packet_bundle_id = packet.context.get("source_packet_bundle_id")
            if isinstance(source_packet_bundle_id, str) and source_packet_bundle_id:
                artifact_refs["source_packet_bundle_id"] = source_packet_bundle_id
            commit = self.work_store.save_commit(
                scope=scope,
                stage="outline",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )

        next_tools = ["prepare_draft"]
        if agent_run_id is not None:
            self.run_store.attach_work_result(
                agent_run_id,
                result.work_result_id,
                work_packet_id=packet.work_packet_id,
                next_suggested_tools=next_tools,
            )
            self.run_store.attach_commit(
                agent_run_id,
                dict(commit.artifact_refs),
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="drafting",
                decision="outline_committed",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_outline",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "job_id": packet_job_id,
                "outline_id": outline.id,
                "outline": asdict(outline),
                "artifact_refs": dict(commit.artifact_refs),
                "already_committed": already_committed,
                "next_suggested_tools": next_tools,
            },
            warnings=list(outline.warnings),
            next_suggested_tools=next_tools,
        )

    def prepare_draft(
        self,
        job_id: str,
        source_packet_bundle_id: str | None = None,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("prepare_draft", agent_run_id, exc)
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "prepare_draft",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        if job.task_spec_id is None:
            return _error_result_with_next(
                "prepare_draft",
                code="job_task_spec_missing",
                message=f"job {job_id} does not have a committed task_spec_id",
                exc=ValueError("task_spec_id"),
                next_suggested_tools=["prepare_task_spec"],
            )
        if job.selected_topic_id is None:
            return _error_result_with_next(
                "prepare_draft",
                code="selected_topic_missing",
                message=f"job {job_id} does not have a selected topic",
                exc=ValueError("selected_topic_id"),
                next_suggested_tools=["select_topic"],
            )
        try:
            task_spec = self.stores.task_store.load_latest(job.task_spec_id)
            selected_topic = self.stores.topic_store.load_selected_topic(job_id)
            research_result = self.stores.research_store.load_latest(job_id)
            outline = self.stores.outline_store.load_latest(job_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "prepare_draft",
                code="draft_artifacts_missing",
                message=f"job {job_id} is missing task, topic, evidence-map, or outline artifacts",
                exc=exc,
                next_suggested_tools=["prepare_research_notes", "prepare_outline"],
            )

        effective_bundle_id = source_packet_bundle_id or _latest_source_packet_bundle_id_for_stage(
            self.work_store,
            scope=f"job:{job_id}",
            stage="outline",
        )
        if effective_bundle_id is None:
            effective_bundle_id = _latest_source_packet_bundle_id_for_stage(
                self.work_store,
                scope=f"job:{job_id}",
                stage="research_notes",
            )
        source_packets: list[SourceTextPacket] = []
        if effective_bundle_id is not None:
            try:
                bundle = self.work_store.load_source_packet_bundle(effective_bundle_id)
            except (KeyError, FileNotFoundError) as exc:
                return _error_result_with_next(
                    "prepare_draft",
                    code="source_packet_bundle_not_found",
                    message=f"SourcePacketBundle not found: {effective_bundle_id}",
                    exc=exc,
                    next_suggested_tools=["resolve_source_requests"],
                )
            if bundle.scope != f"job:{job_id}":
                return _error_result(
                    "prepare_draft",
                    code="source_packet_bundle_job_mismatch",
                    message=f"source packet bundle {effective_bundle_id} does not belong to job {job_id}",
                    exc=ValueError(effective_bundle_id),
                )
            packets_result = _source_text_packets_from_bundle(
                bundle,
                tool_name="prepare_draft",
            )
            if isinstance(packets_result, ToolResult):
                return packets_result
            source_packets = packets_result

        from essay_writer.drafting.service import build_drafting_user_blocks

        user_blocks = build_drafting_user_blocks(
            task_spec,
            selected_topic,
            research_result.evidence_map,
            outline,
            source_packets,
            None,
        )
        prompt_blocks = [
            PromptBlock(text=block.text, cacheable=block.cacheable)
            for block in user_blocks
        ]
        packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "draft",
            short_hash([effective_bundle_id, [block.text for block in prompt_blocks]]),
        )
        artifact_refs = {
            "job_id": job_id,
            "task_spec_id": task_spec.id,
            "selected_topic_id": selected_topic.topic_id,
            "evidence_map_id": research_result.evidence_map.id,
            "outline_id": outline.id,
        }
        if effective_bundle_id is not None:
            artifact_refs["source_packet_bundle_id"] = effective_bundle_id
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="draft",
                scope=f"job:{job_id}",
                instructions=(
                    "Draft the essay from the task specification, selected topic, evidence map, "
                    "outline, and source packets. Return JSON matching response_schema; do not commit it."
                ),
                system_prompt=DRAFTING_SYSTEM_PROMPT,
                prompt_blocks=prompt_blocks,
                response_schema=dict(DRAFTING_SCHEMA),
                context={
                    "job_id": job_id,
                    "task_spec_id": task_spec.id,
                    "selected_topic_id": selected_topic.topic_id,
                    "evidence_map_id": research_result.evidence_map.id,
                    "outline_id": outline.id,
                    "source_packet_bundle_id": effective_bundle_id,
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_draft",
                delegation=DelegationHint(
                    recommended=False,
                    reason="full draft assembly is a global synthesis step",
                    allowed_tools=["submit_work_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not commit it; "
                        "the orchestrator will submit and commit the result."
                    ),
                ),
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="drafting",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_draft",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "job_id": job_id,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_draft(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("commit_draft", agent_run_id, exc)
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_draft",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.commit_tool != "commit_draft":
            return _error_result(
                "commit_draft",
                code="wrong_commit_tool",
                message=f"expected commit_draft packet, got {packet.commit_tool}",
                exc=ValueError(packet.commit_tool),
            )
        validation_error = _validate_work_payload(
            result.payload,
            DRAFTING_SCHEMA,
            tool_name="commit_draft",
        )
        if validation_error is not None:
            return validation_error
        packet_job_id = packet.context.get("job_id") or packet.artifact_refs.get("job_id")
        if not isinstance(packet_job_id, str) or not packet_job_id:
            return _error_result(
                "commit_draft",
                code="job_id_missing",
                message="draft packet is missing job_id",
                exc=ValueError("job_id"),
            )
        try:
            job = self.stores.workflow.load_job(packet_job_id)
            task_spec = self.stores.task_store.load_latest(str(packet.context["task_spec_id"]))
            selected_topic = self.stores.topic_store.load_selected_topic(packet_job_id)
            research_result = self.stores.research_store.load_latest(packet_job_id)
            outline = self.stores.outline_store.load_latest(packet_job_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "commit_draft",
                code="draft_artifacts_missing",
                message=f"job {packet_job_id} is missing draft prerequisite artifacts",
                exc=exc,
                next_suggested_tools=["prepare_draft"],
            )
        note_error = _validate_draft_note_refs(
            result.payload,
            research_result.evidence_map,
            tool_name="commit_draft",
        )
        if note_error is not None:
            return note_error

        scope = f"job:{packet_job_id}"
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="draft")
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None
        if existing_commit is not None:
            draft_version = existing_commit.artifact_refs.get("draft_version")
            if isinstance(draft_version, int):
                try:
                    draft = self.stores.draft_store.load(packet_job_id, draft_version)
                except KeyError as exc:
                    return _error_result(
                        "commit_draft",
                        code="draft_commit_artifact_missing",
                        message="Committed draft artifact is missing",
                        exc=exc,
                    )
            else:
                return _error_result(
                    "commit_draft",
                    code="draft_commit_artifact_missing",
                    message="Committed draft artifact is missing draft_version",
                    exc=KeyError(existing_commit.commit_id),
                )
            commit = existing_commit
        else:
            from essay_writer.drafting.service import draft_from_payload

            draft_version = self.stores.draft_store.next_version(packet_job_id)
            draft = draft_from_payload(
                result.payload,
                job=job,
                selected_topic=selected_topic,
                task_spec=task_spec,
                outline=outline,
                version=draft_version,
                prompt_version="drafting-v1",
            )
            try:
                self.stores.draft_store.save(draft)
                self.stores.workflow.record_draft_ready(
                    job_id=packet_job_id,
                    draft=draft,
                )
            except (FileExistsError, TopicSelectionError) as exc:
                return _error_result(
                    "commit_draft",
                    code="draft_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
            artifact_refs = {
                "job_id": packet_job_id,
                "selected_topic_id": selected_topic.topic_id,
                "evidence_map_id": research_result.evidence_map.id,
                "outline_id": outline.id,
                "draft_id": draft.id,
                "draft_version": draft_version,
            }
            source_packet_bundle_id = packet.context.get("source_packet_bundle_id")
            if isinstance(source_packet_bundle_id, str) and source_packet_bundle_id:
                artifact_refs["source_packet_bundle_id"] = source_packet_bundle_id
            commit = self.work_store.save_commit(
                scope=scope,
                stage="draft",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )

        next_tools = ["prepare_validation"]
        if agent_run_id is not None:
            self.run_store.attach_work_result(
                agent_run_id,
                result.work_result_id,
                work_packet_id=packet.work_packet_id,
                next_suggested_tools=next_tools,
            )
            self.run_store.attach_commit(
                agent_run_id,
                dict(commit.artifact_refs),
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="validation",
                decision="draft_committed",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_draft",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "job_id": packet_job_id,
                "draft_id": draft.id,
                "draft": asdict(draft),
                "artifact_refs": dict(commit.artifact_refs),
                "already_committed": already_committed,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def prepare_revision(
        self,
        job_id: str,
        source_draft_id: str | None = None,
        validation_version: int | None = None,
        *,
        user_instruction: str | None = None,
        selected_lenses: list[str] | None = None,
        source_packet_bundle_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("prepare_revision", agent_run_id, exc)
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "prepare_revision",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        try:
            task_spec = self.stores.task_store.load_latest(str(job.task_spec_id))
            selected_topic = self.stores.topic_store.load_selected_topic(job_id)
            research_result = self.stores.research_store.load_latest(job_id)
            outline = self.stores.outline_store.load_latest(job_id)
            previous_draft = (
                self.stores.draft_store.find_by_id(job_id, source_draft_id)
                if source_draft_id is not None
                else self.stores.draft_store.load_latest(job_id)
            )
            effective_validation_version = validation_version or _latest_validation_version(self.stores, job_id)
            validation = self.stores.validation_store.load(job_id, effective_validation_version)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "prepare_revision",
                code="revision_artifacts_missing",
                message=f"job {job_id} is missing draft revision prerequisite artifacts",
                exc=exc,
                next_suggested_tools=["prepare_validation", "commit_validation"],
            )
        if validation.draft_id != previous_draft.id:
            return _error_result_with_next(
                "prepare_revision",
                code="validation_draft_mismatch",
                message="validation report does not match the draft selected for revision",
                exc=ValueError(validation.draft_id),
                next_suggested_tools=["prepare_validation"],
            )

        effective_bundle_id = source_packet_bundle_id or _latest_source_packet_bundle_id_for_stage(
            self.work_store,
            scope=f"job:{job_id}",
            stage="draft",
        )
        if effective_bundle_id is None:
            effective_bundle_id = _latest_source_packet_bundle_id_for_stage(
                self.work_store,
                scope=f"job:{job_id}",
                stage="outline",
            )
        source_packets: list[SourceTextPacket] = []
        if effective_bundle_id is not None:
            try:
                bundle = self.work_store.load_source_packet_bundle(effective_bundle_id)
            except (KeyError, FileNotFoundError) as exc:
                return _error_result_with_next(
                    "prepare_revision",
                    code="source_packet_bundle_not_found",
                    message=f"SourcePacketBundle not found: {effective_bundle_id}",
                    exc=exc,
                    next_suggested_tools=["resolve_source_requests"],
                )
            if bundle.scope != f"job:{job_id}":
                return _error_result(
                    "prepare_revision",
                    code="source_packet_bundle_job_mismatch",
                    message=f"source packet bundle {effective_bundle_id} does not belong to job {job_id}",
                    exc=ValueError(effective_bundle_id),
                )
            packets_result = _source_text_packets_from_bundle(
                bundle,
                tool_name="prepare_revision",
            )
            if isinstance(packets_result, ToolResult):
                return packets_result
            source_packets = packets_result

        from essay_writer.drafting.revision import build_revision_user_blocks

        effective_lenses = [str(item) for item in (selected_lenses or [])]
        user_blocks = build_revision_user_blocks(
            task_spec=task_spec,
            selected_topic=selected_topic,
            evidence_map=research_result.evidence_map,
            outline=outline,
            previous_draft=previous_draft,
            validation=validation,
            source_packets=source_packets,
            writing_style_payload=None,
            tone_alignment=None,
            user_instruction=user_instruction,
            change_summary=[],
        )
        prompt_blocks = [
            PromptBlock(text=block.text, cacheable=block.cacheable)
            for block in user_blocks
        ]
        packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "revision",
            short_hash([previous_draft.id, effective_validation_version, [block.text for block in prompt_blocks]]),
        )
        artifact_refs = {
            "job_id": job_id,
            "task_spec_id": task_spec.id,
            "selected_topic_id": selected_topic.topic_id,
            "evidence_map_id": research_result.evidence_map.id,
            "outline_id": outline.id,
            "source_draft_id": previous_draft.id,
            "validation_version": effective_validation_version,
        }
        if effective_bundle_id is not None:
            artifact_refs["source_packet_bundle_id"] = effective_bundle_id
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="revision",
                scope=f"job:{job_id}",
                instructions=(
                    "Revise the existing draft using validation diagnostics and the supplied "
                    "evidence. Return JSON matching response_schema; do not commit it."
                ),
                system_prompt=DRAFTING_SYSTEM_PROMPT,
                prompt_blocks=prompt_blocks,
                response_schema=dict(DRAFTING_SCHEMA),
                context={
                    "job_id": job_id,
                    "task_spec_id": task_spec.id,
                    "selected_topic_id": selected_topic.topic_id,
                    "evidence_map_id": research_result.evidence_map.id,
                    "outline_id": outline.id,
                    "source_draft_id": previous_draft.id,
                    "source_draft_version": previous_draft.version,
                    "validation_version": effective_validation_version,
                    "source_packet_bundle_id": effective_bundle_id,
                    "user_instruction": user_instruction,
                    "selected_lenses": effective_lenses,
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_revision",
                delegation=DelegationHint(
                    recommended=False,
                    reason="revision is a full-draft synthesis step",
                    allowed_tools=["submit_work_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not commit it; "
                        "the orchestrator will submit and commit the result."
                    ),
                ),
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="revision",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_revision",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "job_id": job_id,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_revision(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("commit_revision", agent_run_id, exc)
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_revision",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.commit_tool != "commit_revision":
            return _error_result(
                "commit_revision",
                code="wrong_commit_tool",
                message=f"expected commit_revision packet, got {packet.commit_tool}",
                exc=ValueError(packet.commit_tool),
            )
        validation_error = _validate_work_payload(
            result.payload,
            DRAFTING_SCHEMA,
            tool_name="commit_revision",
        )
        if validation_error is not None:
            return validation_error
        packet_job_id = packet.context.get("job_id") or packet.artifact_refs.get("job_id")
        if not isinstance(packet_job_id, str) or not packet_job_id:
            return _error_result(
                "commit_revision",
                code="job_id_missing",
                message="revision packet is missing job_id",
                exc=ValueError("job_id"),
            )
        try:
            job = self.stores.workflow.load_job(packet_job_id)
            task_spec = self.stores.task_store.load_latest(str(packet.context["task_spec_id"]))
            selected_topic = self.stores.topic_store.load_selected_topic(packet_job_id)
            research_result = self.stores.research_store.load_latest(packet_job_id)
            outline = self.stores.outline_store.load_latest(packet_job_id)
            previous_draft = self.stores.draft_store.find_by_id(
                packet_job_id,
                str(packet.context["source_draft_id"]),
            )
            validation_version = int(packet.context["validation_version"])
            validation = self.stores.validation_store.load(packet_job_id, validation_version)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "commit_revision",
                code="revision_artifacts_missing",
                message=f"job {packet_job_id} is missing revision prerequisite artifacts",
                exc=exc,
                next_suggested_tools=["prepare_revision"],
            )
        if validation.draft_id != previous_draft.id:
            return _error_result_with_next(
                "commit_revision",
                code="validation_draft_mismatch",
                message="validation report does not match the draft selected for revision",
                exc=ValueError(validation.draft_id),
                next_suggested_tools=["prepare_validation"],
            )
        note_error = _validate_draft_note_refs(
            result.payload,
            research_result.evidence_map,
            tool_name="commit_revision",
        )
        if note_error is not None:
            return note_error

        scope = f"job:{packet_job_id}"
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="revision")
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None
        if existing_commit is not None:
            draft_version = existing_commit.artifact_refs.get("draft_version")
            if isinstance(draft_version, int):
                try:
                    draft = self.stores.draft_store.load(packet_job_id, draft_version)
                except KeyError as exc:
                    return _error_result(
                        "commit_revision",
                        code="revision_commit_artifact_missing",
                        message="Committed revision artifact is missing",
                        exc=exc,
                    )
            else:
                return _error_result(
                    "commit_revision",
                    code="revision_commit_artifact_missing",
                    message="Committed revision artifact is missing draft_version",
                    exc=KeyError(existing_commit.commit_id),
                )
            commit = existing_commit
        else:
            from essay_writer.drafting.revision import revised_draft_from_payload

            draft_version = self.stores.draft_store.next_version(packet_job_id)
            draft = revised_draft_from_payload(
                result.payload,
                job=job,
                selected_topic=selected_topic,
                task_spec=task_spec,
                outline=outline,
                version=draft_version,
                prompt_version="drafting-revision-v1",
            )
            draft = replace(
                draft,
                origin="system_revision",
                created_by="system",
                parent_draft_id=previous_draft.id,
                manual_request_id=None,
                user_instruction=_optional_context_str(packet.context.get("user_instruction")),
                selected_lenses=_string_list(packet.context.get("selected_lenses")),
            )
            try:
                self.stores.draft_store.save(draft)
                self.stores.workflow.record_draft_ready(
                    job_id=packet_job_id,
                    draft=draft,
                )
            except (FileExistsError, TopicSelectionError) as exc:
                return _error_result(
                    "commit_revision",
                    code="revision_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
            artifact_refs = {
                "job_id": packet_job_id,
                "selected_topic_id": selected_topic.topic_id,
                "evidence_map_id": research_result.evidence_map.id,
                "outline_id": outline.id,
                "source_draft_id": previous_draft.id,
                "draft_id": draft.id,
                "draft_version": draft_version,
                "validation_version": validation_version,
            }
            source_packet_bundle_id = packet.context.get("source_packet_bundle_id")
            if isinstance(source_packet_bundle_id, str) and source_packet_bundle_id:
                artifact_refs["source_packet_bundle_id"] = source_packet_bundle_id
            commit = self.work_store.save_commit(
                scope=scope,
                stage="revision",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )

        next_tools = ["prepare_validation"]
        if agent_run_id is not None:
            self.run_store.attach_work_result(
                agent_run_id,
                result.work_result_id,
                work_packet_id=packet.work_packet_id,
                next_suggested_tools=next_tools,
            )
            self.run_store.attach_commit(
                agent_run_id,
                dict(commit.artifact_refs),
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="validation",
                decision="revision_committed",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_revision",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "job_id": packet_job_id,
                "draft_id": draft.id,
                "draft": asdict(draft),
                "artifact_refs": dict(commit.artifact_refs),
                "already_committed": already_committed,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def run_deterministic_checks(
        self,
        draft_text_or_id: str,
        *,
        job_id: str | None = None,
    ) -> ToolResult:
        draft_text = draft_text_or_id
        draft_id = None
        if job_id is not None:
            try:
                draft = self.stores.draft_store.find_by_id(job_id, draft_text_or_id)
                draft_text = draft.content
                draft_id = draft.id
            except KeyError:
                draft_id = None
        det = run_validation_deterministic_checks(draft_text)
        return ToolResult(
            ok=True,
            tool_name="run_deterministic_checks",
            data={
                "draft_id": draft_id,
                "deterministic": asdict(det),
                "has_issues": det.has_issues,
            },
        )

    def prepare_validation(
        self,
        job_id: str,
        draft_id: str | None = None,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("prepare_validation", agent_run_id, exc)
        try:
            job = self.stores.workflow.load_job(job_id)
            draft = _load_draft_for_job(self.stores, job_id=job_id, draft_id=draft_id)
            task_spec = self.stores.task_store.load_latest(str(job.task_spec_id))
            research_result = self.stores.research_store.load_latest(job_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "prepare_validation",
                code="validation_artifacts_missing",
                message=f"job {job_id} is missing validation prerequisite artifacts",
                exc=exc,
                next_suggested_tools=["prepare_draft"],
            )
        source_cards = []
        for source_id in job.source_ids:
            try:
                source_cards.append(self.stores.source_store.load_source_card(source_id))
            except (KeyError, FileNotFoundError):
                continue
        det = run_validation_deterministic_checks(draft.content)
        metadata_warnings = check_bibliography_against_source_cards(
            draft.bibliography_candidates,
            source_cards,
        )
        from essay_writer.validation.service import build_validation_user_blocks

        user_blocks = build_validation_user_blocks(
            draft.content,
            task_spec=task_spec,
            evidence_map=research_result.evidence_map.notes,
            det=det,
            bibliography_candidates=draft.bibliography_candidates,
            source_cards=source_cards,
            metadata_warnings=metadata_warnings,
        )
        prompt_blocks = [
            PromptBlock(text=block.text, cacheable=block.cacheable)
            for block in user_blocks
        ]
        packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "validation",
            short_hash([draft.id, [block.text for block in prompt_blocks]]),
        )
        artifact_refs = {
            "job_id": job_id,
            "task_spec_id": task_spec.id,
            "draft_id": draft.id,
            "draft_version": draft.version,
            "evidence_map_id": research_result.evidence_map.id,
        }
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="validation",
                scope=f"job:{job_id}",
                instructions=(
                    "Validate the draft against the task, evidence map, citations, and deterministic "
                    "style checks. Return JSON matching response_schema; do not commit it."
                ),
                system_prompt=VALIDATION_SYSTEM_PROMPT,
                prompt_blocks=prompt_blocks,
                response_schema=dict(VALIDATION_SCHEMA),
                context={
                    "job_id": job_id,
                    "task_spec_id": task_spec.id,
                    "draft_id": draft.id,
                    "draft_version": draft.version,
                    "deterministic": asdict(det),
                    "metadata_citation_warnings": [asdict(item) for item in metadata_warnings],
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_validation",
                delegation=DelegationHint(
                    recommended=False,
                    reason="validation is a whole-draft judgment step",
                    allowed_tools=["submit_work_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not commit it; "
                        "the orchestrator will submit and commit the result."
                    ),
                ),
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="validation",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_validation",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "job_id": job_id,
                "draft_id": draft.id,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "deterministic": asdict(det),
                "metadata_citation_warnings": [asdict(item) for item in metadata_warnings],
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_validation(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("commit_validation", agent_run_id, exc)
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_validation",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.commit_tool != "commit_validation":
            return _error_result(
                "commit_validation",
                code="wrong_commit_tool",
                message=f"expected commit_validation packet, got {packet.commit_tool}",
                exc=ValueError(packet.commit_tool),
            )
        validation_error = _validate_work_payload(
            result.payload,
            VALIDATION_SCHEMA,
            tool_name="commit_validation",
        )
        if validation_error is not None:
            return validation_error
        packet_job_id = packet.context.get("job_id") or packet.artifact_refs.get("job_id")
        if not isinstance(packet_job_id, str) or not packet_job_id:
            return _error_result(
                "commit_validation",
                code="job_id_missing",
                message="validation packet is missing job_id",
                exc=ValueError("job_id"),
            )
        try:
            task_spec_id = str(packet.context["task_spec_id"])
            draft_id = str(packet.context["draft_id"])
            det = _deterministic_from_payload(dict(packet.context["deterministic"]))
            metadata_warnings = _metadata_warnings_from_payload(
                packet.context.get("metadata_citation_warnings", [])
            )
        except (KeyError, TypeError, ValueError) as exc:
            return _error_result(
                "commit_validation",
                code="validation_context_invalid",
                message="validation packet context is missing deterministic validation data",
                exc=exc,
            )
        from essay_writer.validation.service import validation_judgment_from_payload

        report = ValidationReport(
            draft_id=draft_id,
            task_spec_id=task_spec_id,
            deterministic=det,
            llm_judgment=validation_judgment_from_payload(result.payload),
            metadata_citation_warnings=metadata_warnings,
            prompt_version="validation-v1",
        )
        scope = f"job:{packet_job_id}"
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="validation")
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None
        if existing_commit is not None:
            validation_version = existing_commit.artifact_refs.get("validation_version")
            if not isinstance(validation_version, int):
                return _error_result(
                    "commit_validation",
                    code="validation_commit_artifact_missing",
                    message="Committed validation artifact is missing validation_version",
                    exc=KeyError(existing_commit.commit_id),
                )
            try:
                report = self.stores.validation_store.load(packet_job_id, validation_version)
            except KeyError as exc:
                return _error_result(
                    "commit_validation",
                    code="validation_commit_artifact_missing",
                    message="Committed validation artifact is missing",
                    exc=exc,
                )
            commit = existing_commit
        else:
            validation_version = self.stores.validation_store.next_version(packet_job_id)
            validation_report_id = f"validation_report_v{validation_version:03d}"
            try:
                self.stores.validation_store.save(
                    packet_job_id,
                    report,
                    version=validation_version,
                )
                self.stores.workflow.record_validation_complete(
                    job_id=packet_job_id,
                    validation_report_id=validation_report_id,
                    passes=report.passes,
                )
            except (FileExistsError, TopicSelectionError) as exc:
                return _error_result(
                    "commit_validation",
                    code="validation_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
            commit = self.work_store.save_commit(
                scope=scope,
                stage="validation",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs={
                    "job_id": packet_job_id,
                    "draft_id": draft_id,
                    "validation_report_id": validation_report_id,
                    "validation_version": validation_version,
                    "passes": report.passes,
                },
            )
        next_tools = ["export_markdown"] if report.passes else ["prepare_revision"]
        if agent_run_id is not None:
            self.run_store.attach_work_result(
                agent_run_id,
                result.work_result_id,
                work_packet_id=packet.work_packet_id,
                next_suggested_tools=next_tools,
            )
            self.run_store.attach_commit(
                agent_run_id,
                dict(commit.artifact_refs),
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="export" if report.passes else "revision",
                decision="validation_committed",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_validation",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "job_id": packet_job_id,
                "draft_id": report.draft_id,
                "validation_report_id": commit.artifact_refs.get("validation_report_id"),
                "validation_report": asdict(report),
                "passes": report.passes,
                "artifact_refs": dict(commit.artifact_refs),
                "already_committed": already_committed,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def save_user_edit(
        self,
        job_id: str,
        draft_id: str,
        content: str,
        *,
        parent_export_id: str | None = None,
        user_instruction: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("save_user_edit", agent_run_id, exc)
        try:
            parent = self.stores.draft_store.find_by_id(job_id, draft_id)
        except KeyError as exc:
            return _error_result(
                "save_user_edit",
                code="draft_not_found",
                message=f"Draft not found for job {job_id}: {draft_id}",
                exc=exc,
            )
        version = self.stores.draft_store.next_version(job_id)
        edited = replace(
            parent,
            id=f"draft_{short_hash([job_id, draft_id, content, version])}",
            version=version,
            content=content,
            origin="user_edit",
            created_by="user",
            parent_draft_id=parent.id,
            parent_export_id=parent_export_id,
            user_instruction=user_instruction,
        )
        try:
            self.stores.draft_store.save(edited)
            self.stores.workflow.record_draft_ready(job_id=job_id, draft=edited)
        except (FileExistsError, TopicSelectionError) as exc:
            return _error_result(
                "save_user_edit",
                code="user_edit_save_failed",
                message=str(exc),
                exc=exc,
            )
        next_tools = ["prepare_validation"]
        artifact_refs = {"job_id": job_id, "draft_id": edited.id, "draft_version": version}
        if agent_run_id is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="save_user_edit",
            data={
                "job_id": job_id,
                "draft_id": edited.id,
                "draft": asdict(edited),
                "artifact_refs": artifact_refs,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def list_drafts(self, job_id: str) -> ToolResult:
        drafts = self.stores.draft_store.list_versions(job_id)
        return ToolResult(
            ok=True,
            tool_name="list_drafts",
            data={"drafts": [asdict(draft) for draft in drafts]},
        )

    def get_draft(
        self,
        job_id: str,
        *,
        draft_id: str | None = None,
        version: int | None = None,
    ) -> ToolResult:
        try:
            if draft_id is not None:
                draft = self.stores.draft_store.find_by_id(job_id, draft_id)
            elif version is not None:
                draft = self.stores.draft_store.load(job_id, version)
            else:
                draft = self.stores.draft_store.load_latest(job_id)
        except KeyError as exc:
            return _error_result(
                "get_draft",
                code="draft_not_found",
                message=f"Draft not found for job {job_id}",
                exc=exc,
            )
        return ToolResult(ok=True, tool_name="get_draft", data={"draft": asdict(draft)})

    def export_markdown(
        self,
        job_id: str,
        *,
        draft_id: str | None = None,
        validation_version: int | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if agent_run_id is not None:
            try:
                self.run_store.load_run(agent_run_id)
            except (KeyError, FileNotFoundError) as exc:
                return _missing_run_result("export_markdown", agent_run_id, exc)
        try:
            job = self.stores.workflow.load_job(job_id)
            task_spec = self.stores.task_store.load_latest(str(job.task_spec_id))
            draft = _load_draft_for_job(self.stores, job_id=job_id, draft_id=draft_id)
            validation = (
                self.stores.validation_store.load(job_id, validation_version)
                if validation_version is not None
                else self.stores.validation_store.load_latest(job_id)
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "export_markdown",
                code="export_artifacts_missing",
                message=f"job {job_id} is missing export prerequisite artifacts",
                exc=exc,
                next_suggested_tools=["prepare_validation"],
            )
        if validation.draft_id != draft.id:
            return _error_result_with_next(
                "export_markdown",
                code="validation_draft_mismatch",
                message="validation report does not match the draft selected for export",
                exc=ValueError(validation.draft_id),
                next_suggested_tools=["prepare_validation"],
            )
        export = FinalExportService().create_markdown_export(
            job=job,
            task_spec=task_spec,
            draft=draft,
            validation=validation,
        )
        try:
            self.stores.export_store.save(export)
            self.stores.workflow.record_final_export_ready(job_id=job_id, export=export)
        except (FileExistsError, TopicSelectionError) as exc:
            return _error_result(
                "export_markdown",
                code="export_save_failed",
                message=str(exc),
                exc=exc,
            )
        artifact_refs = {"job_id": job_id, "draft_id": draft.id, "export_id": export.id}
        next_tools: list[str] = []
        if agent_run_id is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="export_markdown",
            data={
                "job_id": job_id,
                "export_id": export.id,
                "format": export.export_format,
                "content": export.content,
                "preview": export.content[:500],
                "artifact_refs": artifact_refs,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def _direct_source_card_work_result(
        self,
        *,
        source_id: str | None,
        payload: dict[str, object] | None,
    ) -> ToolResult:
        if source_id is None or payload is None:
            return _error_result(
                "commit_source_card",
                code="source_card_commit_input_missing",
                message="commit_source_card requires work_result_id or source_id plus payload",
                exc=ValueError("missing commit input"),
            )
        if not isinstance(payload, dict):
            return _error_result(
                "commit_source_card",
                code="work_result_payload_not_object",
                message="source-card payload must be a JSON object",
                exc=TypeError(type(payload).__name__),
            )
        validation_error = _validate_work_payload(
            payload,
            source_summary.SOURCE_CARD_SCHEMA,
            tool_name="commit_source_card",
        )
        if validation_error is not None:
            return validation_error
        if not self.stores.source_store.has_text_artifacts(source_id):
            return _error_result(
                "commit_source_card",
                code="source_text_artifacts_missing",
                message=f"source text artifacts are missing for source: {source_id}",
                exc=FileNotFoundError(source_id),
            )
        source = self.stores.source_store.load_source(source_id)
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=(
                    "workpkt_source_"
                    f"{safe_slug(source_id)}_source_card_direct_{short_hash(payload)}"
                ),
                stage="source_card",
                scope=f"source:{source_id}",
                instructions="Direct source-card payload commit.",
                system_prompt=source_summary.SOURCE_CARD_SYSTEM_PROMPT,
                prompt_blocks=[],
                response_schema=dict(source_summary.SOURCE_CARD_SCHEMA),
                context={
                    "source_id": source_id,
                    "summary_char_limit": self.source_materializer._config.source_card_summary_char_limit,
                    "file_name": source.file_name,
                },
                artifact_refs={"source_id": source_id},
                commit_tool="commit_source_card",
                delegation=DelegationHint(recommended=False),
            )
        )
        result = self.work_store.submit_result(
            packet.work_packet_id,
            payload=payload,
            producer=WorkProducer(type="system", role="direct_commit", name=None),
        )
        return ToolResult(
            ok=True,
            tool_name="commit_source_card",
            data={"work_result_id": result.work_result_id},
        )

    def _direct_topic_work_result(
        self,
        *,
        job_id: str | None,
        payload: dict[str, object] | None,
        user_instruction: str | None,
    ) -> ToolResult:
        if job_id is None or payload is None:
            return _error_result(
                "commit_topics",
                code="topic_commit_input_missing",
                message="commit_topics requires work_result_id or job_id plus payload",
                exc=ValueError("missing commit input"),
            )
        if not isinstance(payload, dict):
            return _error_result(
                "commit_topics",
                code="work_result_payload_not_object",
                message="topic payload must be a JSON object",
                exc=TypeError(type(payload).__name__),
            )
        validation_error = _validate_work_payload(
            payload,
            TOPIC_IDEATION_SCHEMA,
            tool_name="commit_topics",
        )
        if validation_error is not None:
            return validation_error
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "commit_topics",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        readiness_error = _topic_job_readiness_error(
            self.stores,
            job,
            tool_name="commit_topics",
        )
        if readiness_error is not None:
            return readiness_error
        packet = self.work_store.save_packet(
            WorkPacket(
                work_packet_id=(
                    "workpkt_job_"
                    f"{safe_slug(job_id)}_topic_ideation_direct_{short_hash(payload)}"
                ),
                stage="topic_ideation",
                scope=f"job:{job_id}",
                instructions="Direct topic-ideation payload commit.",
                system_prompt=TOPIC_IDEATION_SYSTEM_PROMPT,
                prompt_blocks=[],
                response_schema=dict(TOPIC_IDEATION_SCHEMA),
                context={
                    "job_id": job_id,
                    "task_spec_id": job.task_spec_id,
                    "user_instruction": user_instruction,
                    "max_candidates": 8,
                },
                artifact_refs={
                    "job_id": job_id,
                    "task_spec_id": job.task_spec_id,
                    "source_ids": list(job.source_ids),
                },
                commit_tool="commit_topics",
                delegation=DelegationHint(recommended=False),
            )
        )
        result = self.work_store.submit_result(
            packet.work_packet_id,
            payload=payload,
            producer=WorkProducer(type="system", role="direct_commit", name=None),
        )
        return ToolResult(
            ok=True,
            tool_name="commit_topics",
            data={"work_result_id": result.work_result_id},
        )


def source_locator_to_payload(locator: SourceLocator) -> dict[str, object]:
    return {
        "source_id": locator.source_id,
        "locator_type": locator.locator_type,
        "pdf_page_start": locator.pdf_page_start,
        "pdf_page_end": locator.pdf_page_end,
        "printed_page_label": locator.printed_page_label,
        "section_id": locator.section_id,
        "query": locator.query,
        "chunk_id": locator.chunk_id,
        "reason": locator.reason,
    }


def source_packet_to_payload(packet: SourceTextPacket) -> dict[str, object]:
    return {
        "packet_id": packet.packet_id,
        "source_id": packet.source_id,
        "locator": source_locator_to_payload(packet.locator),
        "text": packet.text,
        "pdf_page_start": packet.pdf_page_start,
        "pdf_page_end": packet.pdf_page_end,
        "printed_page_start": packet.printed_page_start,
        "printed_page_end": packet.printed_page_end,
        "heading_path": list(packet.heading_path),
        "extraction_method": packet.extraction_method,
        "text_quality": packet.text_quality,
        "warnings": list(packet.warnings),
    }


def _locator_from_payload_result(
    payload: dict[str, object],
    *,
    tool_name: str,
    next_suggested_tools: list[str],
) -> SourceLocator | ToolResult:
    if not isinstance(payload, dict):
        return _error_result_with_next(
            tool_name,
            code="invalid_locator_payload",
            message="source locator payload must be a JSON object",
            exc=TypeError(type(payload).__name__),
            next_suggested_tools=next_suggested_tools,
        )
    try:
        locator = locator_from_payload(payload)
    except (TypeError, ValueError) as exc:
        return _error_result_with_next(
            tool_name,
            code="invalid_locator_payload",
            message=f"source locator payload is invalid: {exc}",
            exc=exc,
            next_suggested_tools=next_suggested_tools,
        )
    if not locator.source_id or locator.locator_type not in {"pdf_pages", "section", "search", "chunk"}:
        return _error_result_with_next(
            tool_name,
            code="invalid_locator_payload",
            message="source locator payload requires source_id and a supported locator_type",
            exc=ValueError("source locator"),
            next_suggested_tools=next_suggested_tools,
        )
    return locator


def _validate_max_chars(max_chars: object, *, tool_name: str) -> ToolResult | None:
    if max_chars is None:
        return None
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        return _error_result(
            tool_name,
            code="invalid_max_chars",
            message="max_chars must be a positive integer.",
            exc=ValueError("max_chars"),
        )
    return None


def _validate_topic_max_candidates(value: object, *, tool_name: str) -> int | ToolResult:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return _error_result(
            tool_name,
            code="invalid_max_candidates",
            message="max_candidates must be a positive integer.",
            exc=ValueError("max_candidates"),
        )
    return value


def _validate_research_max_notes(value: object, *, tool_name: str) -> int | ToolResult:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return _error_result(
            tool_name,
            code="invalid_max_notes",
            message="max_notes must be a positive integer.",
            exc=ValueError("max_notes"),
        )
    return value


def _topic_job_readiness_error(
    stores: AgentStoreBundle,
    job: object,
    *,
    tool_name: str,
) -> ToolResult | None:
    job_id = str(getattr(job, "id"))
    if getattr(job, "task_spec_id", None) is None:
        return _error_result_with_next(
            tool_name,
            code="job_task_spec_missing",
            message=f"job {job_id} does not have a committed task_spec_id",
            exc=ValueError("task_spec_id"),
            next_suggested_tools=["prepare_task_spec"],
        )

    source_ids = list(getattr(job, "source_ids", []))
    if not source_ids:
        return _error_result_with_next(
            tool_name,
            code="job_sources_missing",
            message=f"job {job_id} does not have committed source_ids",
            exc=ValueError("source_ids"),
            next_suggested_tools=["ingest_source_file", "prepare_source_card"],
        )

    for source_id in source_ids:
        if not stores.source_store.has_text_artifacts(source_id):
            return _error_result_with_next(
                tool_name,
                code="source_text_artifacts_missing",
                message=f"source text artifacts are missing for source: {source_id}",
                exc=FileNotFoundError(source_id),
                next_suggested_tools=["ingest_source_file"],
            )
        if not stores.source_store.has_source_card(source_id):
            return _error_result_with_next(
                tool_name,
                code="source_card_missing",
                message=f"source card is missing for source: {source_id}",
                exc=FileNotFoundError(source_id),
                next_suggested_tools=["prepare_source_card"],
            )
    return None


def _source_text_packets_from_bundle(
    bundle: SourcePacketBundle,
    *,
    tool_name: str,
) -> list[SourceTextPacket] | ToolResult:
    packets: list[SourceTextPacket] = []
    for payload in bundle.packet_payloads:
        try:
            packets.append(_source_text_packet_from_payload(payload))
        except (TypeError, ValueError) as exc:
            return _error_result(
                tool_name,
                code="source_packet_bundle_invalid",
                message=f"source packet bundle {bundle.source_packet_bundle_id} contains invalid packet payloads",
                exc=exc,
            )
    return packets


def _source_text_packet_from_payload(payload: dict[str, object]) -> SourceTextPacket:
    locator_payload = payload.get("locator")
    if not isinstance(locator_payload, dict):
        raise ValueError("source packet locator must be an object")
    return SourceTextPacket(
        packet_id=str(payload.get("packet_id", "")).strip(),
        source_id=str(payload.get("source_id", "")).strip(),
        locator=locator_from_payload(locator_payload),
        text=str(payload.get("text", "")),
        pdf_page_start=_optional_payload_int(payload.get("pdf_page_start")),
        pdf_page_end=_optional_payload_int(payload.get("pdf_page_end")),
        printed_page_start=_optional_context_str(payload.get("printed_page_start")),
        printed_page_end=_optional_context_str(payload.get("printed_page_end")),
        heading_path=_string_list(payload.get("heading_path")),
        extraction_method=str(payload.get("extraction_method", "unknown")),
        text_quality=str(payload.get("text_quality", "unknown")),
        warnings=_string_list(payload.get("warnings")),
    )


def _optional_payload_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("expected integer or null")
    return int(value)


def _research_notes_delegation(*, total_packet_chars: int) -> DelegationHint:
    recommended = total_packet_chars > 20_000
    reason = (
        "source packet bundle text exceeds 20000 chars; use a bounded research-notes subagent"
        if recommended
        else "research note extraction fits in the main orchestrator context"
    )
    return DelegationHint(
        recommended=recommended,
        reason=reason,
        suggested_role="research_notes_extractor" if recommended else None,
        allowed_tools=["submit_work_result"],
        return_contract=(
            "Return one JSON object matching response_schema. Do not commit it; "
            "the orchestrator will submit and commit the result."
        ),
        subagent_prompt=(
            "Extract grounded research notes from the supplied WorkPacket. Use only the "
            "provided source packets, keep quotes exact, and return JSON matching response_schema."
        )
        if recommended
        else None,
    )


def _latest_source_packet_bundle_id_for_stage(
    work_store: AgentWorkStore,
    *,
    scope: str,
    stage: str,
) -> str | None:
    for commit in reversed(work_store.list_commits(scope=scope, stage=stage)):
        bundle_id = commit.artifact_refs.get("source_packet_bundle_id")
        if isinstance(bundle_id, str) and bundle_id:
            return bundle_id
    return None


def _latest_validation_version(stores: AgentStoreBundle, job_id: str) -> int:
    version = stores.validation_store.next_version(job_id) - 1
    if version < 1:
        raise KeyError(f"{job_id} validation")
    return version


def _load_draft_for_job(
    stores: AgentStoreBundle,
    *,
    job_id: str,
    draft_id: str | None,
) -> object:
    if draft_id is not None:
        return stores.draft_store.find_by_id(job_id, draft_id)
    return stores.draft_store.load_latest(job_id)


def _deterministic_from_payload(payload: dict[str, object]) -> DeterministicCheckResult:
    tier1 = [
        VocabHit(word=str(item.get("word", "")), count=int(item.get("count", 0)))
        for item in payload.get("tier1_vocab_hits", [])
        if isinstance(item, dict)
    ]
    sentence_runs = [
        SentenceRun(
            sentence_count=int(item.get("sentence_count", 0)),
            avg_word_count=float(item.get("avg_word_count", 0.0)),
        )
        for item in payload.get("consecutive_similar_sentence_runs", [])
        if isinstance(item, dict)
    ]
    paragraph_profile_payload = payload.get("paragraph_length_profile")
    paragraph_profile = (
        ParagraphLengthProfile(
            paragraph_count=int(paragraph_profile_payload.get("paragraph_count", 0)),
            shortest_word_count=int(paragraph_profile_payload.get("shortest_word_count", 0)),
            longest_word_count=int(paragraph_profile_payload.get("longest_word_count", 0)),
            longest_to_shortest_ratio=float(
                paragraph_profile_payload.get("longest_to_shortest_ratio", 0.0)
            ),
        )
        if isinstance(paragraph_profile_payload, dict)
        else None
    )
    return DeterministicCheckResult(
        word_count=int(payload.get("word_count", 0)),
        em_dash_count=int(payload.get("em_dash_count", 0)),
        tier1_vocab_hits=tier1,
        bad_conclusion_opener=bool(payload.get("bad_conclusion_opener", False)),
        consecutive_similar_sentence_runs=sentence_runs,
        participial_phrase_count=int(payload.get("participial_phrase_count", 0)),
        participial_phrase_rate=float(payload.get("participial_phrase_rate", 0.0)),
        contrastive_negation_count=int(payload.get("contrastive_negation_count", 0)),
        signposting_hits=_string_list(payload.get("signposting_hits")),
        en_dash_count=int(payload.get("en_dash_count", 0)),
        decorative_hyphen_pause_count=int(payload.get("decorative_hyphen_pause_count", 0)),
        colon_explanation_pattern_count=int(payload.get("colon_explanation_pattern_count", 0)),
        triplet_contrastive_combo_count=int(payload.get("triplet_contrastive_combo_count", 0)),
        clustered_triplet_count=int(payload.get("clustered_triplet_count", 0)),
        paragraph_length_profile=paragraph_profile,
        paragraph_length_variance_warning=bool(
            payload.get("paragraph_length_variance_warning", False)
        ),
        mechanical_burstiness_count=int(payload.get("mechanical_burstiness_count", 0)),
        concrete_engagement_present=bool(payload.get("concrete_engagement_present", False)),
    )


def _metadata_warnings_from_payload(value: object) -> list[CitationMetadataWarning]:
    if not isinstance(value, list):
        raise ValueError("metadata_citation_warnings must be a list")
    warnings: list[CitationMetadataWarning] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("metadata_citation_warnings entries must be objects")
        warnings.append(
            CitationMetadataWarning(
                source_id=str(item.get("source_id", "")),
                description=str(item.get("description", "")),
                severity=str(item.get("severity", "medium")),
            )
        )
    return warnings


def _validate_draft_note_refs(
    payload: dict[str, object],
    evidence_map: object,
    *,
    tool_name: str,
) -> ToolResult | None:
    valid_note_ids = {getattr(note, "id") for note in getattr(evidence_map, "notes", [])}
    unknown: list[str] = []
    section_source_map = payload.get("section_source_map", [])
    if not isinstance(section_source_map, list):
        return _error_result(
            tool_name,
            code="draft_section_source_map_invalid",
            message="section_source_map must be a list",
            exc=ValueError("section_source_map"),
        )
    for item in section_source_map:
        if not isinstance(item, dict):
            return _error_result(
                tool_name,
                code="draft_section_source_map_invalid",
                message="section_source_map entries must be objects",
                exc=ValueError("section_source_map"),
            )
        for note_id in _string_list(item.get("note_ids")):
            if note_id not in valid_note_ids and note_id not in unknown:
                unknown.append(note_id)
    if unknown:
        return _error_result_with_next(
            tool_name,
            code="draft_unknown_note_ids",
            message=f"draft references unknown note_ids: {', '.join(unknown)}",
            exc=ValueError("note_ids"),
            next_suggested_tools=["prepare_draft"],
        )
    return None


def _trim_source_packet(packet: SourceTextPacket, *, max_chars: int) -> SourceTextPacket:
    if len(packet.text) <= max_chars:
        return packet
    return replace(
        packet,
        text=packet.text[:max_chars].rstrip(),
        warnings=[*packet.warnings, f"Packet text was truncated to {max_chars} characters."],
    )


def _aggregate_packet_warnings(packets: list[SourceTextPacket]) -> list[str]:
    warnings: list[str] = []
    for packet in packets:
        for warning in packet.warnings:
            if warning not in warnings:
                warnings.append(warning)
    return warnings


def _load_research_plan_for_job(
    store: object,
    *,
    job_id: str,
    research_plan_id: str,
) -> object:
    latest = store.load_latest(job_id)
    if getattr(latest, "id") == research_plan_id:
        return latest
    prefix = "research_plan_v"
    if research_plan_id.startswith(prefix) and research_plan_id.removeprefix(prefix).isdigit():
        version = int(research_plan_id.removeprefix(prefix))
        plan = store.load(job_id, version)
        if getattr(plan, "id") == research_plan_id:
            return plan
    raise KeyError(research_plan_id)


def _pending_source_card_packet_count(
    work_store: AgentWorkStore,
    run: AgentRun | None,
) -> int:
    if run is None:
        return 0
    count = 0
    for packet_id in run.pending_work_packet_ids:
        try:
            packet = work_store.load_packet(packet_id)
        except FileNotFoundError:
            continue
        if packet.stage == "source_card":
            count += 1
    return count


def _adversarial_flags_from_context(context: dict[str, object]) -> list[AdversarialFlag]:
    flags = context.get("deterministic_flags", [])
    if not isinstance(flags, list):
        raise ValueError("deterministic_flags must be a list")
    restored: list[AdversarialFlag] = []
    for item in flags:
        if not isinstance(item, dict):
            raise ValueError("deterministic_flags entries must be objects")
        restored.append(AdversarialFlag(**item))
    return restored


def _optional_context_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _task_spec_artifact_refs(task_spec: object) -> dict[str, object]:
    payload = asdict(task_spec)
    refs: dict[str, object] = {
        "task_spec_id": payload["id"],
        "task_spec_version": payload["version"],
        "source_document_ids": list(payload["source_document_ids"]),
    }
    selected_prompt = payload.get("selected_prompt")
    if selected_prompt is not None:
        refs["selected_prompt"] = selected_prompt
    return refs


def _task_spec_stable_payload(task_spec: object) -> dict[str, object]:
    payload = asdict(task_spec)
    payload.pop("created_at", None)
    return payload


def _source_card_delegation(
    *,
    source_id: str,
    selected_excerpt_chars: int,
    pending_source_card_packets: int,
) -> DelegationHint:
    reasons = ["source-card generation is source-scoped and subagent-friendly"]
    if selected_excerpt_chars > 8_000:
        reasons.append("selected excerpts exceed 8000 characters")
    if pending_source_card_packets > 0:
        reasons.append("multiple pending source-card packets are active in this run")
    return DelegationHint(
        recommended=True,
        reason="; ".join(reasons),
        suggested_role="source_card_writer",
        allowed_tools=["submit_work_result"],
        return_contract=(
            "Return one JSON object matching response_schema. Do not commit it; "
            "the orchestrator will submit and commit the result."
        ),
        subagent_prompt=(
            f"Generate a source card for source {source_id} from the supplied WorkPacket. "
            "Use only packet excerpts and return JSON matching response_schema with keys: "
            "title, brief_summary, key_topics, useful_for_topic_ideation, notable_sections, "
            "limitations, citation_metadata, warnings."
        ),
    )


def _validate_work_payload(
    payload: dict[str, object],
    schema: dict[str, object],
    *,
    tool_name: str,
) -> ToolResult | None:
    try:
        import jsonschema  # type: ignore[import-not-found]
    except ImportError:
        fallback_error = _validate_with_local_schema_subset(payload, schema, path="$")
        if fallback_error is None:
            return None
        code, message = fallback_error
        return _error_result(
            tool_name,
            code=code,
            message=message,
            exc=ValueError(message),
        )

    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        return _error_result(
            tool_name,
            code="work_result_payload_invalid",
            message=f"work result payload does not match response_schema: {exc.message}",
            exc=exc,
        )
    except jsonschema.SchemaError as exc:
        return _error_result(
            tool_name,
            code="work_result_schema_invalid",
            message=f"work packet response_schema is invalid: {exc.message}",
            exc=exc,
        )
    return None


def _validate_with_local_schema_subset(
    value: object,
    schema: dict[str, object],
    *,
    path: str,
) -> tuple[str, str] | None:
    supported = {"type", "required", "properties", "additionalProperties", "items", "enum"}
    unsupported = sorted(set(schema) - supported)
    if unsupported:
        return (
            "work_result_schema_validator_unavailable",
            "response_schema uses unsupported keywords without jsonschema installed; "
            "install `.[agent-tools]` to validate this packet",
        )
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        type_names = [item for item in schema_type if isinstance(item, str)]
        if len(type_names) != len(schema_type):
            return _unsupported_schema_subset()
        if value is None and "null" in type_names:
            return None
        validation_errors: list[tuple[str, str]] = []
        for type_name in [item for item in type_names if item != "null"]:
            narrowed = dict(schema)
            narrowed["type"] = type_name
            error = _validate_with_local_schema_subset(value, narrowed, path=path)
            if error is None:
                return None
            validation_errors.append(error)
        if any(code == "work_result_schema_validator_unavailable" for code, _ in validation_errors):
            return _unsupported_schema_subset()
        return (
            "work_result_payload_invalid",
            f"{path} must match one of: {', '.join(type_names)}",
        )
    if schema_type == "object":
        if not isinstance(value, dict):
            return ("work_result_payload_invalid", f"{path} must be an object")
        required = schema.get("required", [])
        if not isinstance(required, list):
            return _unsupported_schema_subset()
        missing = [str(key) for key in required if str(key) not in value]
        if missing:
            return (
                "work_result_payload_invalid",
                f"{path} is missing required fields: {', '.join(missing)}",
            )
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return _unsupported_schema_subset()
        additional = schema.get("additionalProperties", True)
        if not isinstance(additional, (bool, dict)):
            return _unsupported_schema_subset()
        property_names = {str(key) for key in properties}
        extra = sorted(str(key) for key in value if str(key) not in property_names)
        if additional is False and extra:
            return (
                "work_result_payload_invalid",
                f"{path} has unsupported additional fields: {', '.join(extra)}",
            )
        for key, item in value.items():
            key_str = str(key)
            if key_str in properties:
                subschema = properties[key_str]
                if not isinstance(subschema, dict):
                    return _unsupported_schema_subset()
                error = _validate_with_local_schema_subset(
                    item,
                    subschema,
                    path=f"{path}.{key_str}",
                )
                if error is not None:
                    return error
            elif isinstance(additional, dict):
                error = _validate_with_local_schema_subset(
                    item,
                    additional,
                    path=f"{path}.{key_str}",
                )
                if error is not None:
                    return error
        return None
    if schema_type == "string":
        if not isinstance(value, str):
            return ("work_result_payload_invalid", f"{path} must be a string")
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            allowed = ", ".join(str(item) for item in enum_values)
            return ("work_result_payload_invalid", f"{path} must be one of: {allowed}")
        return None
    if schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return ("work_result_payload_invalid", f"{path} must be an integer")
        return None
    if schema_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return ("work_result_payload_invalid", f"{path} must be a number")
        return None
    if schema_type == "boolean":
        if not isinstance(value, bool):
            return ("work_result_payload_invalid", f"{path} must be a boolean")
        return None
    if schema_type == "null":
        if value is not None:
            return ("work_result_payload_invalid", f"{path} must be null")
        return None
    if schema_type == "array":
        if not isinstance(value, list):
            return ("work_result_payload_invalid", f"{path} must be an array")
        items = schema.get("items", {})
        if not isinstance(items, dict):
            return _unsupported_schema_subset()
        for idx, item in enumerate(value):
            error = _validate_with_local_schema_subset(item, items, path=f"{path}[{idx}]")
            if error is not None:
                return error
        return None
    return _unsupported_schema_subset()


def _unsupported_schema_subset() -> tuple[str, str]:
    return (
        "work_result_schema_validator_unavailable",
        "response_schema uses unsupported validation keywords without jsonschema installed; "
        "install `.[agent-tools]` to validate this packet",
    )


def _merge_recovery_refs(
    artifact_refs: dict[str, object],
    existing_refs: dict[str, object],
) -> dict[str, object]:
    merged = dict(artifact_refs)
    source_id = artifact_refs.get("source_id")
    source_card_id = artifact_refs.get("source_card_id")
    if isinstance(source_id, str):
        merged["source_ids"] = _append_unique_ref(existing_refs.get("source_ids"), source_id)
    if isinstance(source_card_id, str):
        merged["source_card_ids"] = _append_unique_ref(
            existing_refs.get("source_card_ids"),
            source_card_id,
        )
    return merged


def _append_unique_ref(existing: object, value: str) -> list[str]:
    refs = [str(item) for item in existing] if isinstance(existing, list) else []
    if value not in refs:
        refs.append(value)
    return refs


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


def _recovered_artifact_refs(recovery: object) -> dict[str, object]:
    latest_checkpoint = getattr(recovery, "latest_checkpoint")
    run = getattr(recovery, "run")
    if latest_checkpoint is not None and latest_checkpoint.created_at >= run.updated_at:
        return dict(latest_checkpoint.artifact_refs)
    return dict(run.artifact_refs)


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


def _error_result_with_next(
    tool_name: str,
    *,
    code: str,
    message: str,
    exc: Exception,
    next_suggested_tools: list[str],
) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=tool_name,
        error=ToolError(
            code=code,
            message=message,
            detail={"exception": type(exc).__name__},
        ),
        next_suggested_tools=list(next_suggested_tools),
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


def _job_summary(job: object) -> dict[str, object]:
    return {
        "id": getattr(job, "id"),
        "status": getattr(job, "status"),
        "current_stage": getattr(job, "current_stage"),
        "task_spec_id": getattr(job, "task_spec_id"),
        "source_ids": list(getattr(job, "source_ids")),
        "selected_topic_id": getattr(job, "selected_topic_id"),
        "draft_id": getattr(job, "draft_id"),
    }


def _job_next_tools(status: str, current_stage: str) -> list[str]:
    if status in {"blocked", "error"}:
        return []
    if status == "created":
        return ["prepare_task_spec", "ingest_source_file"]
    if status == "task_spec_ready" or current_stage == "source_ingestion":
        return ["ingest_source_file", "prepare_source_card"]
    if status == "sources_ready" or current_stage == "topic_ideation":
        return ["prepare_topics"]
    if status == "topic_selection_ready":
        return ["select_topic", "reject_topic"]
    if current_stage == "research":
        return ["resolve_source_requests", "prepare_research_notes"]
    if status == "research_planning_ready":
        return ["create_research_plan"]
    if status == "drafting_ready":
        return ["prepare_outline", "prepare_draft"]
    if status == "validation_ready":
        return ["prepare_validation"]
    if status == "validation_complete":
        return ["export_markdown"]
    return []


def _source_summary(store: object, source: object) -> dict[str, object]:
    source_id = str(getattr(source, "id"))
    return {
        "source_id": source_id,
        "file_name": getattr(source, "file_name"),
        "type": getattr(source, "source_type"),
        "page_count": getattr(source, "page_count"),
        "char_count": getattr(source, "char_count"),
        "full_text_available": getattr(source, "full_text_available"),
        "indexed": getattr(source, "indexed"),
        "source_card_status": "committed" if store.has_source_card(source_id) else "pending",
    }


def _work_packet_summary(packet: WorkPacket) -> dict[str, object]:
    return {
        "work_packet_id": packet.work_packet_id,
        "stage": packet.stage,
        "scope": packet.scope,
        "status": packet.status,
        "commit_tool": packet.commit_tool,
        "artifact_refs": dict(packet.artifact_refs),
        "created_at": packet.created_at,
        "warnings": list(packet.warnings),
    }


def _work_result_summary(result: object) -> dict[str, object]:
    return {
        "work_result_id": getattr(result, "work_result_id"),
        "work_packet_id": getattr(result, "work_packet_id"),
        "status": getattr(result, "status"),
        "payload_hash": getattr(result, "payload_hash"),
        "producer": asdict(getattr(result, "producer")),
        "created_at": getattr(result, "created_at"),
        "warnings": list(getattr(result, "warnings")),
    }
