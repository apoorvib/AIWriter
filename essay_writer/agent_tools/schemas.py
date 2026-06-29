from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    detail: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ToolError":
        return cls(
            code=str(data["code"]),
            message=str(data["message"]),
            detail=dict(data.get("detail", {})),
        )


@dataclass(frozen=True)
class PromptBlock:
    text: str
    cacheable: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PromptBlock":
        return cls(text=str(data["text"]), cacheable=bool(data.get("cacheable", False)))


@dataclass(frozen=True)
class DelegationHint:
    recommended: bool = False
    reason: str | None = None
    suggested_role: str | None = None
    required_model_tier: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    return_contract: str | None = None
    subagent_prompt: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "DelegationHint":
        if data is None:
            return cls()
        return cls(
            recommended=bool(data.get("recommended", False)),
            reason=_optional_str(data.get("reason")),
            suggested_role=_optional_str(data.get("suggested_role")),
            required_model_tier=_optional_str(data.get("required_model_tier")),
            allowed_tools=[str(item) for item in data.get("allowed_tools", [])],
            return_contract=_optional_str(data.get("return_contract")),
            subagent_prompt=_optional_str(data.get("subagent_prompt")),
        )


@dataclass(frozen=True)
class WorkProducer:
    type: Literal["main_agent", "subagent", "user", "system"]
    role: str | None = None
    name: str | None = None
    # When the work packet has delegation_required=True, the producer
    # MUST carry the subagent_token issued by dispatch_subagent. The
    # server validates this in submit_work_result. See mechanism (B).
    subagent_token: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WorkProducer":
        return cls(
            type=data["type"],  # type: ignore[arg-type]
            role=_optional_str(data.get("role")),
            name=_optional_str(data.get("name")),
            subagent_token=_optional_str(data.get("subagent_token")),
        )


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    tool_name: str
    mode: str = "agent_tool_no_api"
    data: dict[str, object] = field(default_factory=dict)
    error: ToolError | None = None
    warnings: list[str] = field(default_factory=list)
    next_suggested_tools: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ToolResult":
        error_data = data.get("error")
        return cls(
            ok=bool(data["ok"]),
            tool_name=str(data["tool_name"]),
            mode=str(data.get("mode", "agent_tool_no_api")),
            data=dict(data.get("data", {})),
            error=ToolError.from_dict(error_data) if isinstance(error_data, dict) else None,
            warnings=[str(item) for item in data.get("warnings", [])],
            next_suggested_tools=[str(item) for item in data.get("next_suggested_tools", [])],
        )


@dataclass(frozen=True)
class WorkPacket:
    work_packet_id: str
    stage: str
    scope: str
    instructions: str
    system_prompt: str
    prompt_blocks: list[PromptBlock]
    response_schema: dict[str, object]
    context: dict[str, object]
    artifact_refs: dict[str, object]
    commit_tool: str
    delegation: DelegationHint
    mode: str = "agent_tool_no_api"
    status: str = "prepared"
    # When True, submit_work_result requires a valid subagent dispatch
    # token in the producer. The token is issued by dispatch_subagent.
    # See mechanism (B) for rationale: certain packets are too large or
    # too prompt-engineered to be safely absorbed by the main
    # orchestrator context. The default is False, so existing packets
    # continue to work unchanged.
    delegation_required: bool = False
    # Proof-of-attention token (mechanism / Gap 3). When set, the token
    # has been appended to ``system_prompt`` and the LLM is instructed to
    # echo it in its output. submit_work_result verifies the token
    # appears in the payload; a missing token means the LLM did not read
    # the supplied system prompt and the result is rejected. None means
    # no challenge was injected (enforcement off).
    system_prompt_challenge: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WorkPacket":
        return cls(
            work_packet_id=str(data["work_packet_id"]),
            stage=str(data["stage"]),
            scope=str(data["scope"]),
            instructions=str(data["instructions"]),
            system_prompt=str(data["system_prompt"]),
            prompt_blocks=[
                PromptBlock.from_dict(item)
                for item in data.get("prompt_blocks", [])
                if isinstance(item, dict)
            ],
            response_schema=dict(data.get("response_schema", {})),
            context=dict(data.get("context", {})),
            artifact_refs=dict(data.get("artifact_refs", {})),
            commit_tool=str(data["commit_tool"]),
            delegation=DelegationHint.from_dict(data.get("delegation")),
            mode=str(data.get("mode", "agent_tool_no_api")),
            status=str(data.get("status", "prepared")),
            delegation_required=bool(data.get("delegation_required", False)),
            system_prompt_challenge=_optional_str(data.get("system_prompt_challenge")),
            created_at=str(data.get("created_at", utc_now_iso())),
            warnings=[str(item) for item in data.get("warnings", [])],
        )


@dataclass(frozen=True)
class WorkResult:
    work_result_id: str
    work_packet_id: str
    status: str
    producer: WorkProducer
    payload: dict[str, object]
    payload_hash: str
    mode: str = "agent_tool_no_api"
    created_at: str = field(default_factory=utc_now_iso)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WorkResult":
        producer_data = data["producer"]
        if not isinstance(producer_data, dict):
            raise TypeError("producer must be a mapping")
        return cls(
            work_result_id=str(data["work_result_id"]),
            work_packet_id=str(data["work_packet_id"]),
            status=str(data["status"]),
            producer=WorkProducer.from_dict(producer_data),
            payload=dict(data.get("payload", {})),
            payload_hash=str(data["payload_hash"]),
            mode=str(data.get("mode", "agent_tool_no_api")),
            created_at=str(data.get("created_at", utc_now_iso())),
            warnings=[str(item) for item in data.get("warnings", [])],
        )


@dataclass(frozen=True)
class CommitRecord:
    commit_id: str
    scope: str
    stage: str
    work_packet_id: str
    work_result_id: str
    artifact_refs: dict[str, object]
    mode: str = "agent_tool_no_api"
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CommitRecord":
        return cls(
            commit_id=str(data["commit_id"]),
            scope=str(data["scope"]),
            stage=str(data["stage"]),
            work_packet_id=str(data["work_packet_id"]),
            work_result_id=str(data["work_result_id"]),
            artifact_refs=dict(data.get("artifact_refs", {})),
            mode=str(data.get("mode", "agent_tool_no_api")),
            created_at=str(data.get("created_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class AgentRun:
    agent_run_id: str
    objective: str
    job_id: str | None = None
    user_constraints: list[str] = field(default_factory=list)
    mode: str = "agent_tool_no_api"
    status: str = "active"
    current_phase: str = "bootstrap"
    # phase_mode controls whether the phase gate enforces ordering for this
    # run. New runs default to "strict". Runs loaded from JSON files that
    # predate the gate are loaded as "legacy" and bypass the gate, so old
    # runs continue to work.
    phase_mode: str = "strict"
    # Phase-advance counter and last get_harness_instructions timestamp,
    # used by the stale-harness check (mechanism C).
    phase_advances_since_harness_read: int = 0
    last_harness_read_at: str | None = None
    # Token issued by skip_writing_style_calibration; recorded so the
    # decision is auditable. (mechanism D)
    writing_style_skip_token: str | None = None
    # Ordered list of phases this run has entered (mechanism / Gap 7).
    # Helps the orchestrator re-orient after compaction: recover shows
    # not just the current phase but the journey to it, so a skipped
    # stage is visible.
    phase_history: list[str] = field(default_factory=list)
    artifact_refs: dict[str, object] = field(default_factory=dict)
    pending_work_packet_ids: list[str] = field(default_factory=list)
    completed_work_result_ids: list[str] = field(default_factory=list)
    committed_artifact_refs: dict[str, object] = field(default_factory=dict)
    next_suggested_tools: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AgentRun":
        # If phase_mode is absent from the JSON, this run predates the
        # phase gate. Load it as legacy so the gate is a no-op for it.
        raw_phase_mode = data.get("phase_mode")
        if raw_phase_mode is None:
            phase_mode = "legacy"
        else:
            phase_mode = str(raw_phase_mode)
        return cls(
            agent_run_id=str(data["agent_run_id"]),
            objective=str(data["objective"]),
            job_id=_optional_str(data.get("job_id")),
            user_constraints=[str(item) for item in data.get("user_constraints", [])],
            mode=str(data.get("mode", "agent_tool_no_api")),
            status=str(data.get("status", "active")),
            current_phase=str(data.get("current_phase", "bootstrap")),
            phase_mode=phase_mode,
            phase_advances_since_harness_read=int(
                data.get("phase_advances_since_harness_read", 0) or 0
            ),
            last_harness_read_at=_optional_str(data.get("last_harness_read_at")),
            writing_style_skip_token=_optional_str(data.get("writing_style_skip_token")),
            phase_history=[str(item) for item in data.get("phase_history", [])],
            artifact_refs=dict(data.get("artifact_refs", {})),
            pending_work_packet_ids=[
                str(item) for item in data.get("pending_work_packet_ids", [])
            ],
            completed_work_result_ids=[
                str(item) for item in data.get("completed_work_result_ids", [])
            ],
            committed_artifact_refs=dict(data.get("committed_artifact_refs", {})),
            next_suggested_tools=[str(item) for item in data.get("next_suggested_tools", [])],
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class AgentRunEvent:
    agent_run_event_id: str
    agent_run_id: str
    event_type: str
    message: str
    data: dict[str, object] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AgentRunEvent":
        return cls(
            agent_run_event_id=str(data["agent_run_event_id"]),
            agent_run_id=str(data["agent_run_id"]),
            event_type=str(data["event_type"]),
            message=str(data["message"]),
            data=dict(data.get("data", {})),
            created_at=str(data.get("created_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class AgentRunCheckpoint:
    agent_run_checkpoint_id: str
    agent_run_id: str
    current_phase: str
    decision: str | None = None
    blocked_on: str | None = None
    artifact_refs: dict[str, object] = field(default_factory=dict)
    pending_work_packet_ids: list[str] = field(default_factory=list)
    completed_work_result_ids: list[str] = field(default_factory=list)
    committed_artifact_refs: dict[str, object] = field(default_factory=dict)
    next_suggested_tools: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AgentRunCheckpoint":
        return cls(
            agent_run_checkpoint_id=str(data["agent_run_checkpoint_id"]),
            agent_run_id=str(data["agent_run_id"]),
            current_phase=str(data["current_phase"]),
            decision=_optional_str(data.get("decision")),
            blocked_on=_optional_str(data.get("blocked_on")),
            artifact_refs=dict(data.get("artifact_refs", {})),
            pending_work_packet_ids=[
                str(item) for item in data.get("pending_work_packet_ids", [])
            ],
            completed_work_result_ids=[
                str(item) for item in data.get("completed_work_result_ids", [])
            ],
            committed_artifact_refs=dict(data.get("committed_artifact_refs", {})),
            next_suggested_tools=[str(item) for item in data.get("next_suggested_tools", [])],
            created_at=str(data.get("created_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class AgentRunRecovery:
    agent_run_id: str
    run: AgentRun
    latest_checkpoint: AgentRunCheckpoint | None
    recent_events: list[AgentRunEvent]
    pending_work_packet_ids: list[str]
    completed_work_result_ids: list[str]
    committed_artifact_refs: dict[str, object]
    next_suggested_tools: list[str]
    resume_instructions: str

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AgentRunRecovery":
        run_data = data["run"]
        checkpoint_data = data.get("latest_checkpoint")
        if not isinstance(run_data, dict):
            raise TypeError("run must be a mapping")
        return cls(
            agent_run_id=str(data["agent_run_id"]),
            run=AgentRun.from_dict(run_data),
            latest_checkpoint=(
                AgentRunCheckpoint.from_dict(checkpoint_data)
                if isinstance(checkpoint_data, dict)
                else None
            ),
            recent_events=[
                AgentRunEvent.from_dict(item)
                for item in data.get("recent_events", [])
                if isinstance(item, dict)
            ],
            pending_work_packet_ids=[
                str(item) for item in data.get("pending_work_packet_ids", [])
            ],
            completed_work_result_ids=[
                str(item) for item in data.get("completed_work_result_ids", [])
            ],
            committed_artifact_refs=dict(data.get("committed_artifact_refs", {})),
            next_suggested_tools=[str(item) for item in data.get("next_suggested_tools", [])],
            resume_instructions=str(data["resume_instructions"]),
        )


@dataclass(frozen=True)
class SourcePacketBundle:
    source_packet_bundle_id: str
    scope: str
    packet_payloads: list[dict[str, object]]
    warnings: list[str] = field(default_factory=list)
    mode: str = "agent_tool_no_api"
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SourcePacketBundle":
        return cls(
            source_packet_bundle_id=str(data["source_packet_bundle_id"]),
            scope=str(data["scope"]),
            packet_payloads=[
                dict(item) for item in data.get("packet_payloads", []) if isinstance(item, dict)
            ],
            warnings=[str(item) for item in data.get("warnings", [])],
            mode=str(data.get("mode", "agent_tool_no_api")),
            created_at=str(data.get("created_at", utc_now_iso())),
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
