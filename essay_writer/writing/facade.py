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
from essay_writer.agent_tools.id_utils import short_hash, timestamp_id
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
from essay_writer.agent_tools.work_store import AgentWorkStore
from essay_writer.writing.context import WritingContextService
from essay_writer.writing.progress import build_writing_progress
from essay_writer.writing.prompts import (
    WRITING_BRIEF_SCHEMA,
    WRITING_BRIEF_SYSTEM_PROMPT,
    build_brief_user_message,
)
from essay_writer.writing.schema import (
    DeliverableSpec,
    ResearchPolicy,
    SkillSelection,
    WriteMode,
    WritingBrief,
    WritingRun,
)
from essay_writer.writing.skills import (
    UnknownWritingSkillError,
    WritingSkillRegistry,
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

    # -- brief ---------------------------------------------------------

    def prepare_writing_brief(self, writing_run_id: str) -> ToolResult:
        run = self._load_run(writing_run_id)
        if run is None:
            return self._run_not_found("prepare_writing_brief", writing_run_id)

        context_items = [
            {
                "context_id": item.context_id,
                "label": item.label,
                "kind": item.kind,
                "content": self.stores.context.load_content(item),
            }
            for item in self.stores.context.list(run.writing_run_id)
        ]
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
            work_packet_id, payload=payload, producer=_coerce_producer(producer)
        )
        duplicate = result.work_result_id in existing_ids
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

    # -- internals -----------------------------------------------------

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
