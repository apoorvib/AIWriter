from __future__ import annotations

import os
import re
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import uuid4

from datetime import datetime

from essay_writer.agent_tools.config import (
    AgentToolConfig,
    STALE_HARNESS_AFTER_PHASE_ADVANCES,
    STALE_HARNESS_AFTER_SECONDS,
)
from essay_writer.agent_tools.run_store import AgentRunStore
from essay_writer.agent_tools.id_utils import content_hash, safe_slug, short_hash, timestamp_id
from essay_writer.agent_tools.phases import (
    PHASE_MODE_STRICT,
    check_tool_allowed,
    normalize_job_stage_to_phase,
)
from essay_writer.agent_tools.skip_tokens import (
    SCOPE_WRITING_STYLE,
    SkipTokenStore,
)
from essay_writer.agent_tools.subagent_tokens import SubagentTokenStore
from essay_writer.agent_tools.workspace_scan import scan_writing_style_directory
from essay_writer.agent_tools.workflow_predicates import (
    is_anti_ai_audit_fresh,
    writing_style_decision_made,
)
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
from essay_writer.agent_tools.workflow_progress import build_workflow_progress
from essay_writer.drafting.anti_ai_audit import (
    ANTI_AI_AUDIT_SCHEMA,
    ANTI_AI_AUDIT_SYSTEM_PROMPT,
)
from essay_writer.drafting.anti_ai_skill import anti_ai_skill_manifest, draft_sha256
from essay_writer.drafting.prompts import DRAFTING_SCHEMA, DRAFTING_SYSTEM_PROMPT
from essay_writer.drafting.schema import utc_now_iso
from essay_writer.drafting.style_revision import (
    STYLE_REVISION_SCHEMA,
    STYLE_REVISION_SYSTEM_PROMPT,
    build_style_revision_user_blocks,
)
from essay_writer.drafting.windowing import (
    DEFAULT_TARGET_WINDOW_WORDS,
    DEFAULT_WINDOWED_REVISION_WORD_THRESHOLD,
    StyleRevisionWindow,
    assemble_window_outputs,
    plan_style_revision_windows,
    should_window_style_revision,
    split_paragraphs,
)
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
# Gap (4): packets whose excerpt/source content exceeds these char
# thresholds are marked delegation_required=True so they MUST be run in
# a clean-context subagent rather than absorbed by the orchestrator.
SOURCE_CARD_DELEGATION_REQUIRED_CHARS = 8_000
RESEARCH_NOTES_DELEGATION_REQUIRED_CHARS = 12_000

# Gap H1: tools that mutate persisted workflow state and therefore must be
# tied to an agent run when require_agent_run is on. Read-only tools,
# bootstrap tools (start/recover/get_harness_instructions), and the
# pre-run upload tools (ingest_*) are intentionally NOT in this set.
_RUN_REQUIRED_TOOLS: frozenset[str] = frozenset({
    "prepare_source_card", "commit_source_card",
    "prepare_writing_style_content", "commit_writing_style_content",
    "attach_writing_style_to_job", "skip_writing_style_calibration",
    "prepare_task_spec", "commit_task_spec",
    "create_job_from_artifacts",
    "prepare_topics", "commit_topics", "select_topic", "reject_topic",
    "create_research_plan", "resolve_source_requests",
    "prepare_research_notes", "commit_research_notes",
    "prepare_outline", "commit_outline",
    "prepare_draft", "commit_draft",
    "prepare_style_revision", "prepare_style_revision_window",
    "commit_style_revision",
    "prepare_anti_ai_audit", "commit_anti_ai_audit",
    "prepare_revision", "commit_revision",
    "prepare_validation", "commit_validation",
    "submit_work_result", "dispatch_subagent",
    "export_markdown",
})

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
    "dispatch_subagent",
    "commit_source_card",
    "ingest_writing_style_sample",
    "prepare_writing_style_content",
    "commit_writing_style_content",
    "attach_writing_style_to_job",
    "skip_writing_style_calibration",
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
    "prepare_style_revision",
    "prepare_style_revision_window",
    "commit_style_revision",
    "prepare_anti_ai_audit",
    "commit_anti_ai_audit",
    "prepare_revision",
    "commit_revision",
    "run_deterministic_checks",
    "prepare_validation",
    "commit_validation",
    "save_user_edit",
    "export_markdown",
    "cleanup_agent_run",
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
    "get_workflow_progress",
]

CLEANUP_SCOPES = ("workflow_logs", "intermediate_artifacts", "all_except_export")
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
    skip_token_store: SkipTokenStore = None  # type: ignore[assignment]
    subagent_token_store: SubagentTokenStore = None  # type: ignore[assignment]
    # Gap (3): when True, every model-reasoning packet gets a proof-of-
    # attention token appended to its system_prompt, and submit_work_result
    # rejects results that do not echo the token. Production builds this
    # facade with enforcement on. The tests/agent_tools conftest flips the
    # default off so the broad suite (which submits hand-written payloads)
    # is not forced to thread tokens through every call; dedicated tests
    # construct the facade with enforce_attention_challenge=True.
    enforce_attention_challenge: bool = True
    # Gap H1: when True, stateful tools (those in _RUN_REQUIRED_TOOLS)
    # refuse calls that omit agent_run_id with `agent_run_required`. This
    # closes the dominant bypass: without it, an orchestrator can skip
    # every phase / stale / writing-style gate simply by never passing
    # the run id, while still persisting artifacts. Production builds the
    # facade with this on; the tests/agent_tools conftest flips it off so
    # the broad suite (which calls many tools without a run) is unaffected.
    require_agent_run: bool = True
    # Fix #1: when True, prepare_validation refuses until an anti-AI audit
    # has been committed for the job. Without it the audit stage (the
    # dedicated "did you apply the anti-AI writing skill" checkpoint) is
    # optional and silently skippable - the exact failure that started
    # this work. Production builds the facade with this on; the
    # tests/agent_tools conftest flips it off so tests that drive
    # draft -> validation directly are unaffected.
    require_anti_ai_audit: bool = True

    def __post_init__(self) -> None:
        if self.skip_token_store is None:
            self.skip_token_store = SkipTokenStore(self.config.skip_token_dir)
        if self.subagent_token_store is None:
            self.subagent_token_store = SubagentTokenStore(
                self.config.subagent_token_dir
            )

    @classmethod
    def from_data_dir(
        cls,
        data_dir: str | Path,
        *,
        source_ingestion_config: SourceIngestionConfig | None = None,
        document_reader: object | None = None,
        ocr_extractor: object | None = None,
        llm_guard: object | None = None,
        enforce_attention_challenge: bool = True,
        require_agent_run: bool = True,
        require_anti_ai_audit: bool = True,
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
            enforce_attention_challenge=enforce_attention_challenge,
            require_agent_run=require_agent_run,
            require_anti_ai_audit=require_anti_ai_audit,
        )

    def _save_model_packet(self, packet: WorkPacket) -> WorkPacket:
        """Persist a model-reasoning packet, applying the attention
        challenge (Gap 3) first when enforcement is on.

        All ``prepare_*`` tools route their WorkPacket saves through this
        method so the challenge is applied uniformly at one chokepoint.
        """
        packet = self._apply_attention_challenge(packet)
        return self.work_store.save_packet(packet)

    def _writing_style_skip_warnings(self, job_id: str) -> list[str]:
        """Return a one-item warning list when the job opted out of voice
        calibration (mechanism D / Gap 6), else an empty list.

        Surfacing this on every downstream drafting/revision packet keeps
        the skip decision visible long after create_job_from_artifacts,
        so the orchestrator (and the user) are reminded that the draft is
        not voice-calibrated and carries detector risk.
        """
        try:
            job = self.stores.workflow.load_job(job_id)
        except (KeyError, FileNotFoundError):
            return []
        if getattr(job, "writing_style_skip_token", None) and not getattr(
            job, "writing_style_content_id", None
        ):
            return [
                "This job opted out of writing-style calibration "
                "(writing_style_skip_token is set). The generated prose will "
                "not match a user voice and carries elevated AI-detection "
                "risk. Attach writing-style content with "
                "attach_writing_style_to_job to remove this warning."
            ]
        return []

    def _apply_attention_challenge(self, packet: WorkPacket) -> WorkPacket:
        """Append a proof-of-attention token to the packet's system prompt
        and record it on the packet. No-op when enforcement is off or when
        the packet already carries a challenge."""
        if not self.enforce_attention_challenge:
            return packet
        if packet.system_prompt_challenge:
            return packet
        token = f"ATTN-{uuid4().hex[:12]}"
        footer = (
            "\n\n---\n"
            "ATTENTION CHECK (required): To confirm you have read this entire "
            f"system prompt, you MUST include the exact token {token} somewhere "
            "in your JSON output. Append it to a free-text string field such as "
            "a notes or self_check_notes array, or any existing string field. "
            "Outputs that omit this token will be rejected with "
            "system_prompt_not_honored, because a missing token indicates the "
            "system prompt was not actually read."
        )
        return replace(
            packet,
            system_prompt=packet.system_prompt + footer,
            system_prompt_challenge=token,
        )

    def _enforce_writing_style_gate(
        self,
        *,
        job_id: str | None,
        writing_style_skip_token: str | None,
    ) -> ToolResult | None:
        """Return a ``blocked_on`` error if the writing-style gate fails.

        The gate fires when:
        - ``job_id`` is None (a brand-new job is being created), OR
        - ``job_id`` is set but no matching job exists yet (also a new
          job creation).

        It does NOT fire on idempotent re-calls of an existing job that
        either already has writing-style content attached or already
        recorded a skip token.
        """
        # Idempotent retry path: if the job exists already, skip the gate.
        if job_id is not None:
            try:
                existing = self.stores.workflow.load_job(job_id)
            except (KeyError, FileNotFoundError):
                existing = None
            if existing is not None and writing_style_decision_made(existing):
                return None

        # If a skip token was supplied, validate it.
        if writing_style_skip_token is not None:
            scope = SCOPE_WRITING_STYLE
            # A skip token is scoped to a concrete job id. Without an
            # explicit job_id the token would be validated against "" and
            # a single token would satisfy every job_id=None creation
            # (M3). Require the caller to name the job they are skipping.
            if not job_id:
                return _error_result_with_next(
                    "create_job_from_artifacts",
                    code="writing_style_skip_token_requires_job_id",
                    message=(
                        "writing_style_skip_token requires an explicit job_id "
                        "so the skip decision is scoped to a specific job. Call "
                        "create_job_from_artifacts with the same job_id you "
                        "passed to skip_writing_style_calibration."
                    ),
                    exc=ValueError("job_id"),
                    next_suggested_tools=["skip_writing_style_calibration"],
                )
            if not self.skip_token_store.validate(
                token=writing_style_skip_token,
                scope=scope,
                job_id=job_id,
            ):
                return _error_result_with_next(
                    "create_job_from_artifacts",
                    code="writing_style_skip_token_invalid",
                    message=(
                        "writing_style_skip_token did not match this job and "
                        f"scope ({scope!r}). Issue a new token via "
                        "skip_writing_style_calibration(job_id, reason)."
                    ),
                    exc=ValueError(writing_style_skip_token),
                    next_suggested_tools=["skip_writing_style_calibration"],
                )
            return None

        # No token, no attached content. Surface what is available in
        # inputs/writing_style/ so the orchestrator can choose to ingest
        # the existing samples or to skip with an explicit reason.
        discovered = scan_writing_style_directory()
        sample_paths = [item.path for item in discovered]
        next_tools: list[str] = []
        if sample_paths:
            next_tools.append("ingest_writing_style_sample")
        next_tools.append("skip_writing_style_calibration")
        return ToolResult(
            ok=False,
            tool_name="create_job_from_artifacts",
            error=ToolError(
                code="writing_style_required",
                message=(
                    "create_job_from_artifacts requires writing-style "
                    "calibration. Either attach a writing-style content_id "
                    "to the job via attach_writing_style_to_job, OR call "
                    "skip_writing_style_calibration(job_id, reason='...') "
                    "and pass the returned token as writing_style_skip_token."
                ),
                detail={
                    "scope": SCOPE_WRITING_STYLE,
                    "samples_discovered": sample_paths,
                    "samples_discovered_count": len(sample_paths),
                    "samples_directory": "inputs/writing_style/",
                    "remedy": (
                        "If samples_discovered is non-empty, ingest them with "
                        "ingest_writing_style_sample, then prepare/commit a "
                        "writing-style content and attach it to the job. "
                        "If you intend to proceed without voice calibration, "
                        "call skip_writing_style_calibration(job_id, reason)."
                    ),
                },
            ),
            next_suggested_tools=next_tools,
        )

    def dispatch_subagent(
        self,
        *,
        work_packet_id: str,
        role: str,
        model_tier: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        """Issue a subagent dispatch token for a work packet.

        Required before ``submit_work_result`` when the packet has
        ``delegation_required=True``. The orchestrator should:
        1. Call ``dispatch_subagent`` to get the token
        2. Dispatch a subagent with the packet (the subagent reads it
           via ``get_work_packet``) and the role
        3. Have the subagent submit its result with the token in the
           producer's ``subagent_token`` field
        """
        # Validate the work packet exists. Run the phase gate if linked.
        try:
            packet = self.work_store.load_packet(work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "dispatch_subagent",
                code="work_packet_not_found",
                message=f"WorkPacket not found: {work_packet_id}",
                exc=exc,
            )
        # Call the gate unconditionally: dispatch_subagent is in
        # _RUN_REQUIRED_TOOLS, so when agent_run_id is None and
        # require_agent_run is on, _load_run_and_gate is what emits the
        # agent_run_required error. Guarding this behind "is not None" silently
        # skipped that enforcement (bug_006).
        _, _gate_error = self._load_run_and_gate(
            "dispatch_subagent", agent_run_id
        )
        if _gate_error is not None:
            return _gate_error
        if not role or not role.strip():
            return _error_result_with_next(
                "dispatch_subagent",
                code="role_required",
                message=(
                    "dispatch_subagent requires a non-empty role string "
                    "(e.g. the packet's delegation.suggested_role)."
                ),
                exc=ValueError("role"),
                next_suggested_tools=["dispatch_subagent"],
            )
        # A dispatch token is only meaningful for a packet that the
        # workflow wants delegated. Minting one for a packet with no
        # delegation intent (neither required nor recommended) is
        # pointless and signals a confused caller. (M2 hardening.)
        if not packet.delegation_required and not packet.delegation.recommended:
            return _error_result_with_next(
                "dispatch_subagent",
                code="delegation_not_applicable",
                message=(
                    f"WorkPacket {work_packet_id!r} is not marked for delegation "
                    "(neither delegation_required nor delegation.recommended). "
                    "Run it inline and submit with a main_agent producer; no "
                    "dispatch token is needed."
                ),
                exc=ValueError(work_packet_id),
                next_suggested_tools=["submit_work_result"],
            )
        required_model_tier = (
            packet.delegation.required_model_tier.strip().lower()
            if packet.delegation.required_model_tier
            else None
        )
        requested_model_tier = model_tier.strip().lower() if model_tier else None
        if required_model_tier and not _model_tier_satisfies_required(
            requested_model_tier,
            required_model_tier=required_model_tier,
        ):
            return _error_result_with_next(
                "dispatch_subagent",
                code="subagent_model_tier_required",
                message=(
                    f"WorkPacket {work_packet_id!r} requires a "
                    f"{required_model_tier!r} subagent model tier. Dispatch with "
                    f"model_tier={required_model_tier!r}, or a provider-specific "
                    "frontier equivalent such as 'opus'. Lower tiers are not allowed."
                ),
                exc=ValueError("model_tier"),
                next_suggested_tools=["dispatch_subagent"],
            )
        try:
            token = self.subagent_token_store.issue(
                work_packet_id=work_packet_id,
                role=role,
                model_tier=requested_model_tier,
            )
        except ValueError as exc:
            return _error_result(
                "dispatch_subagent",
                code="subagent_token_invalid",
                message=str(exc),
                exc=exc,
            )
        next_tools = ["submit_work_result"]
        return ToolResult(
            ok=True,
            tool_name="dispatch_subagent",
            data={
                "subagent_token": token.token,
                "work_packet_id": token.work_packet_id,
                "role": token.role,
                "model_tier": token.model_tier,
                "required_model_tier": required_model_tier,
                "stage": packet.stage,
                "delegation_hint": asdict(packet.delegation),
                "created_at": token.created_at,
                "next_suggested_tools": next_tools,
                "must_remember": (
                    "Pass subagent_token in the producer.subagent_token "
                    "field when calling submit_work_result for this packet."
                ),
            },
            next_suggested_tools=next_tools,
        )

    def skip_writing_style_calibration(
        self,
        *,
        job_id: str,
        reason: str,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        """Issue a skip token that bypasses the writing-style gate.

        The ``reason`` is recorded on the token and on the agent run so
        the decision is auditable. ``reason`` must be a non-empty string;
        callers should articulate why voice calibration is being skipped.
        """
        run = None
        if agent_run_id is not None:
            run, _gate_error = self._load_run_and_gate(
                "skip_writing_style_calibration", agent_run_id
            )
            if _gate_error is not None:
                return _gate_error

        if not job_id or not job_id.strip():
            return _error_result_with_next(
                "skip_writing_style_calibration",
                code="job_id_required",
                message=(
                    "skip_writing_style_calibration requires a concrete, "
                    "non-empty job_id so the skip is scoped to a specific job. "
                    "Pass the same job_id you will give create_job_from_artifacts."
                ),
                exc=ValueError("job_id"),
                next_suggested_tools=["skip_writing_style_calibration"],
            )

        if not reason or not reason.strip():
            return _error_result_with_next(
                "skip_writing_style_calibration",
                code="reason_required",
                message=(
                    "skip_writing_style_calibration requires a non-empty "
                    "reason so the decision is auditable."
                ),
                exc=ValueError("reason"),
                next_suggested_tools=["skip_writing_style_calibration"],
            )

        try:
            token = self.skip_token_store.issue(
                scope=SCOPE_WRITING_STYLE,
                job_id=job_id,
                reason=reason,
            )
        except ValueError as exc:
            return _error_result(
                "skip_writing_style_calibration",
                code="skip_token_invalid",
                message=str(exc),
                exc=exc,
            )

        # Record the decision on the run so recover_agent_run can surface it.
        if agent_run_id is not None and run is not None:
            self.run_store.update_run(
                replace(
                    run,
                    writing_style_skip_token=token.token,
                )
            )

        next_tools = ["create_job_from_artifacts"]
        return ToolResult(
            ok=True,
            tool_name="skip_writing_style_calibration",
            data={
                "skip_token": token.token,
                "scope": token.scope,
                "job_id": token.job_id,
                "reason": token.reason,
                "created_at": token.created_at,
                "next_suggested_tools": next_tools,
            },
            next_suggested_tools=next_tools,
        )

    def _load_run_and_gate(
        self,
        tool_name: str,
        agent_run_id: str | None,
    ) -> tuple[AgentRun | None, ToolResult | None]:
        """Load the agent run if given and run the gates.

        Runs three checks in order:
        1. Run exists (missing -> ``missing_run`` error)
        2. Phase gate (out-of-order -> ``out_of_order`` error)
        3. Stale-harness gate (too many advances or too much time since
           the orchestrator last read ``get_harness_instructions`` ->
           ``harness_stale`` error)

        Returns ``(run, error)``. If ``agent_run_id`` is ``None`` and the
        tool is a stateful (run-required) tool with enforcement on,
        returns ``(None, agent_run_required_error)``; otherwise
        ``(None, None)``.
        """
        if agent_run_id is None:
            if self.require_agent_run and tool_name in _RUN_REQUIRED_TOOLS:
                return None, _error_result_with_next(
                    tool_name,
                    code="agent_run_required",
                    message=(
                        f"{tool_name} mutates workflow state and requires an "
                        "agent_run_id. Start or recover a run first, then pass "
                        "its id. (Omitting agent_run_id would bypass the phase, "
                        "stale-harness, and writing-style gates.)"
                    ),
                    exc=ValueError("agent_run_id"),
                    next_suggested_tools=["start_agent_run", "recover_agent_run"],
                )
            return None, None
        try:
            run = self.run_store.load_run(agent_run_id)
        except (KeyError, FileNotFoundError) as exc:
            return None, _missing_run_result(tool_name, agent_run_id, exc)
        gate_error = _phase_gate_error(tool_name, run)
        if gate_error is not None:
            return run, gate_error
        stale_error = _harness_stale_error(tool_name, run)
        if stale_error is not None:
            return run, stale_error
        return run, None

    def get_harness_instructions(
        self,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
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
        # If linked to a run, reset the stale-harness counter and stamp
        # the last-read timestamp. (mechanism C)
        if agent_run_id is not None:
            try:
                run = self.run_store.load_run(agent_run_id)
                self.run_store.update_run(
                    replace(
                        run,
                        phase_advances_since_harness_read=0,
                        last_harness_read_at=utc_now_iso(),
                    )
                )
            except (KeyError, FileNotFoundError):
                # Soft-fail: get_harness_instructions still returns the
                # instructions even if the run was not found.
                pass
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
        phase_mode: str | None = None,
    ) -> ToolResult:
        # If a job is provided, inherit its current_stage as the run's
        # initial phase so the gate does not block tools that are valid
        # for that mid-flight job.
        initial_phase: str | None = None
        if job_id is not None:
            try:
                existing_job = self.stores.workflow.load_job(job_id)
                # Normalize the job-store stage vocabulary to a valid run
                # phase, else a resumed run could land in a phase no tool
                # allows and be bricked. (Tier-1 fix.)
                initial_phase = normalize_job_stage_to_phase(
                    getattr(existing_job, "current_stage", None)
                )
            except (KeyError, FileNotFoundError):
                initial_phase = None
        run = self.run_store.start_run(
            objective=objective,
            job_id=job_id,
            user_constraints=user_constraints,
            initial_phase=initial_phase,
            phase_mode=phase_mode,
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
        run, _gate_error = self._load_run_and_gate("get_agent_run_state", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        return ToolResult(
            ok=True,
            tool_name="get_agent_run_state",
            data={**_run_state(run), "must_remember": list(MUST_REMEMBER)},
        )

    def get_workflow_progress(self, *, agent_run_id: str) -> ToolResult:
        """Read-only completion ledger derived from persisted store state.

        Returns which required workflow steps are done and the first undone
        required step. Drives Dynamic Workflow orchestration: the script loops
        on next_required_step until all_required_done. No mutation, no gate.
        """
        try:
            run = self.run_store.load_run(agent_run_id)
        except (KeyError, FileNotFoundError) as exc:
            return _missing_run_result("get_workflow_progress", agent_run_id, exc)
        progress = build_workflow_progress(run, self.stores)
        next_step = progress["next_required_step"]
        next_tools = []
        if next_step is not None:
            for step in progress["steps"]:
                if step["step_id"] == next_step:
                    tool = step["next_action"].get("tool")
                    if tool:
                        next_tools = [tool.split(" ")[0]]
                    break
        return ToolResult(
            ok=True,
            tool_name="get_workflow_progress",
            data={**progress, "must_remember": list(MUST_REMEMBER)},
            warnings=list(progress["warnings"]),
            next_suggested_tools=next_tools,
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
                "phase_history": list(recovery.run.phase_history),
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
        writing_style_skip_token: str | None = None,
    ) -> ToolResult:
        run = None
        run, _gate_error = self._load_run_and_gate("create_job_from_artifacts", agent_run_id)
        if _gate_error is not None:
            return _gate_error

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

        # Writing-style gate (mechanism D). Fires only when the call is
        # linked to an agent run (i.e. the orchestrator is driving the
        # workflow). The orchestrator must either:
        # (a) have already attached writing-style content to the job, OR
        # (b) explicitly call skip_writing_style_calibration(reason=...)
        # and pass the returned token as ``writing_style_skip_token``.
        # Idempotent retries on an existing job that recorded a decision
        # bypass the gate. Calls without ``agent_run_id`` (e.g. test
        # fixtures, ad-hoc CLI use) also bypass it.
        if agent_run_id is not None:
            gate_error = self._enforce_writing_style_gate(
                job_id=job_id,
                writing_style_skip_token=writing_style_skip_token,
            )
            if gate_error is not None:
                return gate_error

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

        # If a writing_style_skip_token was supplied, record it on the
        # job so idempotent retries see the decision. (mechanism D)
        if writing_style_skip_token is not None and not getattr(
            job, "writing_style_skip_token", None
        ):
            job = self.stores.workflow.record_writing_style_skip(
                job_id=job.id,
                skip_token=writing_style_skip_token,
            )

        next_tools = ["prepare_topics"]
        artifact_refs = {
            "job_id": job.id,
            "task_spec_id": task_spec.id,
            "source_ids": list(effective_source_ids),
        }
        if agent_run_id is not None and run is not None:
            # Normalize the job stage to a valid run phase (Tier-1 fix).
            job_phase = normalize_job_stage_to_phase(job.current_stage)
            self.run_store.update_run(
                replace(
                    run,
                    job_id=job.id,
                    current_phase=job_phase,
                )
            )
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase=job_phase,
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
        run, _gate_error = self._load_run_and_gate("resolve_source_requests", agent_run_id)
        if _gate_error is not None:
            return _gate_error

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
        run, _gate_error = self._load_run_and_gate("ingest_source_file", agent_run_id)
        if _gate_error is not None:
            return _gate_error

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

    def ingest_writing_style_sample(
        self,
        sample_path: str | Path,
        *,
        title: str | None = None,
        sample_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        path = Path(sample_path)
        if not path.exists():
            return _error_result(
                "ingest_writing_style_sample",
                code="writing_style_sample_not_found",
                message=f"writing style sample not found: {path}",
                exc=FileNotFoundError(path),
            )
        if not path.is_file():
            return _error_result(
                "ingest_writing_style_sample",
                code="writing_style_sample_not_file",
                message=f"writing style sample is not a file: {path}",
                exc=IsADirectoryError(path),
            )
        suffix = path.suffix.lower()
        if suffix not in _SUPPORTED_WRITING_STYLE_SUFFIXES:
            return _error_result(
                "ingest_writing_style_sample",
                code="unsupported_writing_style_sample_type",
                message=(
                    f"unsupported writing style sample type: {suffix or '<none>'}; "
                    f"supported suffixes: {', '.join(sorted(_SUPPORTED_WRITING_STYLE_SUFFIXES))}"
                ),
                exc=ValueError(suffix),
            )
        run = None
        run, _gate_error = self._load_run_and_gate("ingest_writing_style_sample", agent_run_id)
        if _gate_error is not None:
            return _gate_error

        from essay_writer.writing_style.ingestion import (
            HumanWritingSampleIngestionService,
        )

        service = HumanWritingSampleIngestionService(
            self.stores.writing_style_sample_store,
            reader=self.source_materializer._document_reader,
        )
        try:
            sample = service.ingest(path, title=title, sample_id=sample_id)
        except FileNotFoundError as exc:
            return _error_result(
                "ingest_writing_style_sample",
                code="writing_style_sample_not_found",
                message=str(exc),
                exc=exc,
            )

        data = {
            "sample_id": sample.id,
            "title": sample.title,
            "source_filename": sample.source_filename,
            "source_type": sample.source_type,
            "page_count": sample.page_count,
            "word_count": sample.word_count,
            "char_count": sample.char_count,
            "extraction_method": sample.extraction_method,
            "warnings": list(sample.warnings),
            "artifact_dir": sample.artifact_dir,
            "next_suggested_tools": ["prepare_writing_style_content"],
        }
        if agent_run_id is not None and run is not None:
            existing_ids = list(run.artifact_refs.get("writing_style_sample_ids", []))
            if sample.id not in existing_ids:
                existing_ids.append(sample.id)
            self.run_store.update_run(
                replace(
                    run,
                    artifact_refs={
                        **run.artifact_refs,
                        "writing_style_sample_ids": existing_ids,
                    },
                    next_suggested_tools=["prepare_writing_style_content"],
                )
            )
            self.run_store.append_event(
                agent_run_id,
                "writing_style_sample_ingested",
                "Ingested writing-style sample.",
                data={"sample_id": sample.id, "word_count": sample.word_count},
            )
        return ToolResult(
            ok=True,
            tool_name="ingest_writing_style_sample",
            data=data,
            warnings=list(sample.warnings),
            next_suggested_tools=["prepare_writing_style_content"],
        )

    def prepare_writing_style_content(
        self,
        sample_ids: list[str],
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        if not sample_ids:
            return _error_result(
                "prepare_writing_style_content",
                code="writing_style_sample_ids_empty",
                message="at least one writing-style sample_id is required",
                exc=ValueError("sample_ids"),
            )
        run = None
        run, _gate_error = self._load_run_and_gate("prepare_writing_style_content", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        try:
            prompt_samples = self.stores.writing_style_sample_store.load_prompt_samples(
                list(sample_ids)
            )
        except (KeyError, FileNotFoundError) as exc:
            return _error_result_with_next(
                "prepare_writing_style_content",
                code="writing_style_sample_not_found",
                message=f"writing-style sample not found: {exc}",
                exc=exc,
                next_suggested_tools=["ingest_writing_style_sample"],
            )

        from essay_writer.writing_style.prompts import (
            WRITING_STYLE_CONTENT_SCHEMA,
            WRITING_STYLE_CONTENT_SYSTEM_PROMPT,
            build_writing_style_user_message,
        )

        user_message = build_writing_style_user_message(prompt_samples)
        packet_id = timestamp_id(
            "workpkt",
            "writing_style",
            "content",
            short_hash([sample.sample_id for sample in prompt_samples]),
        )
        artifact_refs = {
            "writing_style_sample_ids": [sample.sample_id for sample in prompt_samples],
        }
        packet = self._save_model_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="writing_style_content",
                scope="writing_style",
                instructions=(
                    "Analyze the user's writing samples and produce tone and style guidance JSON "
                    "matching response_schema. Treat the samples as style exemplars only; do not "
                    "copy facts, citations, or claims from them."
                ),
                system_prompt=WRITING_STYLE_CONTENT_SYSTEM_PROMPT,
                prompt_blocks=[PromptBlock(text=user_message, cacheable=True)],
                response_schema=dict(WRITING_STYLE_CONTENT_SCHEMA),
                context={
                    "sample_ids": [sample.sample_id for sample in prompt_samples],
                    "sample_fingerprints": [sample.cleaned_text_hash for sample in prompt_samples],
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_writing_style_content",
                delegation=DelegationHint(
                    recommended=False,
                    reason=(
                        "writing-style content generation is a small, self-contained reasoning task"
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
                current_phase="writing_style",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_writing_style_content",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt": user_message,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_writing_style_content(
        self,
        *,
        work_result_id: str,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("commit_writing_style_content", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_writing_style_content",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.stage != "writing_style_content":
            return _error_result(
                "commit_writing_style_content",
                code="wrong_work_packet_stage",
                message=f"expected writing_style_content packet, got {packet.stage}",
                exc=ValueError(packet.stage),
            )

        from essay_writer.writing_style.prompts import WRITING_STYLE_CONTENT_SCHEMA
        from essay_writer.writing_style.service import (
            _content_from_payload,
            build_sample_fingerprint,
        )
        from essay_writer.writing_style.storage import (
            stable_writing_style_content_id,
        )

        validation_error = _validate_work_payload(
            result.payload,
            WRITING_STYLE_CONTENT_SCHEMA,
            tool_name="commit_writing_style_content",
        )
        if validation_error is not None:
            return validation_error

        sample_ids = list(packet.artifact_refs.get("writing_style_sample_ids", []))
        if not sample_ids:
            return _error_result(
                "commit_writing_style_content",
                code="writing_style_sample_ids_missing",
                message="packet is missing artifact_refs.writing_style_sample_ids",
                exc=ValueError("sample_ids"),
            )
        try:
            prompt_samples = self.stores.writing_style_sample_store.load_prompt_samples(
                sample_ids
            )
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_writing_style_content",
                code="writing_style_sample_not_found",
                message=f"writing-style sample not found: {exc}",
                exc=exc,
            )

        generator_version = "writing-style-content-v1"
        sample_fingerprint = build_sample_fingerprint(
            prompt_samples, generator_version=generator_version
        )
        content_id = stable_writing_style_content_id(sample_fingerprint)
        scope = "writing_style"
        artifact_refs = {
            "writing_style_content_id": content_id,
            "writing_style_sample_ids": sample_ids,
        }

        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(
                    scope=scope, stage="writing_style_content"
                )
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None

        if not already_committed:
            content = _content_from_payload(
                result.payload,
                sample_ids=sample_ids,
                sample_fingerprint=sample_fingerprint,
                version=1,
                content_id=content_id,
                generator_model="harness",
                generator_version=generator_version,
            )
            try:
                self.stores.writing_style_content_store.save(content)
            except FileExistsError:
                # another run already wrote this exact content; treat as success
                pass
            self.work_store.save_commit(
                scope=scope,
                stage="writing_style_content",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )

        if agent_run_id is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=["attach_writing_style_to_job"],
            )
        return ToolResult(
            ok=True,
            tool_name="commit_writing_style_content",
            data={
                "content_id": content_id,
                "sample_ids": sample_ids,
                "already_committed": already_committed,
                "artifact_refs": artifact_refs,
                "next_suggested_tools": ["attach_writing_style_to_job"],
            },
            next_suggested_tools=["attach_writing_style_to_job"],
        )

    def _load_writing_style_payload_for_job(self, job_id: str):
        """Return the WritingStylePayload attached to this job, or None.

        Failures to load the content (missing files, schema drift) are treated
        as 'no payload' rather than hard errors so a downstream prepare tool
        still works without voice calibration. Use this helper everywhere a
        prepare tool needs to thread a writing-style block into prompt_blocks.
        """
        from essay_writer.writing_style.service import build_writing_style_payload

        try:
            job = self.stores.workflow.load_job(job_id)
        except (KeyError, FileNotFoundError):
            return None
        if not job.writing_style_content_id:
            return None
        try:
            content = self.stores.writing_style_content_store.load(
                job.writing_style_content_id
            )
        except (KeyError, FileNotFoundError):
            return None
        try:
            samples = self.stores.writing_style_sample_store.load_prompt_samples(
                list(content.sample_ids)
            )
        except (KeyError, FileNotFoundError):
            samples = []
        return build_writing_style_payload(content, samples)

    def attach_writing_style_to_job(
        self,
        *,
        job_id: str,
        content_id: str,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("attach_writing_style_to_job", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        try:
            content = self.stores.writing_style_content_store.load(content_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "attach_writing_style_to_job",
                code="writing_style_content_not_found",
                message=f"WritingStyleContent not found: {content_id}",
                exc=exc,
            )
        try:
            updated_job = self.stores.workflow.attach_writing_style(
                job_id=job_id,
                sample_ids=list(content.sample_ids),
                content_id=content_id,
            )
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "attach_writing_style_to_job",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        artifact_refs = {
            "job_id": updated_job.id,
            "writing_style_content_id": content_id,
            "writing_style_sample_ids": list(content.sample_ids),
        }
        if agent_run_id is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=["prepare_topics"],
            )
        return ToolResult(
            ok=True,
            tool_name="attach_writing_style_to_job",
            data={
                "job_id": updated_job.id,
                "writing_style_content_id": content_id,
                "writing_style_sample_ids": list(content.sample_ids),
                "artifact_refs": artifact_refs,
                "next_suggested_tools": ["prepare_topics"],
            },
            next_suggested_tools=["prepare_topics"],
        )

    def prepare_source_card(
        self,
        source_id: str,
        *,
        agent_run_id: str | None = None,
        reuse_existing: bool = True,
    ) -> ToolResult:
        run = None
        run, _gate_error = self._load_run_and_gate("prepare_source_card", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        selected_excerpt_chars = sum(chunk.char_count for chunk in excerpts)
        delegation = _source_card_delegation(
            source_id=source_id,
            selected_excerpt_chars=selected_excerpt_chars,
            pending_source_card_packets=_pending_source_card_packet_count(
                self.work_store,
                self.run_store.load_run(agent_run_id) if agent_run_id is not None else None,
            ),
        )
        # Gap (4): large source-card excerpts must be processed by a
        # subagent so the main orchestrator does not absorb a multi-KB
        # excerpt block into its own context.
        source_card_delegation_required = (
            selected_excerpt_chars > SOURCE_CARD_DELEGATION_REQUIRED_CHARS
        )
        packet = self._save_model_packet(
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
                    "selected_excerpt_chars": selected_excerpt_chars,
                    "selected_chunk_ids": [chunk.id for chunk in excerpts],
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_source_card",
                delegation=delegation,
                delegation_required=source_card_delegation_required,
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
        _, _gate_error = self._load_run_and_gate("submit_work_result", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        # Subagent dispatch gate (mechanism B). If the packet requires a
        # subagent dispatch, the producer MUST carry a valid token issued
        # by dispatch_subagent for this exact work packet.
        if packet.delegation_required:
            token = getattr(producer, "subagent_token", None)
            if not token:
                return _error_result_with_next(
                    "submit_work_result",
                    code="subagent_dispatch_required",
                    message=(
                        f"WorkPacket {work_packet_id!r} has delegation_required=True. "
                        "submit_work_result requires a producer carrying a "
                        "subagent_token issued by dispatch_subagent. The packet "
                        "is designed to run in a clean-context subagent; the "
                        "main orchestrator should not absorb it."
                    ),
                    exc=ValueError("subagent_token"),
                    next_suggested_tools=["dispatch_subagent"],
                )
            if not self.subagent_token_store.validate(
                token=token, work_packet_id=work_packet_id
            ):
                return _error_result_with_next(
                    "submit_work_result",
                    code="subagent_dispatch_token_invalid",
                    message=(
                        "subagent_token does not match this work packet. "
                        "Issue a new token via dispatch_subagent(work_packet_id, role, model_tier)."
                    ),
                    exc=ValueError(token),
                    next_suggested_tools=["dispatch_subagent"],
                )
            # Gap (8): a delegated packet must be produced by a subagent.
            # A main_agent producer carrying a token is contradictory and
            # signals the orchestrator ran the work inline anyway.
            if getattr(producer, "type", None) != "subagent":
                return _error_result_with_next(
                    "submit_work_result",
                    code="subagent_dispatch_required",
                    message=(
                        f"WorkPacket {work_packet_id!r} is delegation_required. "
                        "The producer.type must be 'subagent', not "
                        f"{getattr(producer, 'type', None)!r}. Run the packet in "
                        "a dispatched subagent and submit from there."
                    ),
                    exc=ValueError(getattr(producer, "type", None)),
                    next_suggested_tools=["dispatch_subagent"],
                )
            # M2 hardening: a dispatch token authorizes ONE submission.
            # If it was already consumed, allow only an idempotent retry
            # (the same payload, which the store dedups) and reject reuse
            # with a different payload.
            token_record = self.subagent_token_store.load(token)
            if token_record.consumed:
                incoming_hash = content_hash(payload)
                is_retry = any(
                    r.work_packet_id == work_packet_id
                    and r.payload_hash == incoming_hash
                    for r in self.work_store.list_results()
                )
                if not is_retry:
                    return _error_result_with_next(
                        "submit_work_result",
                        code="subagent_dispatch_token_consumed",
                        message=(
                            "This subagent_token was already used for a "
                            "different submission. Each dispatch authorizes one "
                            "result; dispatch a fresh subagent for a new "
                            "submission."
                        ),
                        exc=ValueError(token),
                        next_suggested_tools=["dispatch_subagent"],
                    )
        validation_error = _validate_work_payload(
            payload,
            packet.response_schema,
            tool_name="submit_work_result",
        )
        if validation_error is not None:
            return validation_error

        # Proof-of-attention gate (Gap 3). If the packet carries a
        # system_prompt_challenge, the token must appear somewhere in the
        # serialized payload. A missing token means the orchestrator did
        # not read the supplied system prompt.
        challenge = packet.system_prompt_challenge
        if challenge:
            import json as _json

            serialized = _json.dumps(payload, ensure_ascii=False)
            if challenge not in serialized:
                return _error_result_with_next(
                    "submit_work_result",
                    code="system_prompt_not_honored",
                    message=(
                        "The required attention token from the packet's "
                        "system_prompt is missing from your output. This "
                        "indicates the system_prompt was not read. Re-read the "
                        "packet's system_prompt and include the exact token "
                        "(see the 'ATTENTION CHECK' line at the end of the "
                        "system_prompt) in a free-text field of your JSON."
                    ),
                    exc=ValueError("system_prompt_challenge"),
                    next_suggested_tools=["get_work_packet"],
                )

        existing_ids = {result.work_result_id for result in self.work_store.list_results()}
        result = self.work_store.submit_result(
            packet.work_packet_id,
            payload=payload,
            producer=producer,
            warnings=warnings,
        )
        duplicate = result.work_result_id in existing_ids
        # M2 hardening: mark the dispatch token consumed so it cannot
        # authorize a second, different submission. consume() is
        # idempotent, so an idempotent retry is harmless.
        if packet.delegation_required:
            _consumed_token = getattr(producer, "subagent_token", None)
            if _consumed_token:
                self.subagent_token_store.consume(
                    token=_consumed_token,
                    work_packet_id=packet.work_packet_id,
                )
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
        _, _gate_error = self._load_run_and_gate("commit_source_card", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        _, _gate_error = self._load_run_and_gate("prepare_task_spec", agent_run_id)
        if _gate_error is not None:
            return _gate_error

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
        packet = self._save_model_packet(
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
        _, _gate_error = self._load_run_and_gate("commit_task_spec", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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

        _, _gate_error = self._load_run_and_gate("prepare_topics", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        packet = self._save_model_packet(
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
        _, _gate_error = self._load_run_and_gate("commit_topics", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        candidate_topics = [asdict(candidate) for candidate in topic_result.candidates]
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
                "candidate_topics": candidate_topics,
                "requires_user_topic_selection": True,
                "selection_contract": (
                    "Present candidate_topics to the user and call select_topic "
                    "only after the user chooses one. Pass user_selection_evidence "
                    "summarizing the user's choice."
                ),
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
        user_selection_evidence: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("select_topic", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        selection_evidence = (user_selection_evidence or "").strip()
        if not selection_evidence:
            return _error_result_with_next(
                "select_topic",
                code="topic_selection_user_confirmation_required",
                message=(
                    "select_topic requires user_selection_evidence. Present the "
                    "committed topic options to the user and pass a concise record "
                    "of the user's chosen topic."
                ),
                exc=ValueError("user_selection_evidence"),
                next_suggested_tools=["select_topic", "reject_topic"],
            )
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
                "user_selection_evidence": selection_evidence,
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
        _, _gate_error = self._load_run_and_gate("reject_topic", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        _, _gate_error = self._load_run_and_gate("create_research_plan", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        _, _gate_error = self._load_run_and_gate("prepare_research_notes", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        # Gap (4): a large source-packet bundle must be read by a subagent
        # so the deep source text is not absorbed into the orchestrator.
        research_notes_delegation_required = (
            total_packet_chars > RESEARCH_NOTES_DELEGATION_REQUIRED_CHARS
        )
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
        packet = self._save_model_packet(
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
                delegation_required=research_notes_delegation_required,
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
        _, _gate_error = self._load_run_and_gate("commit_research_notes", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        _, _gate_error = self._load_run_and_gate("prepare_outline", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        packet = self._save_model_packet(
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
        _, _gate_error = self._load_run_and_gate("commit_outline", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        _, _gate_error = self._load_run_and_gate("prepare_draft", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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

        writing_style_payload = self._load_writing_style_payload_for_job(job_id)
        user_blocks = build_drafting_user_blocks(
            task_spec,
            selected_topic,
            research_result.evidence_map,
            outline,
            source_packets,
            writing_style_payload,
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
        packet = self._save_model_packet(
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
            warnings=self._writing_style_skip_warnings(job_id),
            next_suggested_tools=["submit_work_result"],
        )

    def commit_draft(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("commit_draft", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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

        next_tools = ["prepare_style_revision", "prepare_validation"]
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
                current_phase="style_revision",
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

    def prepare_style_revision(
        self,
        job_id: str,
        source_draft_id: str | None = None,
        *,
        source_packet_bundle_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("prepare_style_revision", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        try:
            job = self.stores.workflow.load_job(job_id)
        except KeyError as exc:
            return _error_result(
                "prepare_style_revision",
                code="job_not_found",
                message=f"EssayJob not found: {job_id}",
                exc=exc,
            )
        if job.task_spec_id is None:
            return _error_result_with_next(
                "prepare_style_revision",
                code="job_task_spec_missing",
                message=f"job {job_id} does not have a committed task_spec_id",
                exc=ValueError("task_spec_id"),
                next_suggested_tools=["prepare_task_spec"],
            )
        try:
            task_spec = self.stores.task_store.load_latest(str(job.task_spec_id))
            research_result = self.stores.research_store.load_latest(job_id)
            outline = self.stores.outline_store.load_latest(job_id)
            previous_draft = _load_draft_for_job(
                self.stores,
                job_id=job_id,
                draft_id=source_draft_id,
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "prepare_style_revision",
                code="style_revision_artifacts_missing",
                message=f"job {job_id} is missing style-revision prerequisite artifacts",
                exc=exc,
                next_suggested_tools=["prepare_draft"],
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
                    "prepare_style_revision",
                    code="source_packet_bundle_not_found",
                    message=f"SourcePacketBundle not found: {effective_bundle_id}",
                    exc=exc,
                    next_suggested_tools=["resolve_source_requests"],
                )
            if bundle.scope != f"job:{job_id}":
                return _error_result(
                    "prepare_style_revision",
                    code="source_packet_bundle_job_mismatch",
                    message=(
                        f"source packet bundle {effective_bundle_id} does not belong to job {job_id}"
                    ),
                    exc=ValueError(effective_bundle_id),
                )
            packets_result = _source_text_packets_from_bundle(
                bundle,
                tool_name="prepare_style_revision",
            )
            if isinstance(packets_result, ToolResult):
                return packets_result
            source_packets = packets_result

        det = run_validation_deterministic_checks(previous_draft.content)
        writing_style_payload = self._load_writing_style_payload_for_job(job_id)
        artifact_refs = {
            "job_id": job_id,
            "task_spec_id": task_spec.id,
            "evidence_map_id": research_result.evidence_map.id,
            "outline_id": outline.id,
            "source_draft_id": previous_draft.id,
            "source_draft_version": previous_draft.version,
        }
        if effective_bundle_id is not None:
            artifact_refs["source_packet_bundle_id"] = effective_bundle_id

        common_context = {
            "job_id": job_id,
            "task_spec_id": task_spec.id,
            "selected_topic_id": previous_draft.selected_topic_id,
            "evidence_map_id": research_result.evidence_map.id,
            "outline_id": outline.id,
            "source_draft_id": previous_draft.id,
            "source_draft_version": previous_draft.version,
            "source_packet_bundle_id": effective_bundle_id,
            "deterministic": asdict(det),
        }

        if should_window_style_revision(previous_draft.content):
            return self._prepare_windowed_style_revision_plan(
                job_id=job_id,
                previous_draft=previous_draft,
                task_spec=task_spec,
                outline=outline,
                evidence_map=research_result.evidence_map,
                source_packets=source_packets,
                source_packet_bundle_id=effective_bundle_id,
                writing_style_payload=writing_style_payload,
                det=det,
                artifact_refs=artifact_refs,
                common_context=common_context,
                agent_run_id=agent_run_id,
            )

        user_blocks = build_style_revision_user_blocks(
            task_spec=task_spec,
            draft=previous_draft,
            outline=outline,
            evidence_map=research_result.evidence_map,
            source_packets=source_packets,
            det=det,
            writing_style_payload=writing_style_payload,
        )
        prompt_blocks = [
            PromptBlock(text=block.text, cacheable=block.cacheable)
            for block in user_blocks
        ]
        packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "style_revision",
            short_hash(
                [
                    previous_draft.id,
                    previous_draft.version,
                    effective_bundle_id,
                    [block.text for block in prompt_blocks],
                ]
            ),
        )
        packet = self._save_model_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="style_revision",
                scope=f"job:{job_id}",
                instructions=(
                    "Rewrite the supplied draft as a prose-only style pass guided by the anti-AI "
                    "writing skill embedded in the system_prompt. Preserve meaning, facts, citations, "
                    "source grounding, section_source_map, and bibliography_candidates. "
                    "Return JSON matching response_schema; do not commit it."
                ),
                system_prompt=STYLE_REVISION_SYSTEM_PROMPT,
                prompt_blocks=prompt_blocks,
                response_schema=dict(STYLE_REVISION_SCHEMA),
                context=common_context,
                artifact_refs=artifact_refs,
                commit_tool="commit_style_revision",
                delegation=DelegationHint(
                    recommended=False,
                    reason=(
                        "style revision rewrites the whole draft as prose; the orchestrator "
                        "must apply the embedded anti-AI skill end-to-end"
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
                current_phase="style_revision",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_style_revision",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "job_id": job_id,
                "source_draft_id": previous_draft.id,
                "source_draft_version": previous_draft.version,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "deterministic": asdict(det),
                "windowing": {"mode": "single"},
                "next_suggested_tools": ["submit_work_result"],
            },
            warnings=self._writing_style_skip_warnings(job_id),
            next_suggested_tools=["submit_work_result"],
        )

    def _prepare_windowed_style_revision_plan(
        self,
        *,
        job_id: str,
        previous_draft,
        task_spec,
        outline,
        evidence_map,
        source_packets,
        source_packet_bundle_id,
        writing_style_payload,
        det,
        artifact_refs: dict,
        common_context: dict,
        agent_run_id: str | None,
    ) -> ToolResult:
        windows = plan_style_revision_windows(previous_draft.content)
        windows_payload = [window.as_dict() for window in windows]
        parent_packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "style_revision_plan",
            short_hash(
                [
                    previous_draft.id,
                    previous_draft.version,
                    source_packet_bundle_id,
                    windows_payload,
                ]
            ),
        )
        parent_context = {
            **common_context,
            "windowing": {
                "mode": "windowed",
                "target_window_words": DEFAULT_TARGET_WINDOW_WORDS,
                "threshold_words": DEFAULT_WINDOWED_REVISION_WORD_THRESHOLD,
                "total_windows": len(windows),
                "windows": windows_payload,
            },
        }
        parent_packet = self._save_model_packet(
            WorkPacket(
                work_packet_id=parent_packet_id,
                stage="style_revision_plan",
                scope=f"job:{job_id}",
                instructions=(
                    "Long draft detected. The style-revision pass is split into windows. "
                    "Call prepare_style_revision_window for each window index in "
                    "windowing.windows, submit each result, then call commit_style_revision "
                    "with the ordered list of work_result_ids."
                ),
                system_prompt=STYLE_REVISION_SYSTEM_PROMPT,
                prompt_blocks=[],
                response_schema={},
                context=parent_context,
                artifact_refs=artifact_refs,
                commit_tool=None,
                delegation=DelegationHint(
                    recommended=False,
                    reason="windowed style revision is orchestrated by the main agent",
                    allowed_tools=["prepare_style_revision_window"],
                    return_contract=None,
                ),
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                parent_packet.work_packet_id,
                current_phase="style_revision",
                next_suggested_tools=["prepare_style_revision_window"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_style_revision",
            data={
                "parent_packet_id": parent_packet.work_packet_id,
                "stage": parent_packet.stage,
                "job_id": job_id,
                "source_draft_id": previous_draft.id,
                "source_draft_version": previous_draft.version,
                "windowing": {
                    "mode": "windowed",
                    "total_windows": len(windows),
                    "windows": windows_payload,
                    "threshold_words": DEFAULT_WINDOWED_REVISION_WORD_THRESHOLD,
                    "target_window_words": DEFAULT_TARGET_WINDOW_WORDS,
                },
                "deterministic": asdict(det),
                "artifact_refs": dict(artifact_refs),
                "next_suggested_tools": ["prepare_style_revision_window"],
            },
            warnings=self._writing_style_skip_warnings(job_id),
            next_suggested_tools=["prepare_style_revision_window"],
        )

    def prepare_style_revision_window(
        self,
        parent_packet_id: str,
        window_index: int,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("prepare_style_revision_window", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        try:
            parent_packet = self.work_store.load_packet(parent_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "prepare_style_revision_window",
                code="parent_packet_not_found",
                message=f"parent work packet not found: {parent_packet_id}",
                exc=exc,
            )
        if parent_packet.stage != "style_revision_plan":
            return _error_result(
                "prepare_style_revision_window",
                code="wrong_parent_packet_stage",
                message=(
                    "parent packet is not a style_revision_plan packet; got "
                    f"{parent_packet.stage}"
                ),
                exc=ValueError(parent_packet.stage),
            )
        windowing = parent_packet.context.get("windowing") or {}
        windows_payload = list(windowing.get("windows", []))
        total = len(windows_payload)
        if not 0 <= window_index < total:
            return _error_result(
                "prepare_style_revision_window",
                code="window_index_out_of_range",
                message=f"window_index {window_index} is out of range (total={total})",
                exc=ValueError(window_index),
            )
        window_meta = windows_payload[window_index]
        packet_job_id = parent_packet.context.get("job_id")
        if not isinstance(packet_job_id, str) or not packet_job_id:
            return _error_result(
                "prepare_style_revision_window",
                code="job_id_missing",
                message="parent style_revision_plan packet is missing job_id",
                exc=ValueError("job_id"),
            )
        source_draft_id = parent_packet.context.get("source_draft_id")
        if not isinstance(source_draft_id, str) or not source_draft_id:
            return _error_result(
                "prepare_style_revision_window",
                code="source_draft_id_missing",
                message="parent style_revision_plan packet is missing source_draft_id",
                exc=ValueError("source_draft_id"),
            )
        try:
            previous_draft = self.stores.draft_store.find_by_id(packet_job_id, source_draft_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "prepare_style_revision_window",
                code="style_revision_artifacts_missing",
                message=f"job {packet_job_id} is missing the source draft for windowed revision",
                exc=exc,
                next_suggested_tools=["prepare_style_revision"],
            )

        paragraphs = split_paragraphs(previous_draft.content)
        start = int(window_meta["paragraph_start"])
        end = int(window_meta["paragraph_end"])
        window_text = "\n\n".join(paragraphs[start:end])
        prev_paragraph = paragraphs[start - 1] if start > 0 else None
        next_paragraph = paragraphs[end] if end < len(paragraphs) else None
        window_det = run_validation_deterministic_checks(window_text)
        whole_det = run_validation_deterministic_checks(previous_draft.content)
        # Whole-draft structural context — the per-window LLM cannot see paragraph
        # length variance or the first-sentence chain otherwise. Without this, the
        # soft-tier anti-AI rules ("paragraph length variance", "argument advancement")
        # are structurally invisible at revision time.
        whole_draft_context = {
            "paragraph_count": len(paragraphs),
            "paragraph_word_counts": [len(p.split()) for p in paragraphs],
            "first_sentence_chain": list(
                whole_det.soft_tier.paragraph_first_sentences
            ),
            "paragraphs_under_50_words": whole_det.soft_tier.paragraphs_under_50_words,
            "paragraphs_opening_with_topic_sentence": whole_det.soft_tier.paragraphs_opening_with_topic_sentence,
            "filler_phrase_hits": [
                {"phrase": h.word, "count": h.count}
                for h in whole_det.soft_tier.filler_phrase_hits
            ],
            "significance_inflation_hits": [
                {"phrase": h.word, "count": h.count}
                for h in whole_det.soft_tier.significance_inflation_hits
            ],
            "vague_attribution_hits": [
                {"phrase": h.word, "count": h.count}
                for h in whole_det.soft_tier.vague_attribution_hits
            ],
            "concrete_engagement_present_in_whole_draft": whole_det.concrete_engagement_present,
        }

        instructions = (
            f"You are rewriting WINDOW {window_index + 1} of {total} of a long essay's prose-only "
            "style pass. Return JSON whose 'content' field contains ONLY the revised text for this "
            "window's paragraphs, in the same paragraph order. Do not output text for other windows. "
            "Preserve every claim, citation, and quoted source phrase in this window. Apply the "
            "anti-AI skill in the system_prompt verbatim. If a writing-style block was attached to "
            "the job, the user's voice wins over soft-tier heuristics (hard-tier rules still apply). "
            "The whole_draft_context block reports paragraph counts and the first-sentence chain for "
            "the ENTIRE essay so structural patterns are visible. If `paragraphs_under_50_words == 0` "
            "and you can plausibly split or shorten a paragraph in your window without losing meaning, "
            "do so. If your window covers the first or last paragraph, prefer it for short-paragraph "
            "variety so the introduction or conclusion does not run uniformly long."
        )
        window_user_payload = {
            "window_index": window_index,
            "total_windows": total,
            "paragraph_start": start,
            "paragraph_end": end,
            "window_word_count": int(window_meta.get("word_count", len(window_text.split()))),
            "previous_window_last_paragraph": prev_paragraph,
            "next_window_first_paragraph": next_paragraph,
            "window_text": window_text,
            "window_deterministic_findings": asdict(window_det),
            "whole_draft_context": whole_draft_context,
        }
        import json as _json

        prompt_blocks = [
            PromptBlock(text=_json.dumps(window_user_payload, ensure_ascii=False), cacheable=False)
        ]
        writing_style_payload = self._load_writing_style_payload_for_job(packet_job_id)
        if writing_style_payload is not None:
            from essay_writer.writing_style.prompts import (
                build_writing_style_prompt_block,
            )

            prompt_blocks.append(
                PromptBlock(
                    text="\n\n" + build_writing_style_prompt_block(writing_style_payload),
                    cacheable=False,
                )
            )
        packet_id = timestamp_id(
            "workpkt",
            "job",
            packet_job_id,
            "style_revision_window",
            short_hash([parent_packet_id, window_index, window_text]),
        )
        artifact_refs = {
            **dict(parent_packet.artifact_refs),
            "parent_packet_id": parent_packet_id,
            "window_index": window_index,
        }
        packet = self._save_model_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="style_revision_window",
                scope=f"job:{packet_job_id}",
                instructions=instructions,
                system_prompt=STYLE_REVISION_SYSTEM_PROMPT,
                prompt_blocks=prompt_blocks,
                response_schema=dict(STYLE_REVISION_SCHEMA),
                context={
                    **dict(parent_packet.context),
                    "parent_packet_id": parent_packet_id,
                    "window_index": window_index,
                    "paragraph_start": start,
                    "paragraph_end": end,
                    "window_word_count": window_user_payload["window_word_count"],
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_style_revision",
                delegation=DelegationHint(
                    recommended=True,
                    reason=(
                        "windowed anti-AI rewrite benefits from a bounded subagent with only the "
                        "anti-AI skill in its context; the orchestrator must still submit window "
                        "results in order and call commit_style_revision"
                    ),
                    suggested_role="anti_ai_window_reviser",
                    allowed_tools=["submit_work_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema. content must contain "
                        "ONLY this window's revised paragraphs."
                    ),
                    subagent_prompt=(
                        "You are a bounded prose-only style reviser. The system prompt you receive "
                        "contains the full anti-AI writing skill. Apply it. Use whole_draft_context "
                        "to break the uniform-paragraph-shape and topic-sentence-opener patterns "
                        "the parent draft falls into. Return JSON matching response_schema and stop."
                    ),
                ),
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="style_revision",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_style_revision_window",
            data={
                "work_packet_id": packet.work_packet_id,
                "stage": packet.stage,
                "parent_packet_id": parent_packet_id,
                "window_index": window_index,
                "total_windows": total,
                "paragraph_start": start,
                "paragraph_end": end,
                "commit_tool": packet.commit_tool,
                "delegation": asdict(packet.delegation),
                "response_schema": packet.response_schema,
                "system_prompt": packet.system_prompt,
                "prompt_blocks": [asdict(block) for block in packet.prompt_blocks],
                "instructions": packet.instructions,
                "artifact_refs": dict(packet.artifact_refs),
                "deterministic": asdict(window_det),
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_style_revision(
        self,
        work_result_id: str | None = None,
        *,
        work_result_ids: list[str] | None = None,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("commit_style_revision", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        if work_result_ids:
            return self._commit_windowed_style_revision(
                work_result_ids=list(work_result_ids),
                agent_run_id=agent_run_id,
            )
        if not work_result_id:
            return _error_result(
                "commit_style_revision",
                code="work_result_id_required",
                message="commit_style_revision requires work_result_id (single) or work_result_ids (windowed)",
                exc=ValueError("work_result_id"),
            )
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_style_revision",
                code="work_result_not_found",
                message=f"WorkResult not found or incomplete: {work_result_id}",
                exc=exc,
            )
        if packet.commit_tool != "commit_style_revision":
            return _error_result(
                "commit_style_revision",
                code="wrong_commit_tool",
                message=f"expected commit_style_revision packet, got {packet.commit_tool}",
                exc=ValueError(packet.commit_tool),
            )
        validation_error = _validate_work_payload(
            result.payload,
            STYLE_REVISION_SCHEMA,
            tool_name="commit_style_revision",
        )
        if validation_error is not None:
            return validation_error
        packet_job_id = packet.context.get("job_id") or packet.artifact_refs.get("job_id")
        if not isinstance(packet_job_id, str) or not packet_job_id:
            return _error_result(
                "commit_style_revision",
                code="job_id_missing",
                message="style-revision packet is missing job_id",
                exc=ValueError("job_id"),
            )
        try:
            source_draft_id = str(packet.context["source_draft_id"])
            previous_draft = self.stores.draft_store.find_by_id(packet_job_id, source_draft_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "commit_style_revision",
                code="style_revision_artifacts_missing",
                message=(
                    f"job {packet_job_id} is missing style-revision prerequisite artifacts"
                ),
                exc=exc,
                next_suggested_tools=["prepare_style_revision"],
            )

        scope = f"job:{packet_job_id}"
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="style_revision")
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
                        "commit_style_revision",
                        code="style_revision_commit_artifact_missing",
                        message="Committed style-revision artifact is missing",
                        exc=exc,
                    )
            else:
                return _error_result(
                    "commit_style_revision",
                    code="style_revision_commit_artifact_missing",
                    message="Committed style-revision artifact is missing draft_version",
                    exc=KeyError(existing_commit.commit_id),
                )
            commit = existing_commit
        else:
            content = str(result.payload.get("content", "")).strip()
            if not content:
                return _error_result(
                    "commit_style_revision",
                    code="style_revision_empty_content",
                    message="style-revision payload must include non-empty rewritten content",
                    exc=ValueError("content"),
                )
            content_det = run_validation_deterministic_checks(content)
            violations = hard_tier_anti_ai_violations(content_det)
            if violations:
                return ToolResult(
                    ok=False,
                    tool_name="commit_style_revision",
                    data={
                        "anti_ai_violations": violations,
                        "deterministic": asdict(content_det),
                        "next_suggested_tools": ["prepare_style_revision"],
                    },
                    error=ToolError(
                        code="anti_ai_hard_tier_violation",
                        message=(
                            "style-revision output violates hard-tier anti-AI rules; "
                            "see anti_ai_violations for the specific patterns"
                        ),
                        detail={"violations": violations},
                    ),
                    next_suggested_tools=["prepare_style_revision"],
                )
            risks = [
                str(item).strip()
                for item in result.payload.get("known_risks", [])
                if isinstance(item, (str, int, float)) and str(item).strip()
            ]
            weak_spots = risks if risks else list(previous_draft.known_weak_spots)
            draft_version = self.stores.draft_store.next_version(packet_job_id)
            draft = replace(
                previous_draft,
                id=f"draft_{uuid4().hex[:12]}",
                version=draft_version,
                content=content,
                known_weak_spots=weak_spots,
                origin="style_revision",
                created_by="system",
                parent_draft_id=previous_draft.id,
                parent_export_id=None,
                manual_request_id=None,
                user_instruction=None,
                selected_lenses=[],
                prompt_version="drafting-style-revision-v1",
                created_at=utc_now_iso(),
            )
            try:
                self.stores.draft_store.save(draft)
                self.stores.workflow.record_draft_ready(
                    job_id=packet_job_id,
                    draft=draft,
                )
            except (FileExistsError, TopicSelectionError) as exc:
                return _error_result(
                    "commit_style_revision",
                    code="style_revision_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
            artifact_refs = {
                "job_id": packet_job_id,
                "evidence_map_id": str(packet.context.get("evidence_map_id", "")),
                "outline_id": str(packet.context.get("outline_id", "")),
                "source_draft_id": previous_draft.id,
                "source_draft_version": previous_draft.version,
                "draft_id": draft.id,
                "draft_version": draft_version,
            }
            source_packet_bundle_id = packet.context.get("source_packet_bundle_id")
            if isinstance(source_packet_bundle_id, str) and source_packet_bundle_id:
                artifact_refs["source_packet_bundle_id"] = source_packet_bundle_id
            commit = self.work_store.save_commit(
                scope=scope,
                stage="style_revision",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )

        # After the style-revision pass, the workflow should run the bounded
        # anti-AI audit before validation. The audit is the forcing function
        # that makes the soft-tier checks visible; validation can still be
        # called directly if the user opts out.
        next_tools = ["prepare_anti_ai_audit", "prepare_validation"]
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
                current_phase="anti_ai_audit",
                decision="style_revision_committed",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_style_revision",
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

    def _commit_windowed_style_revision(
        self,
        *,
        work_result_ids: list[str],
        agent_run_id: str | None,
    ) -> ToolResult:
        if not work_result_ids:
            return _error_result(
                "commit_style_revision",
                code="work_result_ids_empty",
                message="commit_style_revision windowed path requires non-empty work_result_ids",
                exc=ValueError("work_result_ids"),
            )
        # Load each result + packet and verify they all belong to the same parent plan
        loaded: list[tuple[object, object]] = []
        parent_packet_id: str | None = None
        packet_job_id: str | None = None
        for work_result_id in work_result_ids:
            try:
                result = self.work_store.load_result(work_result_id)
                packet = self.work_store.load_packet(result.work_packet_id)
            except (KeyError, FileNotFoundError) as exc:
                return _error_result(
                    "commit_style_revision",
                    code="work_result_not_found",
                    message=f"WorkResult not found or incomplete: {work_result_id}",
                    exc=exc,
                )
            if packet.stage != "style_revision_window":
                return _error_result(
                    "commit_style_revision",
                    code="wrong_work_packet_stage",
                    message=(
                        "commit_style_revision windowed path requires style_revision_window "
                        f"packets; got {packet.stage}"
                    ),
                    exc=ValueError(packet.stage),
                )
            this_parent = packet.context.get("parent_packet_id")
            this_job = packet.context.get("job_id")
            if not isinstance(this_parent, str) or not this_parent:
                return _error_result(
                    "commit_style_revision",
                    code="parent_packet_id_missing",
                    message="style_revision_window packet is missing parent_packet_id",
                    exc=ValueError("parent_packet_id"),
                )
            if parent_packet_id is None:
                parent_packet_id = this_parent
                packet_job_id = this_job if isinstance(this_job, str) else None
            elif this_parent != parent_packet_id:
                return _error_result(
                    "commit_style_revision",
                    code="window_results_from_different_plans",
                    message="all windowed work_result_ids must share one parent_packet_id",
                    exc=ValueError(this_parent),
                )
            loaded.append((result, packet))

        try:
            parent_packet = self.work_store.load_packet(parent_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_style_revision",
                code="parent_packet_not_found",
                message=f"parent style_revision_plan packet not found: {parent_packet_id}",
                exc=exc,
            )
        windowing = parent_packet.context.get("windowing") or {}
        total_windows = int(windowing.get("total_windows", 0))
        if total_windows == 0:
            return _error_result(
                "commit_style_revision",
                code="window_plan_invalid",
                message="parent style_revision_plan packet has no windows",
                exc=ValueError("windowing"),
            )

        # Validate each payload against the per-window schema
        for result, _packet in loaded:
            validation_error = _validate_work_payload(
                result.payload,
                STYLE_REVISION_SCHEMA,
                tool_name="commit_style_revision",
            )
            if validation_error is not None:
                return validation_error

        # Sort by window_index
        ordered = sorted(loaded, key=lambda pair: int(pair[1].context.get("window_index", -1)))
        seen_indices = [int(packet.context.get("window_index", -1)) for _r, packet in ordered]
        expected_indices = list(range(total_windows))
        if seen_indices != expected_indices:
            return _error_result(
                "commit_style_revision",
                code="window_results_incomplete_or_duplicated",
                message=(
                    f"windowed commit requires exactly one result per window 0..{total_windows - 1}; "
                    f"got {seen_indices}"
                ),
                exc=ValueError("work_result_ids"),
            )

        if packet_job_id is None or not packet_job_id:
            return _error_result(
                "commit_style_revision",
                code="job_id_missing",
                message="windowed style_revision packets are missing job_id",
                exc=ValueError("job_id"),
            )

        source_draft_id_obj = parent_packet.context.get("source_draft_id")
        if not isinstance(source_draft_id_obj, str) or not source_draft_id_obj:
            return _error_result(
                "commit_style_revision",
                code="source_draft_id_missing",
                message="parent style_revision_plan packet is missing source_draft_id",
                exc=ValueError("source_draft_id"),
            )
        try:
            previous_draft = self.stores.draft_store.find_by_id(packet_job_id, source_draft_id_obj)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "commit_style_revision",
                code="style_revision_artifacts_missing",
                message=f"job {packet_job_id} is missing the source draft for windowed revision",
                exc=exc,
                next_suggested_tools=["prepare_style_revision"],
            )

        scope = f"job:{packet_job_id}"
        commit_signature_hash = short_hash(
            [result.work_result_id for result, _packet in ordered]
        )
        # idempotency: same set of result ids already produced a commit
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="style_revision")
                if commit.artifact_refs.get("window_signature_hash") == commit_signature_hash
            ),
            None,
        )
        already_committed = existing_commit is not None
        if existing_commit is not None:
            draft_version = existing_commit.artifact_refs.get("draft_version")
            if not isinstance(draft_version, int):
                return _error_result(
                    "commit_style_revision",
                    code="style_revision_commit_artifact_missing",
                    message="Committed windowed style-revision artifact is missing draft_version",
                    exc=KeyError(existing_commit.commit_id),
                )
            try:
                draft = self.stores.draft_store.load(packet_job_id, draft_version)
            except KeyError as exc:
                return _error_result(
                    "commit_style_revision",
                    code="style_revision_commit_artifact_missing",
                    message="Committed windowed style-revision artifact is missing",
                    exc=exc,
                )
            commit_record = existing_commit
        else:
            window_texts = [
                str(result.payload.get("content", "")).strip()
                for result, _packet in ordered
            ]
            if any(not text for text in window_texts):
                missing = [idx for idx, text in enumerate(window_texts) if not text]
                return _error_result(
                    "commit_style_revision",
                    code="style_revision_empty_content",
                    message=(
                        f"windowed style-revision is missing content for window indices: {missing}"
                    ),
                    exc=ValueError("content"),
                )

            per_window_violations: list[dict[str, object]] = []
            for idx, text in enumerate(window_texts):
                violations = hard_tier_anti_ai_violations(
                    run_validation_deterministic_checks(text)
                )
                if violations:
                    per_window_violations.append(
                        {"window_index": idx, "violations": violations}
                    )
            if per_window_violations:
                offending_indices = [
                    entry["window_index"] for entry in per_window_violations
                ]
                return ToolResult(
                    ok=False,
                    tool_name="commit_style_revision",
                    data={
                        "offending_window_indices": offending_indices,
                        "per_window_violations": per_window_violations,
                        "next_suggested_tools": ["prepare_style_revision_window"],
                    },
                    error=ToolError(
                        code="anti_ai_hard_tier_violation",
                        message=(
                            "windowed style-revision output violates hard-tier anti-AI rules; "
                            "re-prepare and re-submit only the offending windows"
                        ),
                        detail={"per_window_violations": per_window_violations},
                    ),
                    next_suggested_tools=["prepare_style_revision_window"],
                )

            assembled = assemble_window_outputs(window_texts)
            risks: list[str] = []
            for result, _packet in ordered:
                for item in result.payload.get("known_risks", []):
                    if isinstance(item, (str, int, float)) and str(item).strip():
                        risks.append(str(item).strip())
            weak_spots = risks if risks else list(previous_draft.known_weak_spots)
            draft_version = self.stores.draft_store.next_version(packet_job_id)
            draft = replace(
                previous_draft,
                id=f"draft_{uuid4().hex[:12]}",
                version=draft_version,
                content=assembled,
                known_weak_spots=weak_spots,
                origin="style_revision",
                created_by="system",
                parent_draft_id=previous_draft.id,
                parent_export_id=None,
                manual_request_id=None,
                user_instruction=None,
                selected_lenses=[],
                prompt_version="drafting-style-revision-windowed-v1",
                created_at=utc_now_iso(),
            )
            try:
                self.stores.draft_store.save(draft)
                self.stores.workflow.record_draft_ready(
                    job_id=packet_job_id,
                    draft=draft,
                )
            except (FileExistsError, TopicSelectionError) as exc:
                return _error_result(
                    "commit_style_revision",
                    code="style_revision_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
            artifact_refs = {
                "job_id": packet_job_id,
                "source_draft_id": previous_draft.id,
                "source_draft_version": previous_draft.version,
                "draft_id": draft.id,
                "draft_version": draft_version,
                "parent_packet_id": parent_packet_id,
                "total_windows": total_windows,
                "window_signature_hash": commit_signature_hash,
            }
            commit_record = self.work_store.save_commit(
                scope=scope,
                stage="style_revision",
                work_packet_id=parent_packet_id,
                work_result_id=ordered[0][0].work_result_id,
                artifact_refs=artifact_refs,
            )

        next_tools = ["prepare_validation"]
        if agent_run_id is not None:
            for result, _packet in ordered:
                self.run_store.attach_work_result(
                    agent_run_id,
                    result.work_result_id,
                    work_packet_id=result.work_packet_id,
                    next_suggested_tools=next_tools,
                )
            self.run_store.attach_commit(
                agent_run_id,
                dict(commit_record.artifact_refs),
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="validation",
                decision="style_revision_windowed_committed",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_style_revision",
            data={
                "commit_id": commit_record.commit_id,
                "work_result_ids": [result.work_result_id for result, _packet in ordered],
                "job_id": packet_job_id,
                "draft_id": draft.id,
                "draft": asdict(draft),
                "artifact_refs": dict(commit_record.artifact_refs),
                "already_committed": already_committed,
                "windowing": {"mode": "windowed", "total_windows": total_windows},
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
        _, _gate_error = self._load_run_and_gate("prepare_revision", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        writing_style_payload = self._load_writing_style_payload_for_job(job_id)
        user_blocks = build_revision_user_blocks(
            task_spec=task_spec,
            selected_topic=selected_topic,
            evidence_map=research_result.evidence_map,
            outline=outline,
            previous_draft=previous_draft,
            validation=validation,
            source_packets=source_packets,
            writing_style_payload=writing_style_payload,
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
        packet = self._save_model_packet(
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
            warnings=self._writing_style_skip_warnings(job_id),
            next_suggested_tools=["submit_work_result"],
        )

    def commit_revision(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("commit_revision", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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

            revised_content = str(result.payload.get("content", "")).strip()
            if revised_content:
                revision_det = run_validation_deterministic_checks(revised_content)
                revision_violations = hard_tier_anti_ai_violations(revision_det)
                if revision_violations:
                    return ToolResult(
                        ok=False,
                        tool_name="commit_revision",
                        data={
                            "anti_ai_violations": revision_violations,
                            "deterministic": asdict(revision_det),
                            "next_suggested_tools": ["prepare_revision"],
                        },
                        error=ToolError(
                            code="anti_ai_hard_tier_violation",
                            message=(
                                "revision output violates hard-tier anti-AI rules; "
                                "see anti_ai_violations for the specific patterns"
                            ),
                            detail={"violations": revision_violations},
                        ),
                        next_suggested_tools=["prepare_revision"],
                    )

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

        # A revision produces a NEW draft whose anti_ai_self_check is reset, so
        # the require_anti_ai_audit gate refuses prepare_validation until the
        # revised draft is re-audited. Route to the audit first, mirroring
        # commit_style_revision and save_user_edit (bug_014).
        next_tools = ["prepare_anti_ai_audit", "prepare_validation"]
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
                current_phase="anti_ai_audit",
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

    def prepare_anti_ai_audit(
        self,
        job_id: str,
        draft_id: str | None = None,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        """Run a bounded single-skill anti-AI audit on a committed draft.

        The audit stage exists so the LLM cannot skip the anti-AI self-check
        the way it can when the skill is buried in a multi-goal drafting prompt.
        The audit packet's system prompt is ONLY the anti-AI skill. The
        response schema FORCES the model to fill the seven self-check fields
        and grade each writing-style guidance bullet."""
        import json as _json

        _, _gate_error = self._load_run_and_gate("prepare_anti_ai_audit", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        try:
            if draft_id is None:
                draft = self.stores.draft_store.load_latest(job_id)
            else:
                draft = self.stores.draft_store.find_by_id(job_id, draft_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result_with_next(
                "prepare_anti_ai_audit",
                code="draft_not_found",
                message=f"draft not found for job {job_id}",
                exc=exc,
                next_suggested_tools=["prepare_draft"],
            )

        det = run_validation_deterministic_checks(draft.content)
        skill_manifest = anti_ai_skill_manifest()
        paragraphs = [p for p in draft.content.split("\n\n") if p.strip()]
        whole_draft_context = {
            "paragraph_count": len(paragraphs),
            "paragraph_word_counts": [len(p.split()) for p in paragraphs],
            "first_sentence_chain": list(det.soft_tier.paragraph_first_sentences),
            "paragraphs_under_50_words": det.soft_tier.paragraphs_under_50_words,
            "paragraphs_opening_with_topic_sentence": det.soft_tier.paragraphs_opening_with_topic_sentence,
        }

        # Style-guidance checklist (one row per bullet). If the user attached a
        # writing-style content to the job, those bullets are what the audit
        # grades against.
        writing_style_payload = self._load_writing_style_payload_for_job(job_id)
        guidance_bullets: list[dict[str, str]] = []
        if writing_style_payload is not None:
            content = writing_style_payload.style_content
            for idx, bullet in enumerate(content.guidance, start=1):
                guidance_bullets.append({"id": f"guidance-{idx}", "bullet": bullet})
            for idx, bullet in enumerate(content.preferred_moves, start=1):
                guidance_bullets.append({"id": f"preferred-{idx}", "bullet": f"PREFERRED MOVE: {bullet}"})
            for idx, bullet in enumerate(content.avoid_moves, start=1):
                guidance_bullets.append({"id": f"avoid-{idx}", "bullet": f"AVOID MOVE: {bullet}"})
            for idx, bullet in enumerate(content.structural_habits, start=1):
                guidance_bullets.append({"id": f"structure-{idx}", "bullet": f"STRUCTURAL HABIT: {bullet}"})

        user_payload = {
            "draft_id": draft.id,
            "draft_version": draft.version,
            "draft_sha256": draft_sha256(draft.content),
            "essay_content": draft.content,
            "skill_contract": {
                "skill_file": skill_manifest["path"],
                "skill_sha256": skill_manifest["sha256"],
                "skill_line_count": skill_manifest["line_count"],
            },
            "skill_line_manifest": skill_manifest["lines"],
            "deterministic_findings": asdict(det),
            "whole_draft_context": whole_draft_context,
            "style_guidance_checklist": guidance_bullets,
        }

        prompt_blocks = [
            PromptBlock(text=_json.dumps(user_payload, ensure_ascii=False), cacheable=True),
        ]

        packet_id = timestamp_id(
            "workpkt",
            "job",
            job_id,
            "anti_ai_audit",
            short_hash([draft.id, draft.version]),
        )
        artifact_refs = {
            "job_id": job_id,
            "draft_id": draft.id,
            "draft_version": draft.version,
        }
        packet = self._save_model_packet(
            WorkPacket(
                work_packet_id=packet_id,
                stage="anti_ai_audit",
                scope=f"job:{job_id}",
                instructions=(
                    "Audit the committed draft against the anti-AI writing skill. The system_prompt "
                    "contains ONLY the anti-AI skill; do not invent grounding rules or rewrite the "
                    "draft. Return JSON matching response_schema. Empty arrays will be rejected."
                ),
                system_prompt=ANTI_AI_AUDIT_SYSTEM_PROMPT,
                prompt_blocks=prompt_blocks,
                response_schema=dict(ANTI_AI_AUDIT_SCHEMA),
                context={
                    "job_id": job_id,
                    "draft_id": draft.id,
                    "draft_version": draft.version,
                },
                artifact_refs=artifact_refs,
                commit_tool="commit_anti_ai_audit",
                delegation=DelegationHint(
                    recommended=True,
                    reason=(
                        "bounded single-skill audit; subagent gets ONLY the anti-AI skill in "
                        "its system prompt and produces the structured audit JSON"
                    ),
                    suggested_role="anti_ai_auditor",
                    required_model_tier="frontier",
                    allowed_tools=["submit_work_result"],
                    return_contract=(
                        "Return one JSON object matching response_schema (the audit, not a rewrite)."
                    ),
                    subagent_prompt=(
                        "Use a frontier/highest-reasoning subagent. For Claude this means Opus; "
                        "for Codex use the strongest available Codex reasoning model. "
                        "Read the essay content in the user message. "
                        "Apply the anti-AI writing skill from the system prompt. Score, do not "
                        "rewrite. Return the audit JSON."
                    ),
                ),
                # The audit packet is structurally clean-context work.
                # Require a subagent dispatch token at submit time so the
                # orchestrator cannot silently absorb the audit system
                # prompt. (mechanism B)
                delegation_required=True,
            )
        )
        if agent_run_id is not None:
            self.run_store.attach_work_packet(
                agent_run_id,
                packet.work_packet_id,
                current_phase="anti_ai_audit",
                next_suggested_tools=["submit_work_result"],
            )
        return ToolResult(
            ok=True,
            tool_name="prepare_anti_ai_audit",
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
                "next_suggested_tools": ["submit_work_result"],
            },
            next_suggested_tools=["submit_work_result"],
        )

    def commit_anti_ai_audit(
        self,
        work_result_id: str,
        *,
        agent_run_id: str | None = None,
    ) -> ToolResult:
        """Attach the audit JSON to the draft as a new draft version.

        We do not overwrite the existing draft in place: the audit is a real
        artifact that belongs in the draft history, and downstream consumers
        (validation, export) should be able to ask which audit version they
        are looking at.
        """
        from essay_writer.drafting.schema import (
            AntiAIFinalDecision,
            AntiAISelfCheck,
            AntiAISkillLineAudit,
            AntiAIUnmetRequirement,
            EssayDraft,
            StyleGuidanceGrade,
        )

        _, _gate_error = self._load_run_and_gate("commit_anti_ai_audit", agent_run_id)
        if _gate_error is not None:
            return _gate_error
        try:
            result = self.work_store.load_result(work_result_id)
            packet = self.work_store.load_packet(result.work_packet_id)
        except (KeyError, FileNotFoundError) as exc:
            return _error_result(
                "commit_anti_ai_audit",
                code="work_result_not_found",
                message=f"WorkResult not found: {work_result_id}",
                exc=exc,
            )
        if packet.commit_tool != "commit_anti_ai_audit":
            return _error_result(
                "commit_anti_ai_audit",
                code="wrong_commit_tool",
                message=f"expected commit_anti_ai_audit packet, got {packet.commit_tool}",
                exc=ValueError(packet.commit_tool),
            )
        validation_error = _validate_work_payload(
            result.payload,
            ANTI_AI_AUDIT_SCHEMA,
            tool_name="commit_anti_ai_audit",
        )
        if validation_error is not None:
            return validation_error
        job_id = packet.context.get("job_id") or packet.artifact_refs.get("job_id")
        source_draft_id = packet.context.get("draft_id") or packet.artifact_refs.get("draft_id")
        if not isinstance(job_id, str) or not isinstance(source_draft_id, str):
            return _error_result(
                "commit_anti_ai_audit",
                code="missing_artifact_refs",
                message="anti-AI audit packet missing job_id or draft_id",
                exc=ValueError("artifact_refs"),
            )
        try:
            source_draft = self.stores.draft_store.find_by_id(job_id, source_draft_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return _error_result(
                "commit_anti_ai_audit",
                code="draft_not_found",
                message=f"source draft missing: {source_draft_id}",
                exc=exc,
            )

        binding_error = _validate_anti_ai_audit_binding(
            result.payload,
            source_draft=source_draft,
        )
        if binding_error is not None:
            return binding_error

        audit_payload = result.payload.get("anti_ai_self_check", {}) or {}
        line_audit = [
            AntiAISkillLineAudit(
                line_number=int(row.get("line_number", 0) or 0),
                line_text_sha256=str(row.get("line_text_sha256", "")).strip(),
                requirement=str(row.get("requirement", "")).strip(),
                status=str(row.get("status", "")).strip(),
                evidence=str(row.get("evidence", "")).strip(),
                action_taken=str(row.get("action_taken", "")).strip(),
                draft_evidence=[
                    {
                        "kind": str(item.get("kind", "")).strip(),
                        "reference": str(item.get("reference", "")).strip(),
                        "explanation": str(item.get("explanation", "")).strip(),
                    }
                    for item in row.get("draft_evidence", []) or []
                    if isinstance(item, dict)
                ],
                whole_essay_evidence=dict(row.get("whole_essay_evidence", {}) or {}),
                line_application=str(row.get("line_application", "")).strip(),
            )
            for row in audit_payload.get("line_audit", []) or []
            if isinstance(row, dict)
        ]
        grades = [
            StyleGuidanceGrade(
                bullet=str(grade.get("bullet", "")).strip(),
                followed=bool(grade.get("followed", False)),
                where=str(grade.get("where", "")).strip(),
                why_not=str(grade.get("why_not", "")).strip(),
            )
            for grade in audit_payload.get("style_guidance_grades", []) or []
            if isinstance(grade, dict) and str(grade.get("bullet", "")).strip()
        ]
        unmet_requirements = [
            AntiAIUnmetRequirement(
                line_number=int(row.get("line_number", 0) or 0),
                section=str(row.get("section", "")).strip(),
                status=str(row.get("status", "")).strip(),
                reason=str(row.get("reason", "")).strip(),
                risk=str(row.get("risk", "")).strip(),
            )
            for row in audit_payload.get("unmet_requirements", []) or []
            if isinstance(row, dict)
        ]
        final_decision_raw = audit_payload.get("final_decision") or {}
        final_decision = (
            AntiAIFinalDecision(
                hard_rules_pass=bool(final_decision_raw.get("hard_rules_pass", False)),
                soft_rules_pass=bool(final_decision_raw.get("soft_rules_pass", False)),
                safe_to_claim_detector_reduction=bool(
                    final_decision_raw.get("safe_to_claim_detector_reduction", False)
                ),
                reason=str(final_decision_raw.get("reason", "")).strip(),
            )
            if isinstance(final_decision_raw, dict)
            else None
        )
        audit = AntiAISelfCheck(
            skill_file=str(audit_payload.get("skill_file", "")).strip(),
            skill_sha256=str(audit_payload.get("skill_sha256", "")).strip(),
            skill_line_count=int(audit_payload.get("skill_line_count", 0) or 0),
            draft_sha256=str(audit_payload.get("draft_sha256", "")).strip(),
            line_audit=line_audit,
            paragraph_count=int(audit_payload.get("paragraph_count", 0) or 0),
            paragraph_first_sentences=[
                str(s) for s in audit_payload.get("paragraph_first_sentences", []) or []
            ],
            first_sentence_chain_summarizes_essay=bool(
                audit_payload.get("first_sentence_chain_summarizes_essay", True)
            ),
            paragraphs_under_50_words=int(audit_payload.get("paragraphs_under_50_words", 0) or 0),
            paragraphs_opening_with_topic_sentence=int(
                audit_payload.get("paragraphs_opening_with_topic_sentence", 0) or 0
            ),
            filler_phrases_used=[
                str(s) for s in audit_payload.get("filler_phrases_used", []) or []
            ],
            significance_inflation_phrases=[
                str(s) for s in audit_payload.get("significance_inflation_phrases", []) or []
            ],
            vague_attributions_used=[
                str(s) for s in audit_payload.get("vague_attributions_used", []) or []
            ],
            concrete_source_handles=[
                str(s) for s in audit_payload.get("concrete_source_handles", []) or []
            ],
            style_guidance_grades=grades,
            self_check_notes=[
                str(s) for s in audit_payload.get("self_check_notes", []) or []
            ],
            unmet_requirements=unmet_requirements,
            final_decision=final_decision,
        )
        passes = bool(result.payload.get("pass", False))
        revision_targets = result.payload.get("revision_targets", []) or []

        scope = f"job:{job_id}"
        existing_commit = next(
            (
                commit
                for commit in self.work_store.list_commits(scope=scope, stage="anti_ai_audit")
                if commit.work_result_id == result.work_result_id
            ),
            None,
        )
        already_committed = existing_commit is not None
        if existing_commit is not None:
            audited_version = existing_commit.artifact_refs.get("draft_version")
            if isinstance(audited_version, int):
                draft = self.stores.draft_store.load(job_id, audited_version)
            else:
                return _error_result(
                    "commit_anti_ai_audit",
                    code="audit_commit_artifact_missing",
                    message="prior audit commit is missing draft_version",
                    exc=KeyError(existing_commit.commit_id),
                )
            commit = existing_commit
        else:
            new_version = self.stores.draft_store.next_version(job_id)
            draft = replace(
                source_draft,
                id=f"draft_{uuid4().hex[:12]}",
                version=new_version,
                anti_ai_self_check=audit,
                origin="system_revision",
                created_by="system",
                parent_draft_id=source_draft.id,
                prompt_version="anti-ai-audit-v1",
            )
            try:
                self.stores.draft_store.save(draft)
                self.stores.workflow.record_draft_ready(job_id=job_id, draft=draft)
            except (FileExistsError, TopicSelectionError) as exc:
                return _error_result(
                    "commit_anti_ai_audit",
                    code="audit_commit_failed",
                    message=str(exc),
                    exc=exc,
                )
            artifact_refs = {
                "job_id": job_id,
                "source_draft_id": source_draft.id,
                "draft_id": draft.id,
                "draft_version": new_version,
                "skill_sha256": audit.skill_sha256,
                "draft_sha256": audit.draft_sha256,
                "audit_pass": passes,
                "audit_revision_target_count": len(revision_targets),
            }
            commit = self.work_store.save_commit(
                scope=scope,
                stage="anti_ai_audit",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs=artifact_refs,
            )

        next_tools = (
            ["prepare_validation"]
            if passes
            else ["prepare_revision", "prepare_validation"]
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
                current_phase="validation" if passes else "anti_ai_revision",
                decision="anti_ai_audit_committed",
                next_suggested_tools=next_tools,
            )
        return ToolResult(
            ok=True,
            tool_name="commit_anti_ai_audit",
            data={
                "commit_id": commit.commit_id,
                "work_result_id": result.work_result_id,
                "job_id": job_id,
                "draft_id": draft.id,
                "audit_pass": passes,
                "revision_targets": revision_targets,
                "anti_ai_self_check": audit_payload,
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
        _, _gate_error = self._load_run_and_gate("prepare_validation", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        # The anti-AI audit is draft-bound, not job-bound. A manual edit or
        # regenerated draft invalidates any earlier audit, even if the job has
        # an anti_ai_audit commit in its history.
        if self.require_anti_ai_audit:
            audit_error = _anti_ai_audit_freshness_error(
                "prepare_validation",
                draft=draft,
            )
            if audit_error is not None:
                return audit_error
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
        packet = self._save_model_packet(
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
        _, _gate_error = self._load_run_and_gate("commit_validation", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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

    def cleanup_agent_run(
        self,
        agent_run_id: str,
        *,
        scope: str = "workflow_logs",
        confirm: bool = False,
        force: bool = False,
    ) -> ToolResult:
        if scope not in CLEANUP_SCOPES:
            return _error_result(
                "cleanup_agent_run",
                code="cleanup_scope_invalid",
                message=(
                    f"scope must be one of {CLEANUP_SCOPES}, got {scope!r}"
                ),
                exc=ValueError(scope),
            )
        run, _gate_error = self._load_run_and_gate("cleanup_agent_run", agent_run_id)
        if _gate_error is not None:
            return _gate_error

        if (
            confirm
            and not force
            and run.status == "active"
            and run.pending_work_packet_ids
        ):
            return _error_result(
                "cleanup_agent_run",
                code="cleanup_blocked_active_run",
                message=(
                    f"agent run {agent_run_id} is still active with "
                    f"{len(run.pending_work_packet_ids)} pending work packet(s). "
                    "Resolve or commit them first, or call again with force=True."
                ),
                exc=ValueError(run.status),
            )

        plan = _build_cleanup_plan(
            stores=self.stores,
            work_store=self.work_store,
            run_store=self.run_store,
            run=run,
            scope=scope,
        )

        plan_summary = {
            category: {"count": entry["count"], "bytes": entry["bytes"]}
            for category, entry in plan["delete"].items()
        }
        preserved_summary = {
            category: {"count": entry["count"], "bytes": entry["bytes"]}
            for category, entry in plan["preserve"].items()
        }
        totals = {
            "deletable_count": sum(entry["count"] for entry in plan["delete"].values()),
            "deletable_bytes": sum(entry["bytes"] for entry in plan["delete"].values()),
            "preserved_count": sum(entry["count"] for entry in plan["preserve"].values()),
            "preserved_bytes": sum(entry["bytes"] for entry in plan["preserve"].values()),
        }

        if not confirm:
            return ToolResult(
                ok=True,
                tool_name="cleanup_agent_run",
                data={
                    "dry_run": True,
                    "confirm": False,
                    "agent_run_id": agent_run_id,
                    "job_id": run.job_id,
                    "scope": scope,
                    "would_delete": plan_summary,
                    "preserved": preserved_summary,
                    "totals": totals,
                    "warnings": plan["warnings"],
                    "next_steps": [
                        "Show the user this preview, then call cleanup_agent_run again "
                        "with confirm=True only if the user explicitly approves the deletion."
                    ],
                },
            )

        allowed_root = self.stores.data_dir.resolve()
        deleted: dict[str, dict[str, int]] = {}
        delete_errors: list[str] = []
        for category, entry in plan["delete"].items():
            count = 0
            byte_total = 0
            for path in entry["paths"]:
                try:
                    deleted_count, deleted_bytes = _safe_delete_path(
                        Path(path),
                        allowed_root=allowed_root,
                    )
                except (ValueError, OSError) as exc:
                    delete_errors.append(f"{category}:{path}: {exc}")
                    continue
                count += deleted_count
                byte_total += deleted_bytes
            deleted[category] = {"count": count, "bytes": byte_total}

        actual_totals = {
            "deleted_count": sum(entry["count"] for entry in deleted.values()),
            "deleted_bytes": sum(entry["bytes"] for entry in deleted.values()),
            "preserved_count": totals["preserved_count"],
            "preserved_bytes": totals["preserved_bytes"],
        }
        return ToolResult(
            ok=True,
            tool_name="cleanup_agent_run",
            data={
                "dry_run": False,
                "confirm": True,
                "agent_run_id": agent_run_id,
                "job_id": run.job_id,
                "scope": scope,
                "deleted": deleted,
                "preserved": preserved_summary,
                "totals": actual_totals,
                "warnings": plan["warnings"] + delete_errors,
            },
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
        _, _gate_error = self._load_run_and_gate("save_user_edit", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
            anti_ai_self_check=None,
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
        next_tools = ["prepare_anti_ai_audit"]
        artifact_refs = {"job_id": job_id, "draft_id": edited.id, "draft_version": version}
        if agent_run_id is not None:
            self.run_store.attach_commit(
                agent_run_id,
                artifact_refs,
                next_suggested_tools=next_tools,
            )
            self.run_store.checkpoint(
                agent_run_id,
                current_phase="anti_ai_audit",
                decision="user_edit_saved",
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
        allow_failed_validation: bool = False,
    ) -> ToolResult:
        _, _gate_error = self._load_run_and_gate("export_markdown", agent_run_id)
        if _gate_error is not None:
            return _gate_error
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
        if self.require_anti_ai_audit:
            audit_error = _anti_ai_audit_freshness_error(
                "export_markdown",
                draft=draft,
            )
            if audit_error is not None:
                return audit_error
        # Refuse to export a draft whose validation did not pass, unless the
        # caller explicitly overrides. Without this, the documented
        # "loop back through revision on failure" step is advisory only:
        # commit_validation(fail) -> prepare_validation -> export ships a
        # failed essay. (Tier-1 fix for the export-failed-validation bug.)
        if not validation.passes and not allow_failed_validation:
            return _error_result_with_next(
                "export_markdown",
                code="validation_not_passing",
                message=(
                    "The latest validation report for this draft did not pass "
                    "(validation.passes is False). Run prepare_revision -> "
                    "commit_revision and re-validate until it passes, or call "
                    "export_markdown with allow_failed_validation=True to "
                    "deliberately export a draft that failed validation."
                ),
                exc=ValueError("validation_not_passing"),
                next_suggested_tools=["prepare_revision", "prepare_validation"],
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
        packet = self._save_model_packet(
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
        packet = self._save_model_packet(
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


_FRONTIER_MODEL_TIER_ALIASES = {
    "frontier",
    "highest_available",
    "highest-available",
    "highest_reasoning",
    "highest-reasoning",
    "max",
    "opus",
    "claude-opus",
    "claude_opus",
    "gpt-5",
    "gpt5",
    "gpt-5-high",
    "codex",
    "codex-high",
    "codex_high",
}


def _model_tier_satisfies_required(
    requested_model_tier: str | None,
    *,
    required_model_tier: str,
) -> bool:
    requested = (requested_model_tier or "").strip().lower()
    required = required_model_tier.strip().lower()
    if not requested:
        return False
    if requested == required:
        return True
    if required == "frontier":
        return requested in _FRONTIER_MODEL_TIER_ALIASES
    return False


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
_SUPPORTED_WRITING_STYLE_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def hard_tier_anti_ai_violations(det: DeterministicCheckResult) -> list[dict[str, object]]:
    """Return a list of hard-tier anti-AI violations found by the deterministic
    checker. The list mirrors the enumerated hard-tier rules in
    DRAFTING_SYSTEM_PROMPT and STYLE_REVISION_SYSTEM_PROMPT, so prompt and gate
    stay coupled: anything banned in the prompt is also rejected at commit
    time.

    Returns an empty list when the text passes. Each entry is a structured
    record naming the rule and the specific evidence (count or hits) so the
    rejection response is actionable for the harness.
    """
    violations: list[dict[str, object]] = []
    if det.em_dash_count > 0:
        violations.append({"rule": "em_dash", "count": det.em_dash_count})
    if det.decorative_hyphen_pause_count > 0:
        violations.append(
            {
                "rule": "decorative_hyphen_pause",
                "count": det.decorative_hyphen_pause_count,
            }
        )
    if det.tier1_vocab_hits:
        violations.append(
            {
                "rule": "tier1_vocabulary",
                "hits": [
                    {"word": hit.word, "count": hit.count}
                    for hit in det.tier1_vocab_hits
                ],
            }
        )
    if det.bad_conclusion_opener:
        violations.append({"rule": "bad_conclusion_opener"})
    if det.signposting_hits:
        violations.append(
            {"rule": "signposting", "phrases": list(det.signposting_hits)}
        )
    if det.triplet_contrastive_combo_count > 0:
        violations.append(
            {
                "rule": "triplet_contrastive_combo",
                "count": det.triplet_contrastive_combo_count,
            }
        )
    return violations


def _anti_ai_line_reasoning_error(
    row: dict[str, object],
    *,
    line_number: int,
    line_text: str,
    tool_name: str,
) -> ToolResult | None:
    application = str(row.get("line_application", "")).strip()
    if len(application) < 25:
        return _error_result(
            tool_name,
            code="anti_ai_skill_line_audit_weak_reasoning",
            message=(
                "anti-AI audit line_application is too thin to prove "
                f"line-specific reasoning for skill line {line_number}."
            ),
            exc=ValueError("line_application"),
        )
    lowered_application = application.lower()
    if f"line {line_number}" in lowered_application:
        return None
    line_words = [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{3,}", line_text.lower())
        if word not in {"this", "that", "with", "from", "must", "should", "will"}
    ]
    if line_words and any(word in lowered_application for word in line_words[:8]):
        return None
    return _error_result(
        tool_name,
        code="anti_ai_skill_line_audit_weak_reasoning",
        message=(
            "anti-AI audit line_application must tie its reasoning to the "
            f"specific skill-file line {line_number}, not just a generic checklist."
        ),
        exc=ValueError("line_application"),
    )


def _anti_ai_line_draft_evidence_error(
    row: dict[str, object],
    *,
    line_number: int,
    draft_text: str,
    tool_name: str,
) -> ToolResult | None:
    evidence_items = row.get("draft_evidence")
    if not isinstance(evidence_items, list) or not evidence_items:
        return _error_result(
            tool_name,
            code="anti_ai_skill_line_audit_missing_draft_evidence",
            message=(
                "anti-AI audit rows must include draft_evidence for every "
                f"skill line; line {line_number} did not."
            ),
            exc=ValueError("draft_evidence"),
        )
    status = str(row.get("status", "")).strip()
    meaningful = False
    paragraph_count = len(_draft_paragraphs(draft_text))
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip()
        reference = str(item.get("reference", "")).strip()
        explanation = str(item.get("explanation", "")).strip()
        if len(reference) < 3 or len(explanation) < 12:
            continue
        if kind == "draft_quote" and reference in draft_text:
            meaningful = True
        elif kind == "paragraph_reference" and _valid_paragraph_reference(
            reference,
            paragraph_count=paragraph_count,
        ):
            meaningful = True
        elif kind == "deterministic_check":
            meaningful = True
    if status == "context":
        return None
    if meaningful:
        return None
    return _error_result(
        tool_name,
        code="anti_ai_skill_line_audit_missing_draft_evidence",
        message=(
            "anti-AI audit non-context rows must cite draft-specific evidence "
            f"for skill line {line_number}: an exact draft quote, paragraph "
            "reference, or deterministic check."
        ),
        exc=ValueError("draft_evidence"),
    )


def _anti_ai_line_whole_essay_error(
    row: dict[str, object],
    *,
    line_number: int,
    paragraph_count: int,
    tool_name: str,
) -> ToolResult | None:
    whole = row.get("whole_essay_evidence")
    if not isinstance(whole, dict):
        return _error_result(
            tool_name,
            code="anti_ai_skill_line_audit_missing_whole_essay_review",
            message=(
                "anti-AI audit rows must include whole_essay_evidence for every "
                f"skill line; line {line_number} did not."
            ),
            exc=ValueError("whole_essay_evidence"),
        )
    scope = str(whole.get("scope", "")).strip()
    try:
        reviewed_count = int(whole.get("paragraph_count_reviewed", -1))
    except (TypeError, ValueError):
        reviewed_count = -1
    method = str(whole.get("method", "")).strip()
    finding = str(whole.get("finding", "")).strip()
    if (
        scope != "whole_essay"
        or reviewed_count != paragraph_count
        or len(method) < 20
        or len(finding) < 20
    ):
        return _error_result(
            tool_name,
            code="anti_ai_skill_line_audit_missing_whole_essay_review",
            message=(
                "anti-AI audit rows must prove whole-essay review for each "
                f"skill line. Line {line_number} must use scope='whole_essay', "
                "the exact audited paragraph count, and a substantive method/finding."
            ),
            exc=ValueError("whole_essay_evidence"),
        )
    return None


def _draft_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _valid_paragraph_reference(reference: str, *, paragraph_count: int) -> bool:
    match = re.search(r"\bparagraph\s+(\d+)\b", reference.lower())
    if match is None:
        return False
    paragraph_number = int(match.group(1))
    return 1 <= paragraph_number <= max(1, paragraph_count)


def _validate_anti_ai_audit_binding(
    payload: dict[str, object],
    *,
    source_draft: object,
    tool_name: str = "commit_anti_ai_audit",
) -> ToolResult | None:
    audit = payload.get("anti_ai_self_check")
    if not isinstance(audit, dict):
        return _error_result(
            tool_name,
            code="anti_ai_self_check_missing",
            message="anti-AI audit payload is missing anti_ai_self_check",
            exc=ValueError("anti_ai_self_check"),
        )
    manifest = anti_ai_skill_manifest()
    expected_skill_file = str(manifest["path"])
    expected_skill_hash = str(manifest["sha256"])
    expected_draft_hash = draft_sha256(str(getattr(source_draft, "content")))
    # Compare only the basename. The audit's skill_file is an absolute,
    # environment-specific path, so full-path equality rejects an audit
    # re-validated on a different machine / OS / checkout root even when the
    # skill bytes are byte-identical (bug_007). The skill_sha256 check below is
    # the authoritative content-integrity gate; the basename check only rejects
    # an audit that pointed at a differently-named file.
    if os.path.basename(str(audit.get("skill_file", ""))) != os.path.basename(
        expected_skill_file
    ):
        return _error_result(
            tool_name,
            code="anti_ai_skill_file_mismatch",
            message="anti-AI audit skill file name does not match the current repo skill file",
            exc=ValueError("skill_file"),
        )
    if str(audit.get("skill_sha256", "")) != expected_skill_hash:
        return _error_result(
            tool_name,
            code="anti_ai_skill_hash_mismatch",
            message="anti-AI audit skill hash does not match the current repo skill file",
            exc=ValueError("skill_sha256"),
        )
    if int(audit.get("skill_line_count", 0) or 0) != int(manifest["line_count"]):
        return _error_result(
            tool_name,
            code="anti_ai_skill_line_count_mismatch",
            message="anti-AI audit skill line count does not match the current repo skill file",
            exc=ValueError("skill_line_count"),
        )
    if str(audit.get("draft_sha256", "")) != expected_draft_hash:
        return _error_result(
            tool_name,
            code="anti_ai_draft_hash_mismatch",
            message="anti-AI audit draft hash does not match the audited draft text",
            exc=ValueError("draft_sha256"),
        )

    rows = audit.get("line_audit", [])
    if not isinstance(rows, list):
        return _error_result(
            tool_name,
            code="anti_ai_skill_line_audit_invalid",
            message="anti-AI audit line_audit must be a list",
            exc=ValueError("line_audit"),
        )
    by_line: dict[int, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            line_number = int(row.get("line_number", 0) or 0)
        except (TypeError, ValueError):
            continue
        if line_number in by_line:
            return _error_result(
                tool_name,
                code="anti_ai_skill_line_audit_duplicate",
                message=f"anti-AI audit has duplicate line coverage for line {line_number}",
                exc=ValueError(line_number),
            )
        by_line[line_number] = row

    manifest_lines = manifest["lines"]
    assert isinstance(manifest_lines, list)
    expected_numbers = {
        int(line["line_number"])
        for line in manifest_lines
        if isinstance(line, dict)
    }
    present_numbers = set(by_line)
    if present_numbers != expected_numbers:
        missing = sorted(expected_numbers - present_numbers)
        extra = sorted(present_numbers - expected_numbers)
        return ToolResult(
            ok=False,
            tool_name=tool_name,
            error=ToolError(
                code="anti_ai_skill_line_audit_incomplete",
                message="anti-AI audit must include one line_audit row for every skill file line",
                detail={
                    "missing_lines": missing[:20],
                    "missing_count": len(missing),
                    "extra_lines": extra[:20],
                    "extra_count": len(extra),
                },
            ),
            next_suggested_tools=["prepare_anti_ai_audit"],
        )
    for line in manifest_lines:
        if not isinstance(line, dict):
            continue
        line_number = int(line["line_number"])
        expected_line_hash = str(line["sha256"])
        actual_line_hash = str(by_line[line_number].get("line_text_sha256", ""))
        if actual_line_hash != expected_line_hash:
            return ToolResult(
                ok=False,
                tool_name=tool_name,
                error=ToolError(
                    code="anti_ai_skill_line_audit_hash_mismatch",
                    message=(
                        "anti-AI audit line hash does not match the current "
                        f"skill file at line {line_number}"
                    ),
                    detail={
                        "line_number": line_number,
                        "expected": expected_line_hash,
                        "actual": actual_line_hash,
                    },
                ),
                next_suggested_tools=["prepare_anti_ai_audit"],
            )
        row = by_line[line_number]
        line_text = str(line.get("text", ""))
        reasoning_error = _anti_ai_line_reasoning_error(
            row,
            line_number=line_number,
            line_text=line_text,
            tool_name=tool_name,
        )
        if reasoning_error is not None:
            return reasoning_error
        whole_essay_error = _anti_ai_line_whole_essay_error(
            row,
            line_number=line_number,
            paragraph_count=len(_draft_paragraphs(str(getattr(source_draft, "content")))),
            tool_name=tool_name,
        )
        if whole_essay_error is not None:
            return whole_essay_error
        evidence_error = _anti_ai_line_draft_evidence_error(
            row,
            line_number=line_number,
            draft_text=str(getattr(source_draft, "content")),
            tool_name=tool_name,
        )
        if evidence_error is not None:
            return evidence_error
    non_context_rows = [
        row
        for row in by_line.values()
        if str(row.get("status", "")).strip() != "context"
    ]
    proof_tuples = [
        (
            str(row.get("requirement", "")).strip(),
            str(row.get("evidence", "")).strip(),
            str(row.get("line_application", "")).strip(),
            str(row.get("action_taken", "")).strip(),
        )
        for row in non_context_rows
    ]
    legacy_proof_tuples = [
        (
            str(row.get("requirement", "")).strip(),
            str(row.get("evidence", "")).strip(),
            str(row.get("action_taken", "")).strip(),
        )
        for row in non_context_rows
    ]
    unique_proofs = set(proof_tuples)
    unique_legacy_proofs = set(legacy_proof_tuples)
    if (
        proof_tuples
        and (
            len(unique_proofs) < max(1, len(proof_tuples) // 2)
            or len(unique_legacy_proofs) < max(1, len(legacy_proof_tuples) // 2)
        )
    ):
        return _error_result(
            tool_name,
            code="anti_ai_skill_line_audit_boilerplate",
            message=(
                "anti-AI audit line proof is too repetitive. requirement, "
                "evidence, and action_taken must be line-specific enough to "
                "show the auditor processed individual skill lines."
            ),
            exc=ValueError("line_audit_boilerplate"),
        )
    failed_or_blocked = {
        line_number
        for line_number, row in by_line.items()
        if str(row.get("status", "")).strip() in {"failed", "blocked"}
    }
    unmet_rows = audit.get("unmet_requirements", []) or []
    unmet_lines = {
        int(row.get("line_number", 0) or 0)
        for row in unmet_rows
        if isinstance(row, dict)
    }
    final_decision = audit.get("final_decision")
    hard_rules_pass = None
    soft_rules_pass = None
    safe_to_claim = None
    if isinstance(final_decision, dict):
        hard_rules_pass = bool(final_decision.get("hard_rules_pass", False))
        soft_rules_pass = bool(final_decision.get("soft_rules_pass", False))
        safe_to_claim = bool(final_decision.get("safe_to_claim_detector_reduction", False))
    if failed_or_blocked:
        top_level_pass = bool(payload.get("pass", False))
        if (
            not failed_or_blocked.issubset(unmet_lines)
            or top_level_pass
            or hard_rules_pass
            or soft_rules_pass
            or safe_to_claim
        ):
            return _error_result(
                tool_name,
                code="anti_ai_skill_line_audit_inconsistent",
                message=(
                    "failed or blocked anti-AI skill lines must be listed in "
                    "unmet_requirements and must make pass/final_decision fail."
                ),
                exc=ValueError("line_audit_inconsistent"),
            )
    return None


def _anti_ai_audit_freshness_error(
    tool_name: str,
    *,
    draft: object,
) -> ToolResult | None:
    audit = getattr(draft, "anti_ai_self_check", None)
    if audit is None:
        return _error_result_with_next(
            tool_name,
            code="anti_ai_audit_required",
            message=(
                "The selected draft has no committed anti-AI audit. Run "
                "prepare_anti_ai_audit -> submit_work_result -> "
                "commit_anti_ai_audit for this exact draft before validation or export."
            ),
            exc=ValueError("anti_ai_audit"),
            next_suggested_tools=["prepare_anti_ai_audit"],
        )
    if not getattr(audit, "skill_sha256", "") or not getattr(audit, "draft_sha256", ""):
        return _error_result_with_next(
            tool_name,
            code="anti_ai_audit_required",
            message=(
                "The selected draft has only a draft-time self-check, not a "
                "committed line-bound anti-AI audit. Run prepare_anti_ai_audit "
                "for this exact draft before validation or export."
            ),
            exc=ValueError("anti_ai_audit"),
            next_suggested_tools=["prepare_anti_ai_audit"],
        )
    if not is_anti_ai_audit_fresh(draft):
        return _error_result_with_next(
            tool_name,
            code="anti_ai_audit_stale",
            message=(
                "The selected draft's anti-AI audit is stale. The audit must "
                "match the current anti-ai-detection-SKILL.md hash and the exact "
                "draft text hash."
            ),
            exc=ValueError("anti_ai_audit_stale"),
            next_suggested_tools=["prepare_anti_ai_audit"],
        )
    return _validate_anti_ai_audit_binding(
        {"anti_ai_self_check": asdict(audit)},
        source_draft=draft,
        tool_name=tool_name,
    )


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
        "phase_history": list(run.phase_history),
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


def _harness_stale_error(tool_name: str, run: AgentRun) -> ToolResult | None:
    """Return a ``harness_stale`` / ``harness_never_read`` error when the
    orchestrator has not read ``get_harness_instructions`` recently enough.

    The check fires only for tools that begin with ``prepare_`` or
    ``commit_`` (the stateful-write tools), so read-only and
    bookkeeping tools are not gated on staleness.

    Two trigger conditions:
    - ``harness_never_read``: the run has never read the harness
      (``last_harness_read_at is None``). The orchestrator must read the
      instructions at least once before doing any stateful write.
    - ``harness_stale``: too many phase advances or too much elapsed time
      since the last read.

    Legacy-mode runs always pass.
    """
    if run.phase_mode != PHASE_MODE_STRICT:
        return None
    if not (tool_name.startswith("prepare_") or tool_name.startswith("commit_")):
        return None
    last_read = run.last_harness_read_at
    # Gap (1): the harness must be read at least once before the first
    # stateful write. A fresh run has last_harness_read_at = None.
    if last_read is None:
        return ToolResult(
            ok=False,
            tool_name=tool_name,
            error=ToolError(
                code="harness_never_read",
                message=(
                    "You have not called get_harness_instructions on this run. "
                    "Read the workflow instructions before the first stateful "
                    f"write ({tool_name!r}). Call "
                    "get_harness_instructions(agent_run_id=...) first."
                ),
                detail={
                    "last_harness_read_at": None,
                    "wrong_call": tool_name,
                },
            ),
            next_suggested_tools=["get_harness_instructions"],
        )
    advances = run.phase_advances_since_harness_read
    seconds_since_read: float | None = None
    try:
        parsed = datetime.fromisoformat(last_read)
        now = datetime.fromisoformat(utc_now_iso())
        seconds_since_read = (now - parsed).total_seconds()
    except (TypeError, ValueError):
        seconds_since_read = None
    too_many_advances = advances >= STALE_HARNESS_AFTER_PHASE_ADVANCES
    too_old = (
        seconds_since_read is not None
        and seconds_since_read >= STALE_HARNESS_AFTER_SECONDS
    )
    if not (too_many_advances or too_old):
        return None
    return ToolResult(
        ok=False,
        tool_name=tool_name,
        error=ToolError(
            code="harness_stale",
            message=(
                f"Your last get_harness_instructions read is stale. "
                f"phase_advances_since_harness_read={advances} "
                f"(threshold={STALE_HARNESS_AFTER_PHASE_ADVANCES}); "
                f"seconds_since_read="
                f"{int(seconds_since_read) if seconds_since_read is not None else 'never'} "
                f"(threshold={STALE_HARNESS_AFTER_SECONDS}). "
                f"Call get_harness_instructions before {tool_name!r}."
            ),
            detail={
                "phase_advances_since_harness_read": advances,
                "advances_threshold": STALE_HARNESS_AFTER_PHASE_ADVANCES,
                "seconds_since_read": seconds_since_read,
                "seconds_threshold": STALE_HARNESS_AFTER_SECONDS,
                "last_harness_read_at": last_read,
            },
        ),
        next_suggested_tools=["get_harness_instructions"],
    )


def _phase_gate_error(tool_name: str, run: AgentRun) -> ToolResult | None:
    """Return an ``out_of_order`` ToolResult if the gate blocks this call.

    Returns ``None`` if the call is allowed. Legacy-mode runs always
    return ``None`` (the gate is a no-op for them).
    """
    check = check_tool_allowed(
        tool_name,
        current_phase=run.current_phase,
        phase_mode=run.phase_mode,
    )
    if check.allowed:
        return None
    return ToolResult(
        ok=False,
        tool_name=tool_name,
        error=ToolError(
            code="out_of_order",
            message=check.reason or (
                f"Tool {tool_name!r} is not allowed in current phase "
                f"{run.current_phase!r}."
            ),
            detail={
                "current_phase": check.current_phase,
                "expected_phases": list(check.expected_phases),
                "wrong_call": tool_name,
            },
        ),
        next_suggested_tools=list(check.suggested_next_tools),
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


# --------------------------------------------------------------------------- #
# cleanup_agent_run helpers
# --------------------------------------------------------------------------- #


def _safe_delete_path(path: Path, *, allowed_root: Path) -> tuple[int, int]:
    """Delete a single file or a directory tree, but only if it resolves under
    `allowed_root`. Symlinks are never followed for the containment check or
    for recursive deletion. Returns (deleted_entry_count, deleted_byte_total).
    Raises ValueError if the path escapes the allowed root."""
    if not path.exists() and not path.is_symlink():
        return (0, 0)
    if path.is_symlink():
        raise ValueError(f"refusing to delete symlink: {path}")
    resolved = path.resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(
            f"refusing to delete path outside allowed_root {allowed_root}: {resolved}"
        ) from exc
    if path.is_file():
        size = path.stat().st_size
        path.unlink()
        return (1, size)
    if path.is_dir():
        count, byte_total = _measure_tree(path)
        shutil.rmtree(path)
        return (count, byte_total)
    return (0, 0)


def _measure_tree(root: Path) -> tuple[int, int]:
    count = 0
    byte_total = 0
    for entry in root.rglob("*"):
        if entry.is_symlink():
            continue
        if entry.is_file():
            try:
                byte_total += entry.stat().st_size
            except OSError:
                pass
            count += 1
        elif entry.is_dir():
            count += 1
    return (count, byte_total)


def _path_summary(paths: list[Path]) -> dict[str, object]:
    count = 0
    byte_total = 0
    for path in paths:
        if not path.exists() or path.is_symlink():
            continue
        if path.is_file():
            count += 1
            try:
                byte_total += path.stat().st_size
            except OSError:
                pass
        elif path.is_dir():
            tree_count, tree_bytes = _measure_tree(path)
            count += tree_count
            byte_total += tree_bytes
    return {"count": count, "bytes": byte_total, "paths": [str(p) for p in paths]}


def _list_json(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted([p for p in path.iterdir() if p.is_file() and p.suffix == ".json"])


def _agent_run_log_paths(run_store: AgentRunStore, agent_run_id: str) -> dict[str, list[Path]]:
    """Return events and checkpoints belonging to the given agent_run_id.
    Each file is loaded and filtered by its `agent_run_id` field so substring
    collisions on filenames cannot delete the wrong run's data."""
    from essay_writer.agent_tools.json_io import read_json

    event_paths: list[Path] = []
    for path in _list_json(run_store.events_dir):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if payload.get("agent_run_id") == agent_run_id:
            event_paths.append(path)

    checkpoint_paths: list[Path] = []
    for path in _list_json(run_store.checkpoints_dir):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if payload.get("agent_run_id") == agent_run_id:
            checkpoint_paths.append(path)

    return {"events": event_paths, "checkpoints": checkpoint_paths}


def _work_artifact_paths_for_job(
    work_store: AgentWorkStore,
    job_id: str | None,
) -> dict[str, list[Path]]:
    """Return work packets / results / commits / source-packet bundles whose
    `scope` matches `job:{job_id}`. If `job_id` is None, returns empty lists."""
    if not job_id:
        return {
            "packets": [],
            "results": [],
            "commits": [],
            "source_packet_bundles": [],
        }
    scope = f"job:{job_id}"

    packets = work_store.list_packets(scope=scope)
    packet_paths = [work_store.packets_dir / f"{p.work_packet_id}.json" for p in packets]
    packet_ids = {p.work_packet_id for p in packets}

    result_paths: list[Path] = []
    for path in _list_json(work_store.results_dir):
        try:
            from essay_writer.agent_tools.json_io import read_json

            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if payload.get("work_packet_id") in packet_ids:
            result_paths.append(path)

    commits = work_store.list_commits(scope=scope)
    commit_paths = [work_store.commits_dir / f"{c.commit_id}.json" for c in commits]

    bundle_paths: list[Path] = []
    for path in _list_json(work_store.source_packet_bundles_dir):
        try:
            from essay_writer.agent_tools.json_io import read_json

            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if payload.get("scope") == scope:
            bundle_paths.append(path)

    return {
        "packets": packet_paths,
        "results": result_paths,
        "commits": commit_paths,
        "source_packet_bundles": bundle_paths,
    }


def _build_cleanup_plan(
    *,
    stores: AgentStoreBundle,
    work_store: AgentWorkStore,
    run_store: AgentRunStore,
    run: AgentRun,
    scope: str,
) -> dict[str, object]:
    """Enumerate the paths a cleanup at `scope` would delete vs preserve.
    Returns a dict with keys `delete`, `preserve`, and `warnings`.

    `delete` maps a category key to {"count", "bytes", "paths"}.
    `preserve` maps a category key to {"count", "bytes", "paths"} so the
    caller can confirm what will remain on disk. Path lists in `preserve`
    are summarized lazily — they are not enumerated under directories that
    may be huge."""
    data_dir = stores.data_dir
    job_id = run.job_id
    warnings: list[str] = []

    run_log_paths = _agent_run_log_paths(run_store, run.agent_run_id)
    work_paths = _work_artifact_paths_for_job(work_store, job_id)

    run_record_path = run_store.runs_dir / f"{run.agent_run_id}.json"

    job_record_path: Path | None = None
    job_dir_paths: dict[str, Path] = {}
    if job_id:
        job_record_path = stores.job_store._jobs_dir / f"{job_id}.json"
        job_dir_paths = {
            "research_plans": data_dir / "research_plans" / job_id,
            "topics": data_dir / "topics" / job_id,
            "research": data_dir / "research" / job_id,
            "outlines": data_dir / "outlines" / job_id,
            "validations": data_dir / "validations" / job_id,
            "drafts": data_dir / "drafts" / job_id,
            "exports": data_dir / "exports" / job_id,
        }

    delete: dict[str, dict[str, object]] = {}
    preserve: dict[str, dict[str, object]] = {}

    # workflow_logs: always part of every scope
    delete["agent_run_events"] = _path_summary(run_log_paths["events"])
    delete["agent_run_checkpoints"] = _path_summary(run_log_paths["checkpoints"])
    delete["work_packets"] = _path_summary(work_paths["packets"])
    delete["work_results"] = _path_summary(work_paths["results"])
    delete["work_commits"] = _path_summary(work_paths["commits"])
    delete["source_packet_bundles"] = _path_summary(work_paths["source_packet_bundles"])

    if scope == "workflow_logs":
        preserve["agent_run_record"] = _path_summary(
            [run_record_path] if run_record_path.exists() else []
        )
        if job_id:
            for category, path in job_dir_paths.items():
                preserve[f"job_dir_{category}"] = _path_summary([path])
            if job_record_path is not None:
                preserve["job_record"] = _path_summary(
                    [job_record_path] if job_record_path.exists() else []
                )
        return {"delete": delete, "preserve": preserve, "warnings": warnings}

    if scope in ("intermediate_artifacts", "all_except_export"):
        if not job_id:
            warnings.append(
                f"agent run {run.agent_run_id} has no job_id; "
                f"only agent-run logs are cleanable at scope={scope}."
            )
        for category in ("research_plans", "topics", "research", "outlines", "validations"):
            target = job_dir_paths.get(category)
            delete[f"job_dir_{category}"] = _path_summary([target] if target else [])

    if scope == "intermediate_artifacts":
        # Preserve latest draft only; delete older draft versions.
        drafts_dir = job_dir_paths.get("drafts")
        older_drafts: list[Path] = []
        latest_draft: list[Path] = []
        if drafts_dir and drafts_dir.exists():
            files = sorted(
                [p for p in drafts_dir.iterdir() if p.is_file() and p.suffix == ".json"]
            )
            if files:
                latest_draft = [files[-1]]
                older_drafts = files[:-1]
        delete["older_drafts"] = _path_summary(older_drafts)
        preserve["latest_draft"] = _path_summary(latest_draft)
        preserve["agent_run_record"] = _path_summary(
            [run_record_path] if run_record_path.exists() else []
        )
        if job_record_path is not None:
            preserve["job_record"] = _path_summary(
                [job_record_path] if job_record_path.exists() else []
            )
        if job_id:
            preserve["exports"] = _path_summary([job_dir_paths["exports"]])
            preserve["task_specs"] = _path_summary([data_dir / "task_specs"])
            preserve["sources"] = _path_summary([data_dir / "sources"])
        return {"delete": delete, "preserve": preserve, "warnings": warnings}

    # all_except_export: also delete all drafts, the job record, and the agent run record itself.
    delete["all_drafts"] = _path_summary(
        [job_dir_paths["drafts"]] if "drafts" in job_dir_paths else []
    )
    delete["job_record"] = _path_summary(
        [job_record_path] if job_record_path is not None and job_record_path.exists() else []
    )
    delete["agent_run_record"] = _path_summary(
        [run_record_path] if run_record_path.exists() else []
    )
    if job_id:
        preserve["exports"] = _path_summary([job_dir_paths["exports"]])
        preserve["task_specs"] = _path_summary([data_dir / "task_specs"])
        preserve["sources"] = _path_summary([data_dir / "sources"])
    return {"delete": delete, "preserve": preserve, "warnings": warnings}
