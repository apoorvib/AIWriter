"""Writing-specific prepare/submit/commit tool facade.

Mirrors the essay ``AgentToolFacade`` prepare/submit/commit shape but drives the
generic ``essay_writer.writing`` domain: it owns its own ``WritingStores`` and a
scoped ``AgentWorkStore`` (``writing:{run_id}``), reuses the shared work-payload
validator and proof-of-attention challenge, and never performs network calls.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from essay_writer.agent_tools.attention import (
    attention_challenge_satisfied,
    build_attention_challenge,
)
from essay_writer.agent_tools.id_utils import content_hash, short_hash, timestamp_id
from essay_writer.agent_tools.schema_validation import (
    error_result,
    error_result_with_next,
    validate_work_payload,
)
from essay_writer.agent_tools.schemas import (
    DelegationHint,
    PromptBlock,
    ToolResult,
    WorkPacket,
    WorkProducer,
)
from essay_writer.agent_tools.subagent_tokens import SubagentTokenStore
from essay_writer.agent_tools.work_store import AgentWorkStore
from essay_writer.writing.context import (
    UnsupportedWritingContextError,
    WritingContextLimitError,
    WritingContextService,
)
from essay_writer.writing.progress import MAX_REVISION_ROUNDS, build_writing_progress
from essay_writer.writing.prompts import (
    WRITING_BRIEF_SCHEMA,
    WRITING_BRIEF_SYSTEM_PROMPT,
    WRITING_DRAFT_SCHEMA,
    WRITING_DRAFT_SYSTEM_PROMPT,
    WRITING_PLAN_SCHEMA,
    WRITING_PLAN_SYSTEM_PROMPT,
    WRITING_RESEARCH_SCHEMA,
    WRITING_RESEARCH_SYSTEM_PROMPT,
    WRITING_REVIEW_SCHEMA,
    WRITING_REVIEW_SYSTEM_PROMPT,
    build_brief_user_message,
    build_draft_user_message,
    build_plan_user_message,
    build_research_user_message,
    build_review_user_message,
)
from essay_writer.writing.schema import (
    DeliverableSpec,
    ResearchFact,
    ResearchPolicy,
    ResearchSource,
    ReviewIssue,
    SkillSelection,
    WriteMode,
    WritingBrief,
    WritingDraft,
    WritingOutput,
    WritingPlan,
    WritingResearch,
    WritingReview,
    WritingRun,
    utc_now_iso,
)
from essay_writer.writing.skills import (
    UnknownWritingSkillError,
    WritingSkillRegistry,
    compose_skill_prompt,
    resolve_skill_stack,
)
from essay_writer.writing.storage import WritingStores

_MODES = {"immediate": WriteMode.IMMEDIATE, "detailed": WriteMode.DETAILED}
_POLICIES = {
    "auto": ResearchPolicy.AUTO,
    "required": ResearchPolicy.REQUIRED,
    "off": ResearchPolicy.OFF,
}


def _coerce_producer(producer: WorkProducer | dict | None) -> WorkProducer:
    if producer is None:
        return WorkProducer(type="main_agent")
    if isinstance(producer, WorkProducer):
        return producer
    return WorkProducer.from_dict(producer)


@dataclass
class WritingToolFacade:
    stores: WritingStores
    work_store: AgentWorkStore
    registry: WritingSkillRegistry
    context_service: WritingContextService
    subagent_token_store: SubagentTokenStore
    enforce_attention_challenge: bool = True

    @classmethod
    def from_data_dir(
        cls,
        data_dir: str | Path,
        *,
        document_reader: object | None = None,
        enforce_attention_challenge: bool = True,
    ) -> "WritingToolFacade":
        stores = WritingStores.from_data_dir(data_dir)
        work_store = AgentWorkStore(stores.root / "agent_work")
        registry = WritingSkillRegistry.default()
        context_service = WritingContextService(
            stores.context, document_reader=document_reader
        )
        return cls(
            stores=stores,
            work_store=work_store,
            registry=registry,
            context_service=context_service,
            subagent_token_store=SubagentTokenStore(stores.root / "subagent_tokens"),
            enforce_attention_challenge=enforce_attention_challenge,
        )

    # -- run lifecycle -------------------------------------------------

    def start_writing_run(
        self,
        raw_request: str,
        *,
        mode: str | None = None,
        research_policy: str = "auto",
        include_skill_ids: list[str] | None = None,
        exclude_skill_ids: list[str] | None = None,
    ) -> ToolResult:
        if not raw_request or not raw_request.strip():
            return error_result(
                "start_writing_run",
                code="raw_request_required",
                message="start_writing_run requires a non-empty raw_request.",
                exc=ValueError("raw_request"),
            )
        if mode is not None and mode not in _MODES:
            return error_result(
                "start_writing_run",
                code="invalid_mode",
                message="mode must be 'immediate', 'detailed', or omitted.",
                exc=ValueError(mode),
            )
        if research_policy not in _POLICIES:
            return error_result(
                "start_writing_run",
                code="invalid_research_policy",
                message="research_policy must be 'auto', 'required', or 'off'.",
                exc=ValueError(research_policy),
            )
        include = list(include_skill_ids or [])
        exclude = list(exclude_skill_ids or [])
        try:
            for skill_id in [*include, *exclude]:
                self.registry.get(skill_id)
        except UnknownWritingSkillError as exc:
            return error_result_with_next(
                "start_writing_run",
                code="unknown_writing_skill",
                message=str(exc),
                exc=exc,
                next_suggested_tools=["start_writing_run"],
            )

        run_id = timestamp_id("wrun", short_hash(raw_request))
        run = WritingRun(
            writing_run_id=run_id,
            raw_request=raw_request,
            mode_hint=_MODES.get(mode) if mode is not None else None,
            research_policy=_POLICIES[research_policy],
            include_skill_ids=include,
            exclude_skill_ids=exclude,
        )
        self.stores.runs.create(run)
        return self._run_result("start_writing_run", run, ["prepare_writing_brief"])

    def recover_writing_run(self, writing_run_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("recover_writing_run", writing_run_id)
        ledger = build_writing_progress(run, self.stores)
        return ToolResult(
            ok=True,
            tool_name="recover_writing_run",
            data={
                "writing_run_id": run.writing_run_id,
                "run": asdict(run),
                "progress": ledger,
                "resume_instructions": (
                    "The persisted writing run is authoritative. Act on "
                    "progress.next_action; if requires_human is true, return the "
                    "questions and the writing_run_id and stop."
                ),
            },
            next_suggested_tools=[ledger["next_action"].get("tool")]
            if ledger["next_action"].get("tool")
            else [],
        )

    def get_writing_progress(self, writing_run_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("get_writing_progress", writing_run_id)
        ledger = build_writing_progress(run, self.stores)
        return ToolResult(
            ok=True,
            tool_name="get_writing_progress",
            data={"writing_run_id": run.writing_run_id, "progress": ledger},
        )

    def list_writing_runs(self, *, status: str | None = None, limit: int = 20) -> ToolResult:
        runs = self.stores.runs.list()
        if status is not None:
            runs = [run for run in runs if run.status == status]
        runs = runs[: max(0, int(limit))]
        return ToolResult(
            ok=True,
            tool_name="list_writing_runs",
            data={
                "runs": [
                    {
                        "writing_run_id": run.writing_run_id,
                        "status": run.status,
                        "raw_request": run.raw_request,
                        "output_id": run.output_id,
                        "created_at": run.created_at,
                        "updated_at": run.updated_at,
                    }
                    for run in runs
                ],
                "count": len(runs),
            },
        )

    def get_writing_output(self, writing_run_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("get_writing_output", writing_run_id)
        if not self._output_exists(writing_run_id):
            return error_result_with_next(
                "get_writing_output",
                code="writing_output_not_found",
                message=(
                    "this run has not been finalized; no output exists yet."
                ),
                exc=KeyError(writing_run_id),
                next_suggested_tools=["get_writing_progress"],
            )
        return self._finalized_result(writing_run_id, True)

    def ingest_writing_context(
        self,
        writing_run_id: str,
        *,
        text: str | None = None,
        document_path: str | None = None,
        label: str,
    ) -> ToolResult:
        """Attach untrusted reference content (inline text or a file) to a run.

        Exactly one of ``text`` or ``document_path`` must be supplied. The content
        is stored immutably and surfaced to later stages as ``context`` — it is
        never treated as tool instructions.
        """
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("ingest_writing_context", writing_run_id)
        if bool(text) == bool(document_path):
            return error_result(
                "ingest_writing_context",
                code="context_source_ambiguous",
                message="supply exactly one of text or document_path.",
                exc=ValueError("text/document_path"),
            )
        if not label or not str(label).strip():
            return error_result(
                "ingest_writing_context",
                code="label_required",
                message="ingest_writing_context requires a non-empty label.",
                exc=ValueError("label"),
            )
        try:
            if text is not None:
                item = self.context_service.add_inline(
                    run.writing_run_id, str(text), label=str(label)
                )
            else:
                item = self.context_service.add_file(
                    run.writing_run_id, str(document_path), label=str(label)
                )
        except FileNotFoundError as exc:
            return error_result(
                "ingest_writing_context",
                code="context_file_not_found",
                message=f"context file not found: {document_path}",
                exc=exc,
            )
        except (WritingContextLimitError, UnsupportedWritingContextError) as exc:
            return error_result(
                "ingest_writing_context",
                code="context_rejected",
                message=str(exc),
                exc=exc,
            )
        context_ids = list(run.context_ids)
        if item.context_id not in context_ids:
            context_ids.append(item.context_id)
            self.stores.runs.update(replace(run, context_ids=context_ids))
        return ToolResult(
            ok=True,
            tool_name="ingest_writing_context",
            data={
                "writing_run_id": run.writing_run_id,
                "context_id": item.context_id,
                "label": item.label,
                "kind": item.kind,
                "char_count": item.char_count,
            },
        )

    # -- brief ---------------------------------------------------------

    def prepare_writing_brief(self, writing_run_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("prepare_writing_brief", writing_run_id)

        context_items = self._context_payload(run.writing_run_id)
        user_message = build_brief_user_message(
            raw_request=run.raw_request,
            available_skills=self.registry.catalog(),
            mode_hint=run.mode_hint.value if run.mode_hint else None,
            research_policy=run.research_policy.value,
            include_skill_ids=run.include_skill_ids,
            exclude_skill_ids=run.exclude_skill_ids,
            context=context_items,
        )
        packet_id = timestamp_id(
            "wpkt", run.writing_run_id, "brief", short_hash(user_message)
        )
        packet = self._save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="writing_brief",
                scope=f"writing:{run.writing_run_id}",
                instructions=(
                    "Route this request into a writing brief. Return JSON matching "
                    "response_schema; do not commit it. Choose skill IDs only from "
                    "available_skills and respect the explicit_overrides."
                ),
                system_prompt=WRITING_BRIEF_SYSTEM_PROMPT,
                prompt_blocks=[
                    PromptBlock(
                        text=json.dumps(user_message, ensure_ascii=False),
                        cacheable=False,
                    )
                ],
                response_schema=dict(WRITING_BRIEF_SCHEMA),
                context={"writing_run_id": run.writing_run_id},
                artifact_refs={"writing_run_id": run.writing_run_id},
                commit_tool="commit_writing_brief",
                delegation=DelegationHint(
                    recommended=False,
                    allowed_tools=["submit_writing_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not "
                        "commit it; submit it with submit_writing_result."
                    ),
                ),
            )
        )
        return ToolResult(
            ok=True,
            tool_name="prepare_writing_brief",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "writing_run_id": run.writing_run_id,
                "commit_tool": packet.commit_tool,
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt": user_message,
                "instructions": packet.instructions,
                "delegation": asdict(packet.delegation),
                "next_suggested_tools": ["submit_writing_result"],
            },
            next_suggested_tools=["submit_writing_result"],
        )

    def submit_writing_result(
        self,
        work_packet_id: str,
        payload: dict[str, object],
        *,
        producer: WorkProducer | dict | None = None,
    ) -> ToolResult:
        try:
            packet = self.work_store.load_packet(work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return error_result(
                "submit_writing_result",
                code="work_packet_not_found",
                message=f"WorkPacket not found: {work_packet_id}",
                exc=exc,
            )
        producer_obj = _coerce_producer(producer)
        delegation_error = self._enforce_delegation(work_packet_id, packet, producer_obj, payload)
        if delegation_error is not None:
            return delegation_error
        validation_error = validate_work_payload(
            payload, packet.response_schema, tool_name="submit_writing_result"
        )
        if validation_error is not None:
            return validation_error
        challenge = packet.system_prompt_challenge
        if challenge and not attention_challenge_satisfied(payload, challenge):
            return error_result_with_next(
                "submit_writing_result",
                code="system_prompt_not_honored",
                message=(
                    "The required attention token from the packet's system_prompt "
                    "is missing from your output. Re-read the packet's system_prompt "
                    "and include the exact token (see the 'ATTENTION CHECK' line) in "
                    "a free-text field of your JSON."
                ),
                exc=ValueError("system_prompt_challenge"),
                next_suggested_tools=["get_work_packet"],
            )
        existing_ids = {result.work_result_id for result in self.work_store.list_results()}
        result = self.work_store.submit_result(
            work_packet_id, payload=payload, producer=producer_obj
        )
        duplicate = result.work_result_id in existing_ids
        if packet.delegation_required and producer_obj.subagent_token:
            self.subagent_token_store.consume(
                token=producer_obj.subagent_token, work_packet_id=packet.work_packet_id
            )
        next_tools = [packet.commit_tool] if packet.commit_tool else []
        return ToolResult(
            ok=True,
            tool_name="submit_writing_result",
            data={
                "work_result_id": result.work_result_id,
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "commit_tool": packet.commit_tool,
                "duplicate": duplicate,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def commit_writing_brief(self, work_result_id: str) -> ToolResult:
        loaded = self._load_result_and_packet("commit_writing_brief", work_result_id)
        if isinstance(loaded, ToolResult):
            return loaded
        result, packet = loaded
        if packet.stage != "writing_brief":
            return error_result(
                "commit_writing_brief",
                code="wrong_work_packet_stage",
                message=f"expected writing_brief packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )
        run_id = str(packet.artifact_refs.get("writing_run_id", ""))
        run = self._load_run(run_id)
        if run is None:
            return self._run_not_found("commit_writing_brief", run_id)

        payload = result.payload
        top_selected = [str(item) for item in payload.get("selected_skill_ids", [])]
        try:
            deliverables, brief_skills = self._resolve_deliverables(
                run, payload.get("deliverables", []), top_selected
            )
        except UnknownWritingSkillError as exc:
            return error_result_with_next(
                "commit_writing_brief",
                code="unknown_writing_skill",
                message=str(exc),
                exc=exc,
                next_suggested_tools=["prepare_writing_brief"],
            )

        mode = run.mode_hint or WriteMode(str(payload["mode"]))
        research_needed = self._effective_research_needed(
            run, bool(payload.get("research_needed", False))
        )
        blocking = [str(item) for item in payload.get("blocking_questions", [])]
        version = self.stores.briefs.next_version(run_id)
        brief = WritingBrief(
            brief_id=f"{run_id}-brief-v{version}",
            writing_run_id=run_id,
            version=version,
            mode=mode,
            purpose=str(payload["purpose"]),
            audience=str(payload["audience"]),
            deliverables=deliverables,
            selected_skills=brief_skills,
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            blocking_questions=blocking,
            research_needed=research_needed,
            research_reasons=[str(item) for item in payload.get("research_reasons", [])],
        )
        self.stores.briefs.save(brief)
        self.stores.runs.update(
            replace(
                run,
                brief_id=brief.brief_id,
                status="needs_input" if blocking else "active",
                blocked_on=["brief"] if blocking else [],
            )
        )
        self.work_store.save_commit(
            scope=packet.scope,
            stage="writing_brief",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs={
                "writing_run_id": run_id,
                "brief_id": brief.brief_id,
                "version": version,
            },
        )
        ledger = build_writing_progress(self.stores.runs.load(run_id), self.stores)
        return ToolResult(
            ok=True,
            tool_name="commit_writing_brief",
            data={
                "writing_run_id": run_id,
                "brief_id": brief.brief_id,
                "version": version,
                "mode": brief.mode.value,
                "research_needed": brief.research_needed,
                "blocking_questions": blocking,
                "selected_skills": [asdict(item) for item in brief.selected_skills],
                "progress": ledger,
            },
            next_suggested_tools=[ledger["next_action"].get("tool")]
            if ledger["next_action"].get("tool")
            else [],
        )

    def answer_writing_questions(
        self, writing_run_id: str, answers: str
    ) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("answer_writing_questions", writing_run_id)
        if not answers or not str(answers).strip():
            return error_result(
                "answer_writing_questions",
                code="answers_required",
                message="answer_writing_questions requires non-empty answers.",
                exc=ValueError("answers"),
            )
        item = self.context_service.add_answer(run.writing_run_id, str(answers))
        context_ids = list(run.context_ids)
        if item.context_id not in context_ids:
            context_ids.append(item.context_id)
        updated = self.stores.runs.update(
            replace(run, context_ids=context_ids, status="active", blocked_on=[])
        )
        ledger = build_writing_progress(updated, self.stores)
        return ToolResult(
            ok=True,
            tool_name="answer_writing_questions",
            data={
                "writing_run_id": run.writing_run_id,
                "context_id": item.context_id,
                "progress": ledger,
                "next_suggested_tools": ["prepare_writing_brief"],
            },
            next_suggested_tools=["prepare_writing_brief"],
        )

    # -- research ------------------------------------------------------

    def prepare_writing_research(self, writing_run_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("prepare_writing_research", writing_run_id)
        if run.research_policy == ResearchPolicy.OFF:
            return error_result_with_next(
                "prepare_writing_research",
                code="research_disabled",
                message=(
                    "research_policy is 'off'. Supply any needed facts as context "
                    "or proceed with explicit uncertainty; do not browse the web."
                ),
                exc=ValueError("off"),
                next_suggested_tools=["prepare_writing_draft"],
            )
        brief = self._latest_brief(run.writing_run_id)
        if brief is None:
            return error_result_with_next(
                "prepare_writing_research",
                code="brief_required",
                message="commit a writing brief before preparing research.",
                exc=ValueError("brief"),
                next_suggested_tools=["prepare_writing_brief"],
            )
        if brief.blocking_questions:
            return error_result_with_next(
                "prepare_writing_research",
                code="brief_blocked",
                message="answer the brief's blocking questions before researching.",
                exc=ValueError("blocking_questions"),
                next_suggested_tools=["answer_writing_questions"],
            )

        user_message = build_research_user_message(
            brief, self._context_payload(run.writing_run_id)
        )
        packet_id = timestamp_id(
            "wpkt", run.writing_run_id, "research", short_hash(user_message)
        )
        packet = self._save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="writing_research",
                scope=f"writing:{run.writing_run_id}",
                instructions=(
                    "Use web search to gather bounded, current facts for this brief. "
                    "Return JSON matching response_schema; do not commit it. Every "
                    "fact must map to a disclosed HTTP(S) source with title and dates. "
                    "Do not store full pages; quote at most 25 words from one source."
                ),
                system_prompt=WRITING_RESEARCH_SYSTEM_PROMPT,
                prompt_blocks=[
                    PromptBlock(
                        text=json.dumps(user_message, ensure_ascii=False),
                        cacheable=False,
                    )
                ],
                response_schema=dict(WRITING_RESEARCH_SCHEMA),
                context={"writing_run_id": run.writing_run_id},
                artifact_refs={"writing_run_id": run.writing_run_id},
                commit_tool="commit_writing_research",
                delegation=DelegationHint(
                    recommended=False,
                    allowed_tools=["submit_writing_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema with disclosed "
                        "HTTP(S) sources and bounded facts. Do not commit it."
                    ),
                ),
            )
        )
        return ToolResult(
            ok=True,
            tool_name="prepare_writing_research",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "writing_run_id": run.writing_run_id,
                "commit_tool": packet.commit_tool,
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt": user_message,
                "instructions": packet.instructions,
                "delegation": asdict(packet.delegation),
                "next_suggested_tools": ["submit_writing_result"],
            },
            next_suggested_tools=["submit_writing_result"],
        )

    def commit_writing_research(self, work_result_id: str) -> ToolResult:
        loaded = self._load_result_and_packet("commit_writing_research", work_result_id)
        if isinstance(loaded, ToolResult):
            return loaded
        result, packet = loaded
        if packet.stage != "writing_research":
            return error_result(
                "commit_writing_research",
                code="wrong_work_packet_stage",
                message=f"expected writing_research packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )
        run_id = str(packet.artifact_refs.get("writing_run_id", ""))
        run = self._load_run(run_id)
        if run is None:
            return self._run_not_found("commit_writing_research", run_id)
        if run.research_policy == ResearchPolicy.OFF:
            return error_result(
                "commit_writing_research",
                code="research_disabled",
                message="research_policy is 'off'; this research result cannot be committed.",
                exc=ValueError("off"),
            )

        existing = [
            commit
            for commit in self.work_store.list_commits(
                scope=packet.scope, stage="writing_research"
            )
            if commit.work_result_id == result.work_result_id
        ]
        if existing:
            return self._research_committed_result(run_id, existing[0].artifact_refs, True)

        sources, source_warnings, remap, error = self._build_research_sources(result.payload)
        if error is not None:
            return error
        facts, error = self._build_research_facts(
            result.payload, {source.source_id for source in sources}, remap
        )
        if error is not None:
            return error

        version = self.stores.research.next_version(run_id)
        research = WritingResearch(
            research_id=f"{run_id}-research-v{version}",
            writing_run_id=run_id,
            version=version,
            sources=sources,
            facts=facts,
            conflicts=[str(item) for item in result.payload.get("conflicts", [])],
            warnings=[
                *[str(item) for item in result.payload.get("warnings", [])],
                *source_warnings,
            ],
        )
        self.stores.research.save(research)
        self.stores.runs.update(replace(run, research_id=research.research_id))
        commit = self.work_store.save_commit(
            scope=packet.scope,
            stage="writing_research",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs={
                "writing_run_id": run_id,
                "research_id": research.research_id,
                "version": version,
            },
        )
        return self._research_committed_result(run_id, commit.artifact_refs, False)

    # -- plan ----------------------------------------------------------

    def prepare_writing_plan(self, writing_run_id: str, deliverable_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("prepare_writing_plan", writing_run_id)
        brief = self._latest_brief(run.writing_run_id)
        guard = self._deliverable_guard("prepare_writing_plan", run, brief, deliverable_id)
        if isinstance(guard, ToolResult):
            return guard
        deliverable = guard
        if brief.mode != WriteMode.DETAILED:
            return error_result_with_next(
                "prepare_writing_plan",
                code="plan_not_required",
                message="immediate deliverables do not use a plan; draft directly.",
                exc=ValueError("immediate"),
                next_suggested_tools=["prepare_writing_draft"],
            )

        research = self._research_dict(run.writing_run_id)
        user_message = build_plan_user_message(brief, deliverable, research)
        packet_id = timestamp_id(
            "wpkt", run.writing_run_id, "plan", deliverable_id, short_hash(user_message)
        )
        packet = self._save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="writing_plan",
                scope=f"writing:{run.writing_run_id}",
                instructions=(
                    "Draft a proportional plan for this one detailed deliverable. "
                    "Return JSON matching response_schema; do not commit it. Only cite "
                    "research_fact_ids that appear in the supplied research."
                ),
                system_prompt=WRITING_PLAN_SYSTEM_PROMPT,
                prompt_blocks=[
                    PromptBlock(
                        text=json.dumps(user_message, ensure_ascii=False),
                        cacheable=False,
                    )
                ],
                response_schema=dict(WRITING_PLAN_SCHEMA),
                context={"writing_run_id": run.writing_run_id, "deliverable_id": deliverable_id},
                artifact_refs={
                    "writing_run_id": run.writing_run_id,
                    "deliverable_id": deliverable_id,
                },
                commit_tool="commit_writing_plan",
                delegation=DelegationHint(
                    recommended=False,
                    allowed_tools=["submit_writing_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not commit it."
                    ),
                ),
            )
        )
        return self._prepared_result(
            "prepare_writing_plan", packet, run.writing_run_id, user_message,
            extra={"deliverable_id": deliverable_id},
        )

    def commit_writing_plan(self, work_result_id: str) -> ToolResult:
        loaded = self._load_result_and_packet("commit_writing_plan", work_result_id)
        if isinstance(loaded, ToolResult):
            return loaded
        result, packet = loaded
        if packet.stage != "writing_plan":
            return error_result(
                "commit_writing_plan",
                code="wrong_work_packet_stage",
                message=f"expected writing_plan packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )
        run_id = str(packet.artifact_refs.get("writing_run_id", ""))
        deliverable_id = str(packet.artifact_refs.get("deliverable_id", ""))
        run = self._load_run(run_id)
        if run is None:
            return self._run_not_found("commit_writing_plan", run_id)
        brief = self._latest_brief(run_id)
        guard = self._deliverable_guard("commit_writing_plan", run, brief, deliverable_id)
        if isinstance(guard, ToolResult):
            return guard

        existing = [
            commit
            for commit in self.work_store.list_commits(scope=packet.scope, stage="writing_plan")
            if commit.work_result_id == result.work_result_id
        ]
        if existing:
            return self._plan_committed_result(run_id, deliverable_id, existing[0].artifact_refs, True)

        payload = result.payload
        fact_ids = [str(item) for item in payload.get("research_fact_ids", [])]
        fact_error = self._validate_research_fact_ids("commit_writing_plan", run_id, fact_ids)
        if fact_error is not None:
            return fact_error

        version = self.stores.plans.next_version(run_id, deliverable_id)
        plan = WritingPlan(
            plan_id=f"{run_id}-{deliverable_id}-plan-v{version}",
            writing_run_id=run_id,
            deliverable_id=deliverable_id,
            version=version,
            sections=[str(item) for item in payload.get("sections", [])],
            key_points=[str(item) for item in payload.get("key_points", [])],
            research_fact_ids=fact_ids,
        )
        self.stores.plans.save(plan)
        commit = self.work_store.save_commit(
            scope=packet.scope,
            stage="writing_plan",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs={
                "writing_run_id": run_id,
                "deliverable_id": deliverable_id,
                "plan_id": plan.plan_id,
                "version": version,
            },
        )
        return self._plan_committed_result(run_id, deliverable_id, commit.artifact_refs, False)

    # -- draft ---------------------------------------------------------

    def prepare_writing_draft(self, writing_run_id: str, deliverable_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("prepare_writing_draft", writing_run_id)
        brief = self._latest_brief(run.writing_run_id)
        guard = self._deliverable_guard("prepare_writing_draft", run, brief, deliverable_id)
        if isinstance(guard, ToolResult):
            return guard
        deliverable = guard
        if brief.mode == WriteMode.DETAILED and not self.stores.plans.versions(
            run.writing_run_id, deliverable_id
        ):
            return error_result_with_next(
                "prepare_writing_draft",
                code="plan_required",
                message="detailed deliverables need a committed plan before drafting.",
                exc=ValueError("plan"),
                next_suggested_tools=["prepare_writing_plan"],
            )

        selections = self._deliverable_selections(brief, deliverable)
        skill_prompt = compose_skill_prompt(self.registry, selections)
        user_message = build_draft_user_message(
            brief=brief,
            deliverable=deliverable,
            skill_prompt=skill_prompt,
            context=self._context_payload(run.writing_run_id),
            research=self._research_dict(run.writing_run_id),
            plan=self._plan_dict(run.writing_run_id, deliverable_id),
        )
        packet_id = timestamp_id(
            "wpkt", run.writing_run_id, "draft", deliverable_id, short_hash(user_message)
        )
        packet = self._save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="writing_draft",
                scope=f"writing:{run.writing_run_id}",
                instructions=(
                    "Write this one deliverable in full, following the composed skill "
                    "prompt's precedence. Return JSON matching response_schema; do not "
                    "commit it. Record explicit assumptions, cite only supplied "
                    "research_fact_ids, and include a self_check for immediate work."
                ),
                system_prompt=WRITING_DRAFT_SYSTEM_PROMPT,
                prompt_blocks=[
                    PromptBlock(
                        text=json.dumps(user_message, ensure_ascii=False),
                        cacheable=False,
                    )
                ],
                response_schema=dict(WRITING_DRAFT_SCHEMA),
                context={"writing_run_id": run.writing_run_id, "deliverable_id": deliverable_id},
                artifact_refs={
                    "writing_run_id": run.writing_run_id,
                    "deliverable_id": deliverable_id,
                },
                commit_tool="commit_writing_draft",
                delegation=DelegationHint(
                    recommended=False,
                    allowed_tools=["submit_writing_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema with the finished "
                        "prose in content. Do not commit it."
                    ),
                ),
            )
        )
        return self._prepared_result(
            "prepare_writing_draft", packet, run.writing_run_id, user_message,
            extra={"deliverable_id": deliverable_id},
        )

    def commit_writing_draft(self, work_result_id: str) -> ToolResult:
        loaded = self._load_result_and_packet("commit_writing_draft", work_result_id)
        if isinstance(loaded, ToolResult):
            return loaded
        result, packet = loaded
        if packet.stage != "writing_draft":
            return error_result(
                "commit_writing_draft",
                code="wrong_work_packet_stage",
                message=f"expected writing_draft packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )
        run_id = str(packet.artifact_refs.get("writing_run_id", ""))
        deliverable_id = str(packet.artifact_refs.get("deliverable_id", ""))
        run = self._load_run(run_id)
        if run is None:
            return self._run_not_found("commit_writing_draft", run_id)
        brief = self._latest_brief(run_id)
        guard = self._deliverable_guard("commit_writing_draft", run, brief, deliverable_id)
        if isinstance(guard, ToolResult):
            return guard
        deliverable = guard

        existing = [
            commit
            for commit in self.work_store.list_commits(scope=packet.scope, stage="writing_draft")
            if commit.work_result_id == result.work_result_id
        ]
        if existing:
            return self._draft_committed_result(run_id, deliverable_id, existing[0].artifact_refs, True)

        payload = result.payload
        content = str(payload.get("content", ""))
        if not content.strip():
            return error_result(
                "commit_writing_draft",
                code="draft_content_empty",
                message="a committed draft must have non-empty content.",
                exc=ValueError("content"),
            )
        self_check = [str(item) for item in payload.get("self_check", [])]
        if brief.mode == WriteMode.IMMEDIATE and not self_check:
            return error_result_with_next(
                "commit_writing_draft",
                code="self_check_required",
                message=(
                    "immediate deliverables carry their own review; self_check must be "
                    "a non-empty list of the checks you performed."
                ),
                exc=ValueError("self_check"),
                next_suggested_tools=["prepare_writing_draft"],
            )
        fact_ids = [str(item) for item in payload.get("research_fact_ids", [])]
        fact_error = self._validate_research_fact_ids("commit_writing_draft", run_id, fact_ids)
        if fact_error is not None:
            return fact_error

        selections = self._deliverable_selections(brief, deliverable)
        version = self.stores.drafts.next_version(run_id, deliverable_id)
        draft = WritingDraft(
            draft_id=f"{run_id}-{deliverable_id}-draft-v{version}",
            writing_run_id=run_id,
            deliverable_id=deliverable_id,
            version=version,
            content=content,
            selected_skills=selections,
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            research_fact_ids=fact_ids,
            self_check=self_check,
            origin="draft",
        )
        self.stores.drafts.save(draft)
        commit = self.work_store.save_commit(
            scope=packet.scope,
            stage="writing_draft",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs={
                "writing_run_id": run_id,
                "deliverable_id": deliverable_id,
                "draft_id": draft.draft_id,
                "version": version,
            },
        )
        return self._draft_committed_result(run_id, deliverable_id, commit.artifact_refs, False)

    # -- review --------------------------------------------------------

    def prepare_writing_review(self, writing_run_id: str, deliverable_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("prepare_writing_review", writing_run_id)
        brief = self._latest_brief(run.writing_run_id)
        guard = self._deliverable_guard("prepare_writing_review", run, brief, deliverable_id)
        if isinstance(guard, ToolResult):
            return guard
        deliverable = guard
        if brief.mode != WriteMode.DETAILED:
            return error_result_with_next(
                "prepare_writing_review",
                code="review_not_required",
                message="immediate deliverables embed their own self-check; no review packet.",
                exc=ValueError("immediate"),
                next_suggested_tools=["finalize_writing_run"],
            )
        draft = self._load_latest_draft(run.writing_run_id, deliverable_id)
        if draft is None:
            return error_result_with_next(
                "prepare_writing_review",
                code="draft_required",
                message="draft this deliverable before reviewing it.",
                exc=ValueError("draft"),
                next_suggested_tools=["prepare_writing_draft"],
            )

        selections = self._deliverable_selections(brief, deliverable)
        skill_prompt = compose_skill_prompt(self.registry, selections)
        user_message = build_review_user_message(
            draft=asdict(draft), brief=brief, skill_prompt=skill_prompt
        )
        packet_id = timestamp_id(
            "wpkt", run.writing_run_id, "review", deliverable_id, short_hash(user_message)
        )
        packet = self._save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="writing_review",
                scope=f"writing:{run.writing_run_id}",
                instructions=(
                    "Review this exact draft against every selected skill and explicit "
                    "requirement. Return JSON matching response_schema; do not commit it. "
                    "Reserve 'blocker' for unsupported facts, violated explicit "
                    "requirements, wrong format, or unsafe content; style is major/minor."
                ),
                system_prompt=WRITING_REVIEW_SYSTEM_PROMPT,
                prompt_blocks=[
                    PromptBlock(
                        text=json.dumps(user_message, ensure_ascii=False),
                        cacheable=False,
                    )
                ],
                response_schema=dict(WRITING_REVIEW_SCHEMA),
                context={"writing_run_id": run.writing_run_id, "deliverable_id": deliverable_id},
                artifact_refs={
                    "writing_run_id": run.writing_run_id,
                    "deliverable_id": deliverable_id,
                    "draft_id": draft.draft_id,
                    "draft_sha256": draft.content_sha256,
                },
                commit_tool="commit_writing_review",
                delegation_required=True,
                delegation=DelegationHint(
                    recommended=True,
                    reason="A detailed review must run in a clean context, blind to the drafting rationale.",
                    suggested_role="writing-reviewer",
                    allowed_tools=["get_work_packet", "submit_writing_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. Do not commit it; "
                        "submit it with submit_writing_result carrying the dispatch token."
                    ),
                ),
            )
        )
        return self._prepared_result(
            "prepare_writing_review", packet, run.writing_run_id, user_message,
            extra={
                "deliverable_id": deliverable_id,
                "delegation_required": True,
                "next_suggested_tools": ["dispatch_writing_reviewer"],
            },
            next_suggested_tools=["dispatch_writing_reviewer"],
        )

    def dispatch_writing_reviewer(
        self,
        work_packet_id: str,
        *,
        role: str = "writing-reviewer",
        model_tier: str | None = None,
    ) -> ToolResult:
        try:
            packet = self.work_store.load_packet(work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return error_result(
                "dispatch_writing_reviewer",
                code="work_packet_not_found",
                message=f"WorkPacket not found: {work_packet_id}",
                exc=exc,
            )
        if not packet.delegation_required:
            return error_result_with_next(
                "dispatch_writing_reviewer",
                code="delegation_not_applicable",
                message=(
                    f"WorkPacket {work_packet_id!r} is not delegation-required; run it "
                    "inline and submit with a main_agent producer."
                ),
                exc=ValueError(work_packet_id),
                next_suggested_tools=["submit_writing_result"],
            )
        try:
            token = self.subagent_token_store.issue(
                work_packet_id=work_packet_id,
                role=role,
                model_tier=model_tier,
            )
        except ValueError as exc:
            return error_result(
                "dispatch_writing_reviewer",
                code="subagent_token_invalid",
                message=str(exc),
                exc=exc,
            )
        return ToolResult(
            ok=True,
            tool_name="dispatch_writing_reviewer",
            data={
                "subagent_token": token.token,
                "work_packet_id": token.work_packet_id,
                "role": token.role,
                "stage": packet.stage,
                "delegation_hint": asdict(packet.delegation),
                "must_remember": (
                    "Dispatch a clean-context subagent, then submit its result with "
                    "producer.type='subagent' and this subagent_token."
                ),
                "next_suggested_tools": ["submit_writing_result"],
            },
            next_suggested_tools=["submit_writing_result"],
        )

    def commit_writing_review(self, work_result_id: str) -> ToolResult:
        loaded = self._load_result_and_packet("commit_writing_review", work_result_id)
        if isinstance(loaded, ToolResult):
            return loaded
        result, packet = loaded
        if packet.stage != "writing_review":
            return error_result(
                "commit_writing_review",
                code="wrong_work_packet_stage",
                message=f"expected writing_review packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )
        run_id = str(packet.artifact_refs.get("writing_run_id", ""))
        deliverable_id = str(packet.artifact_refs.get("deliverable_id", ""))
        bound_draft_id = str(packet.artifact_refs.get("draft_id", ""))
        bound_sha = str(packet.artifact_refs.get("draft_sha256", ""))
        run = self._load_run(run_id)
        if run is None:
            return self._run_not_found("commit_writing_review", run_id)
        brief = self._latest_brief(run_id)
        guard = self._deliverable_guard("commit_writing_review", run, brief, deliverable_id)
        if isinstance(guard, ToolResult):
            return guard
        deliverable = guard

        existing = [
            commit
            for commit in self.work_store.list_commits(scope=packet.scope, stage="writing_review")
            if commit.work_result_id == result.work_result_id
        ]
        if existing:
            return self._review_committed_result(run_id, deliverable_id, existing[0].artifact_refs, True)

        # The review is bound to one exact draft. If a newer draft has since
        # landed (e.g. a revision), this review is stale and must be re-run.
        draft = self._load_latest_draft(run_id, deliverable_id)
        if draft is None or draft.content_sha256 != bound_sha:
            return error_result_with_next(
                "commit_writing_review",
                code="stale_review",
                message=(
                    "this review is bound to a draft that is no longer current; "
                    "prepare a fresh review against the latest draft."
                ),
                exc=ValueError("draft_sha256"),
                next_suggested_tools=["prepare_writing_review"],
            )

        payload = result.payload
        issues = [
            ReviewIssue(
                issue_id=str(entry["issue_id"]),
                severity=str(entry["severity"]),
                location=str(entry["location"]),
                skill_id=str(entry["skill_id"]),
                evidence=str(entry["evidence"]),
                correction=str(entry["correction"]),
                category=str(entry.get("category", "style")),
            )
            for entry in payload.get("issues", [])
        ]
        has_blocker = any(issue.severity == "blocker" for issue in issues)
        passed = bool(payload.get("passed", False)) and not has_blocker
        selections = self._deliverable_selections(brief, deliverable)
        version = self.stores.reviews.next_version(run_id, deliverable_id)
        review = WritingReview(
            review_id=f"{run_id}-{deliverable_id}-review-v{version}",
            writing_run_id=run_id,
            deliverable_id=deliverable_id,
            version=version,
            draft_id=bound_draft_id or draft.draft_id,
            draft_sha256=bound_sha or draft.content_sha256,
            selected_skills=selections,
            passed=passed,
            issues=issues,
            notes=[str(item) for item in payload.get("notes", [])],
        )
        self.stores.reviews.save(review)
        commit = self.work_store.save_commit(
            scope=packet.scope,
            stage="writing_review",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs={
                "writing_run_id": run_id,
                "deliverable_id": deliverable_id,
                "review_id": review.review_id,
                "version": version,
                "passed": passed,
            },
        )
        return self._review_committed_result(run_id, deliverable_id, commit.artifact_refs, False)

    # -- revision ------------------------------------------------------

    def prepare_writing_revision(self, writing_run_id: str, deliverable_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("prepare_writing_revision", writing_run_id)
        brief = self._latest_brief(run.writing_run_id)
        guard = self._deliverable_guard("prepare_writing_revision", run, brief, deliverable_id)
        if isinstance(guard, ToolResult):
            return guard
        deliverable = guard
        draft = self._load_latest_draft(run.writing_run_id, deliverable_id)
        review = self._load_latest_review(run.writing_run_id, deliverable_id)
        if draft is None or review is None or review.draft_sha256 != draft.content_sha256:
            return error_result_with_next(
                "prepare_writing_revision",
                code="revision_not_required",
                message="revise only against a fresh review of the current draft.",
                exc=ValueError("review"),
                next_suggested_tools=["prepare_writing_review"],
            )
        if review.passed:
            return error_result_with_next(
                "prepare_writing_revision",
                code="revision_not_required",
                message="the current draft passed review; nothing to revise.",
                exc=ValueError("passed"),
                next_suggested_tools=["finalize_writing_run"],
            )
        rounds = self._revision_count(run.writing_run_id, deliverable_id)
        if rounds >= MAX_REVISION_ROUNDS:
            return error_result_with_next(
                "prepare_writing_revision",
                code="revision_cap_reached",
                message=(
                    f"the automatic {MAX_REVISION_ROUNDS}-round revision cap is reached; "
                    "finalize best-effort or return remaining blockers to the human."
                ),
                exc=ValueError("cap"),
                next_suggested_tools=["finalize_writing_run"],
            )

        selections = self._deliverable_selections(brief, deliverable)
        skill_prompt = compose_skill_prompt(self.registry, selections)
        user_message = {
            "brief": asdict(brief),
            "deliverable": asdict(deliverable),
            "selected_skill_prompt": skill_prompt,
            "context": self._context_payload(run.writing_run_id),
            "research": self._research_dict(run.writing_run_id),
            "prior_draft": {
                "content": draft.content,
                "assumptions": list(draft.assumptions),
                "research_fact_ids": list(draft.research_fact_ids),
            },
            "review_issues": [asdict(issue) for issue in review.issues],
            "revision_round": rounds + 1,
        }
        packet_id = timestamp_id(
            "wpkt", run.writing_run_id, "revision", deliverable_id, short_hash(user_message)
        )
        packet = self._save_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="writing_revision",
                scope=f"writing:{run.writing_run_id}",
                instructions=(
                    "Revise this deliverable to resolve the review issues while honoring "
                    "the skill precedence. Return JSON matching response_schema; do not "
                    "commit it. Preserve everything the review did not fault."
                ),
                system_prompt=WRITING_DRAFT_SYSTEM_PROMPT,
                prompt_blocks=[
                    PromptBlock(
                        text=json.dumps(user_message, ensure_ascii=False),
                        cacheable=False,
                    )
                ],
                response_schema=dict(WRITING_DRAFT_SCHEMA),
                context={"writing_run_id": run.writing_run_id, "deliverable_id": deliverable_id},
                artifact_refs={
                    "writing_run_id": run.writing_run_id,
                    "deliverable_id": deliverable_id,
                    "revises_draft_id": draft.draft_id,
                    "review_id": review.review_id,
                },
                commit_tool="commit_writing_revision",
                delegation=DelegationHint(
                    recommended=False,
                    allowed_tools=["submit_writing_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema with the revised "
                        "prose in content. Do not commit it."
                    ),
                ),
            )
        )
        return self._prepared_result(
            "prepare_writing_revision", packet, run.writing_run_id, user_message,
            extra={"deliverable_id": deliverable_id, "revision_round": rounds + 1},
        )

    def commit_writing_revision(self, work_result_id: str) -> ToolResult:
        loaded = self._load_result_and_packet("commit_writing_revision", work_result_id)
        if isinstance(loaded, ToolResult):
            return loaded
        result, packet = loaded
        if packet.stage != "writing_revision":
            return error_result(
                "commit_writing_revision",
                code="wrong_work_packet_stage",
                message=f"expected writing_revision packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )
        run_id = str(packet.artifact_refs.get("writing_run_id", ""))
        deliverable_id = str(packet.artifact_refs.get("deliverable_id", ""))
        run = self._load_run(run_id)
        if run is None:
            return self._run_not_found("commit_writing_revision", run_id)
        brief = self._latest_brief(run_id)
        guard = self._deliverable_guard("commit_writing_revision", run, brief, deliverable_id)
        if isinstance(guard, ToolResult):
            return guard
        deliverable = guard

        existing = [
            commit
            for commit in self.work_store.list_commits(scope=packet.scope, stage="writing_revision")
            if commit.work_result_id == result.work_result_id
        ]
        if existing:
            return self._draft_committed_result(
                run_id, deliverable_id, existing[0].artifact_refs, True,
                tool_name="commit_writing_revision",
            )

        payload = result.payload
        content = str(payload.get("content", ""))
        if not content.strip():
            return error_result(
                "commit_writing_revision",
                code="draft_content_empty",
                message="a committed revision must have non-empty content.",
                exc=ValueError("content"),
            )
        fact_ids = [str(item) for item in payload.get("research_fact_ids", [])]
        fact_error = self._validate_research_fact_ids("commit_writing_revision", run_id, fact_ids)
        if fact_error is not None:
            return fact_error

        selections = self._deliverable_selections(brief, deliverable)
        version = self.stores.drafts.next_version(run_id, deliverable_id)
        draft = WritingDraft(
            draft_id=f"{run_id}-{deliverable_id}-draft-v{version}",
            writing_run_id=run_id,
            deliverable_id=deliverable_id,
            version=version,
            content=content,
            selected_skills=selections,
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            research_fact_ids=fact_ids,
            self_check=[str(item) for item in payload.get("self_check", [])],
            origin="revision",
        )
        self.stores.drafts.save(draft)
        commit = self.work_store.save_commit(
            scope=packet.scope,
            stage="writing_revision",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs={
                "writing_run_id": run_id,
                "deliverable_id": deliverable_id,
                "draft_id": draft.draft_id,
                "version": version,
            },
        )
        return self._draft_committed_result(
            run_id, deliverable_id, commit.artifact_refs, False,
            tool_name="commit_writing_revision",
        )

    # -- finalization --------------------------------------------------

    def finalize_writing_run(self, writing_run_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("finalize_writing_run", writing_run_id)
        ledger = build_writing_progress(run, self.stores)

        if self._output_exists(run.writing_run_id):
            return self._finalized_result(run.writing_run_id, True)

        if ledger["requires_human"] or ledger["status"] == "blocked":
            return error_result_with_next(
                "finalize_writing_run",
                code="run_blocked",
                message=(
                    "the run has unresolved blockers (facts, explicit requirements, "
                    "wrong deliverable, or unsafe content) and cannot be finalized."
                ),
                exc=ValueError("blocked"),
                next_suggested_tools=["answer_writing_questions"],
            )
        if ledger["next_required_step"] != "finalize":
            return error_result_with_next(
                "finalize_writing_run",
                code="run_incomplete",
                message=(
                    "the run is not ready to finalize; next required step is "
                    f"{ledger['next_required_step']!r}."
                ),
                exc=ValueError(ledger["next_required_step"]),
                next_suggested_tools=[ledger["next_action"].get("tool", "get_writing_progress")],
            )

        brief = self._latest_brief(run.writing_run_id)
        deliverables = [
            self._load_latest_draft(run.writing_run_id, spec.deliverable_id)
            for spec in brief.deliverables
        ]
        deliverables = [draft for draft in deliverables if draft is not None]
        research = (
            self.stores.research.load_latest(run.writing_run_id)
            if self.stores.research.versions(run.writing_run_id)
            else None
        )
        assumptions: list[str] = []
        for source in [brief.assumptions, *[d.assumptions for d in deliverables]]:
            for item in source:
                if item not in assumptions:
                    assumptions.append(item)

        output = WritingOutput(
            output_id=f"{run.writing_run_id}-output",
            writing_run_id=run.writing_run_id,
            deliverables=deliverables,
            selected_skills=list(brief.selected_skills),
            assumptions=assumptions,
            researched_sources=list(research.sources) if research else [],
            warnings=list(ledger["warnings"]),
        )
        self.stores.outputs.save(output)
        self.stores.runs.update(
            replace(run, status="complete", output_id=output.output_id, blocked_on=[])
        )
        return self._finalized_result(run.writing_run_id, False)

    # -- internals -----------------------------------------------------

    def _deliverable_guard(
        self, tool_name: str, run: WritingRun, brief: WritingBrief | None, deliverable_id: str
    ) -> DeliverableSpec | ToolResult:
        """Shared plan/draft precondition check.

        Returns the resolved ``DeliverableSpec`` when the run is ready for
        per-deliverable work, or a terminal ``ToolResult`` describing what to do
        first (commit a brief, answer questions, run research, or fix the id).
        """
        if brief is None:
            return error_result_with_next(
                tool_name,
                code="brief_required",
                message="commit a writing brief before drafting.",
                exc=ValueError("brief"),
                next_suggested_tools=["prepare_writing_brief"],
            )
        if brief.blocking_questions:
            return error_result_with_next(
                tool_name,
                code="brief_blocked",
                message="answer the brief's blocking questions first.",
                exc=ValueError("blocking_questions"),
                next_suggested_tools=["answer_writing_questions"],
            )
        if self._research_pending(run, brief):
            return error_result_with_next(
                tool_name,
                code="research_required",
                message="this run requires research before per-deliverable work.",
                exc=ValueError("research"),
                next_suggested_tools=["prepare_writing_research"],
            )
        deliverable = self._find_deliverable(brief, deliverable_id)
        if deliverable is None:
            return error_result(
                tool_name,
                code="deliverable_not_found",
                message=f"deliverable {deliverable_id!r} is not in the committed brief.",
                exc=KeyError(deliverable_id),
            )
        return deliverable

    def _research_pending(self, run: WritingRun, brief: WritingBrief) -> bool:
        if run.research_policy == ResearchPolicy.OFF:
            return False
        required = run.research_policy == ResearchPolicy.REQUIRED or brief.research_needed
        return required and not self.stores.research.versions(run.writing_run_id)

    @staticmethod
    def _find_deliverable(brief: WritingBrief, deliverable_id: str) -> DeliverableSpec | None:
        for deliverable in brief.deliverables:
            if deliverable.deliverable_id == deliverable_id:
                return deliverable
        return None

    @staticmethod
    def _deliverable_selections(
        brief: WritingBrief, deliverable: DeliverableSpec
    ) -> list[SkillSelection]:
        by_id = {selection.skill_id: selection for selection in brief.selected_skills}
        return [
            by_id[skill_id]
            for skill_id in deliverable.selected_skill_ids
            if skill_id in by_id
        ]

    def _enforce_delegation(
        self, work_packet_id: str, packet: WorkPacket, producer: WorkProducer,
        payload: dict[str, object],
    ) -> ToolResult | None:
        """Clean-context delegation gate (mechanism B) for writing packets.

        A ``delegation_required`` packet (currently only detailed review) must be
        produced by a dispatched subagent carrying a valid, unconsumed token, so
        the main orchestrator cannot absorb the review into its own context.
        """
        if not packet.delegation_required:
            return None
        token = producer.subagent_token
        if not token or producer.type != "subagent":
            return error_result_with_next(
                "submit_writing_result",
                code="subagent_dispatch_required",
                message=(
                    f"WorkPacket {work_packet_id!r} is delegation_required. Dispatch a "
                    "clean-context subagent via dispatch_writing_reviewer and submit from "
                    "there with producer.type='subagent' and its subagent_token."
                ),
                exc=ValueError("subagent_token"),
                next_suggested_tools=["dispatch_writing_reviewer"],
            )
        if not self.subagent_token_store.validate(token=token, work_packet_id=work_packet_id):
            return error_result_with_next(
                "submit_writing_result",
                code="subagent_dispatch_token_invalid",
                message=(
                    "subagent_token does not match this work packet; issue a new one via "
                    "dispatch_writing_reviewer(work_packet_id)."
                ),
                exc=ValueError(token),
                next_suggested_tools=["dispatch_writing_reviewer"],
            )
        record = self.subagent_token_store.load(token)
        if record.consumed:
            incoming = content_hash(payload)
            is_retry = any(
                r.work_packet_id == work_packet_id and r.payload_hash == incoming
                for r in self.work_store.list_results()
            )
            if not is_retry:
                return error_result_with_next(
                    "submit_writing_result",
                    code="subagent_dispatch_token_consumed",
                    message=(
                        "this subagent_token was already used for a different submission; "
                        "dispatch a fresh reviewer for a new result."
                    ),
                    exc=ValueError(token),
                    next_suggested_tools=["dispatch_writing_reviewer"],
                )
        return None

    def _load_latest_draft(self, run_id: str, deliverable_id: str) -> WritingDraft | None:
        if not self.stores.drafts.versions(run_id, deliverable_id):
            return None
        return self.stores.drafts.load_latest(run_id, deliverable_id)

    def _load_latest_review(self, run_id: str, deliverable_id: str) -> WritingReview | None:
        if not self.stores.reviews.versions(run_id, deliverable_id):
            return None
        return self.stores.reviews.load_latest(run_id, deliverable_id)

    def _revision_count(self, run_id: str, deliverable_id: str) -> int:
        return sum(
            1
            for version in self.stores.drafts.versions(run_id, deliverable_id)
            if self.stores.drafts.load(run_id, deliverable_id, version).origin == "revision"
        )

    def _output_exists(self, run_id: str) -> bool:
        try:
            self.stores.outputs.load(run_id)
            return True
        except (KeyError, FileNotFoundError):
            return False

    def _research_dict(self, run_id: str) -> dict | None:
        if not self.stores.research.versions(run_id):
            return None
        return asdict(self.stores.research.load_latest(run_id))

    def _plan_dict(self, run_id: str, deliverable_id: str) -> dict | None:
        if not self.stores.plans.versions(run_id, deliverable_id):
            return None
        return asdict(self.stores.plans.load_latest(run_id, deliverable_id))

    def _known_fact_ids(self, run_id: str) -> set[str]:
        if not self.stores.research.versions(run_id):
            return set()
        return {fact.fact_id for fact in self.stores.research.load_latest(run_id).facts}

    def _validate_research_fact_ids(
        self, tool_name: str, run_id: str, fact_ids: list[str]
    ) -> ToolResult | None:
        if not fact_ids:
            return None
        known = self._known_fact_ids(run_id)
        unknown = [fact_id for fact_id in fact_ids if fact_id not in known]
        if unknown:
            return error_result_with_next(
                tool_name,
                code="unknown_research_fact",
                message=(
                    "cited research facts are absent from committed research: "
                    + ", ".join(sorted(set(unknown)))
                ),
                exc=ValueError("research_fact_ids"),
                next_suggested_tools=["prepare_writing_research"],
            )
        return None

    def _plan_committed_result(
        self, run_id: str, deliverable_id: str, artifact_refs: dict[str, object], idempotent: bool
    ) -> ToolResult:
        plan = self.stores.plans.load_latest(run_id, deliverable_id)
        ledger = build_writing_progress(self.stores.runs.load(run_id), self.stores)
        return ToolResult(
            ok=True,
            tool_name="commit_writing_plan",
            data={
                "writing_run_id": run_id,
                "deliverable_id": deliverable_id,
                "plan_id": str(artifact_refs.get("plan_id", plan.plan_id)),
                "version": plan.version,
                "already_committed": idempotent,
                "progress": ledger,
            },
            next_suggested_tools=[ledger["next_action"].get("tool")]
            if ledger["next_action"].get("tool")
            else [],
        )

    def _draft_committed_result(
        self, run_id: str, deliverable_id: str, artifact_refs: dict[str, object],
        idempotent: bool, *, tool_name: str = "commit_writing_draft",
    ) -> ToolResult:
        draft = self.stores.drafts.load_latest(run_id, deliverable_id)
        ledger = build_writing_progress(self.stores.runs.load(run_id), self.stores)
        return ToolResult(
            ok=True,
            tool_name=tool_name,
            data={
                "writing_run_id": run_id,
                "deliverable_id": deliverable_id,
                "draft_id": str(artifact_refs.get("draft_id", draft.draft_id)),
                "version": draft.version,
                "selected_skills": [asdict(item) for item in draft.selected_skills],
                "research_fact_ids": list(draft.research_fact_ids),
                "already_committed": idempotent,
                "progress": ledger,
            },
            next_suggested_tools=[ledger["next_action"].get("tool")]
            if ledger["next_action"].get("tool")
            else [],
        )

    def _review_committed_result(
        self, run_id: str, deliverable_id: str, artifact_refs: dict[str, object], idempotent: bool
    ) -> ToolResult:
        review = self.stores.reviews.load_latest(run_id, deliverable_id)
        ledger = build_writing_progress(self.stores.runs.load(run_id), self.stores)
        return ToolResult(
            ok=True,
            tool_name="commit_writing_review",
            data={
                "writing_run_id": run_id,
                "deliverable_id": deliverable_id,
                "review_id": str(artifact_refs.get("review_id", review.review_id)),
                "version": review.version,
                "passed": review.passed,
                "selected_skills": [asdict(item) for item in review.selected_skills],
                "issue_count": len(review.issues),
                "already_committed": idempotent,
                "progress": ledger,
            },
            next_suggested_tools=[ledger["next_action"].get("tool")]
            if ledger["next_action"].get("tool")
            else [],
        )

    def _finalized_result(self, run_id: str, idempotent: bool) -> ToolResult:
        output = self.stores.outputs.load(run_id)
        ledger = build_writing_progress(self.stores.runs.load(run_id), self.stores)
        return ToolResult(
            ok=True,
            tool_name="finalize_writing_run",
            data={
                "writing_run_id": run_id,
                "output_id": output.output_id,
                "deliverables": [
                    {"format": self._deliverable_format(run_id, draft.deliverable_id),
                     "content": draft.content}
                    for draft in output.deliverables
                ],
                "selected_skills": [
                    {"id": item.skill_id, "version": item.version, "sha256": item.sha256}
                    for item in output.selected_skills
                ],
                "assumptions": list(output.assumptions),
                "researched_sources": [
                    {"title": source.title, "url": source.url}
                    for source in output.researched_sources
                ],
                "warnings": list(output.warnings),
                "already_finalized": idempotent,
                "progress": ledger,
            },
            next_suggested_tools=[],
        )

    def _deliverable_format(self, run_id: str, deliverable_id: str) -> str:
        brief = self._latest_brief(run_id)
        if brief is not None:
            spec = self._find_deliverable(brief, deliverable_id)
            if spec is not None:
                return spec.format
        return ""

    def _prepared_result(
        self, tool_name: str, packet: WorkPacket, run_id: str,
        user_message: dict, *, extra: dict[str, object] | None = None,
        next_suggested_tools: list[str] | None = None,
    ) -> ToolResult:
        next_tools = next_suggested_tools or ["submit_writing_result"]
        data = {
            "work_packet_id": packet.work_packet_id,
            "stage": packet.stage,
            "writing_run_id": run_id,
            "commit_tool": packet.commit_tool,
            "response_schema": packet.response_schema,
            "system_prompt": packet.system_prompt,
            "prompt": user_message,
            "instructions": packet.instructions,
            "delegation": asdict(packet.delegation),
            "next_suggested_tools": next_tools,
        }
        if extra:
            data.update(extra)
        return ToolResult(
            ok=True,
            tool_name=tool_name,
            data=data,
            next_suggested_tools=next_tools,
        )

    def _resolve_deliverables(
        self,
        run: WritingRun,
        deliverables_payload: object,
        top_selected: list[str],
    ) -> tuple[list[DeliverableSpec], list[SkillSelection]]:
        deliverables: list[DeliverableSpec] = []
        brief_skills: dict[str, SkillSelection] = {}
        for entry in deliverables_payload or []:
            model_selected = list(
                dict.fromkeys(
                    [*top_selected, *[str(i) for i in entry.get("selected_skill_ids", [])]]
                )
            )
            resolved = resolve_skill_stack(
                registry=self.registry,
                format_id=str(entry["format"]),
                model_selected_ids=model_selected,
                include_ids=run.include_skill_ids,
                exclude_ids=run.exclude_skill_ids,
            )
            deliverables.append(
                DeliverableSpec(
                    deliverable_id=str(entry["deliverable_id"]),
                    format=str(entry["format"]),
                    objective=str(entry["objective"]),
                    audience=entry.get("audience"),
                    constraints=[str(c) for c in entry.get("constraints", [])],
                    selected_skill_ids=[item.skill_id for item in resolved],
                )
            )
            for selection in resolved:
                brief_skills.setdefault(selection.skill_id, selection)
        ordered = sorted(brief_skills.values(), key=lambda item: item.skill_id)
        return deliverables, ordered

    def _context_payload(self, run_id: str) -> list[dict[str, object]]:
        return [
            {
                "context_id": item.context_id,
                "label": item.label,
                "kind": item.kind,
                "content": self.stores.context.load_content(item),
            }
            for item in self.stores.context.list(run_id)
        ]

    def _latest_brief(self, run_id: str) -> WritingBrief | None:
        if not self.stores.briefs.versions(run_id):
            return None
        return self.stores.briefs.load_latest(run_id)

    def _build_research_sources(
        self, payload: dict[str, object]
    ) -> tuple[list[ResearchSource], list[str], dict[str, str], ToolResult | None]:
        sources: list[ResearchSource] = []
        warnings: list[str] = []
        remap: dict[str, str] = {}
        canonical_by_url: dict[str, str] = {}
        for entry in payload.get("sources", []) or []:
            source_id = str(entry["source_id"])
            url = str(entry.get("url", "")).strip()
            if not url.lower().startswith(("http://", "https://")):
                return [], [], {}, error_result(
                    "commit_writing_research",
                    code="invalid_source_url",
                    message=f"source {source_id!r} url must be HTTP(S), got {url!r}",
                    exc=ValueError(url),
                )
            title = str(entry.get("title", "")).strip()
            if not title:
                return [], [], {}, error_result(
                    "commit_writing_research",
                    code="invalid_source",
                    message=f"source {source_id!r} must have a non-empty title",
                    exc=ValueError("title"),
                )
            if url in canonical_by_url:
                remap[source_id] = canonical_by_url[url]
                continue
            published_at = entry.get("published_at")
            source = ResearchSource(
                source_id=source_id,
                title=title,
                url=url,
                publisher=entry.get("publisher"),
                published_at=published_at,
                accessed_at=str(entry.get("accessed_at") or utc_now_iso()),
            )
            sources.append(source)
            canonical_by_url[url] = source_id
            remap[source_id] = source_id
            if not published_at:
                warnings.append(
                    f"source {source_id!r} has no publication date; not treated as "
                    "current evidence"
                )
        return sources, warnings, remap, None

    def _build_research_facts(
        self,
        payload: dict[str, object],
        valid_source_ids: set[str],
        remap: dict[str, str],
    ) -> tuple[list[ResearchFact], ToolResult | None]:
        facts_payload = payload.get("facts", []) or []
        if facts_payload and not valid_source_ids:
            return [], error_result(
                "commit_writing_research",
                code="research_sources_undisclosed",
                message="research has facts but no disclosed HTTP(S) sources",
                exc=ValueError("sources"),
            )
        facts: list[ResearchFact] = []
        for entry in facts_payload:
            fact_id = str(entry["fact_id"])
            source_ids = [
                remap.get(str(item), str(item)) for item in entry.get("source_ids", [])
            ]
            if not source_ids:
                return [], error_result(
                    "commit_writing_research",
                    code="fact_without_source",
                    message=f"fact {fact_id!r} has no source; every claim needs a source",
                    exc=ValueError("source_ids"),
                )
            unknown = [item for item in source_ids if item not in valid_source_ids]
            if unknown:
                return [], error_result(
                    "commit_writing_research",
                    code="fact_source_unknown",
                    message=(
                        f"fact {fact_id!r} cites undisclosed source(s): "
                        f"{', '.join(sorted(set(unknown)))}"
                    ),
                    exc=ValueError("source_ids"),
                )
            quote = entry.get("short_quote")
            if quote and len(str(quote).split()) > 25:
                return [], error_result(
                    "commit_writing_research",
                    code="quote_too_long",
                    message=f"fact {fact_id!r} quotes more than 25 words from one source",
                    exc=ValueError("short_quote"),
                )
            facts.append(
                ResearchFact(
                    fact_id=fact_id,
                    claim=str(entry["claim"]),
                    source_ids=list(dict.fromkeys(source_ids)),
                    confidence=str(entry.get("confidence", "medium")),
                    short_quote=quote,
                )
            )
        return facts, None

    def _research_committed_result(
        self, run_id: str, artifact_refs: dict[str, object], idempotent: bool
    ) -> ToolResult:
        research = self.stores.research.load_latest(run_id)
        ledger = build_writing_progress(self.stores.runs.load(run_id), self.stores)
        return ToolResult(
            ok=True,
            tool_name="commit_writing_research",
            data={
                "writing_run_id": run_id,
                "research_id": str(artifact_refs.get("research_id", research.research_id)),
                "source_count": len(research.sources),
                "fact_count": len(research.facts),
                "already_committed": idempotent,
                "progress": ledger,
            },
            next_suggested_tools=[ledger["next_action"].get("tool")]
            if ledger["next_action"].get("tool")
            else [],
        )

    def _effective_research_needed(self, run: WritingRun, model_decision: bool) -> bool:
        if run.research_policy == ResearchPolicy.REQUIRED:
            return True
        if run.research_policy == ResearchPolicy.OFF:
            return False
        return model_decision

    def _save_packet(self, packet: WorkPacket) -> WorkPacket:
        if self.enforce_attention_challenge:
            packet = build_attention_challenge(packet)
        return self.work_store.save_packet(packet)

    def _load_run(self, writing_run_id: str) -> WritingRun | None:
        if not writing_run_id:
            return None
        try:
            return self.stores.runs.load(writing_run_id)
        except (KeyError, FileNotFoundError):
            return None

    def _load_result_and_packet(self, tool_name: str, work_result_id: str):
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return error_result(
                tool_name,
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        return result, packet

    def _run_result(
        self, tool_name: str, run: WritingRun, next_tools: list[str]
    ) -> ToolResult:
        ledger = build_writing_progress(run, self.stores)
        return ToolResult(
            ok=True,
            tool_name=tool_name,
            data={
                "writing_run_id": run.writing_run_id,
                "progress": ledger,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def _run_not_found(self, tool_name: str, writing_run_id: str) -> ToolResult:
        return error_result(
            tool_name,
            code="writing_run_not_found",
            message=f"writing run not found: {writing_run_id}",
            exc=KeyError(writing_run_id),
        )


__all__ = ["WritingToolFacade"]
