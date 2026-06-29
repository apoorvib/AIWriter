"""Workflow phase model and gate.

This module declares the agent-run phase state machine and the gate
used by ``facade`` tools to enforce step-by-step workflow execution.

Phase string values match what ``facade`` already emits via
``run_store.attach_work_packet(current_phase=...)`` and
``run_store.checkpoint(current_phase=...)`` so that existing code does
not need to change phase names. New phases introduced by mechanism (D)
(``writing_style_gate``) are explicitly named here.

The phase of an :class:`AgentRun` is held server-side. Each tool
declares the phases it is allowed to be called from. A call from a
non-allowed phase returns a structured ``out_of_order`` error instead
of running.

Backward compatibility: runs that were created before this module
existed are loaded with ``phase_mode = "legacy"`` and bypass the gate.
New runs default to ``"strict"``.
"""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Phase constants. String values match the existing facade emission so the
# gate can drop in without renaming.
# ---------------------------------------------------------------------------

PHASE_BOOTSTRAP = "bootstrap"
PHASE_SOURCE_INGESTION = "source_cards"
PHASE_WRITING_STYLE_INGESTION = "writing_style"
PHASE_TASK_SPEC = "task_specification"
PHASE_JOB_CREATION = "job_creation"
PHASE_WRITING_STYLE_GATE = "writing_style_gate"  # new for mechanism (D)
PHASE_TOPIC_IDEATION = "topic_ideation"
PHASE_TOPIC_SELECTION = "topic_selection"
PHASE_RESEARCH_PLANNING = "research_planning"
PHASE_SOURCE_RESOLUTION = "source_resolution"
PHASE_RESEARCH_NOTES = "research_notes"
PHASE_OUTLINE = "outlining"
PHASE_DRAFTING = "drafting"
PHASE_STYLE_REVISION = "style_revision"
PHASE_ANTI_AI_AUDIT = "anti_ai_audit"
PHASE_ANTI_AI_REVISION = "anti_ai_revision"
PHASE_VALIDATION = "validation"
PHASE_REVISION = "revision"
PHASE_EXPORT = "export"
PHASE_COMPLETE = "complete"
PHASE_CLEANUP = "cleanup"


ALL_PHASES: frozenset[str] = frozenset({
    PHASE_BOOTSTRAP,
    PHASE_SOURCE_INGESTION,
    PHASE_WRITING_STYLE_INGESTION,
    PHASE_TASK_SPEC,
    PHASE_JOB_CREATION,
    PHASE_WRITING_STYLE_GATE,
    PHASE_TOPIC_IDEATION,
    PHASE_TOPIC_SELECTION,
    PHASE_RESEARCH_PLANNING,
    PHASE_SOURCE_RESOLUTION,
    PHASE_RESEARCH_NOTES,
    PHASE_OUTLINE,
    PHASE_DRAFTING,
    PHASE_STYLE_REVISION,
    PHASE_ANTI_AI_AUDIT,
    PHASE_ANTI_AI_REVISION,
    PHASE_VALIDATION,
    PHASE_REVISION,
    PHASE_EXPORT,
    PHASE_COMPLETE,
    PHASE_CLEANUP,
})


PHASE_MODE_STRICT = "strict"
PHASE_MODE_LEGACY = "legacy"


# The job-store (essay_writer/jobs/workflow.py) uses a different vocabulary
# for EssayJob.current_stage than the run-phase constants above. When a run
# inherits a job's stage (start_agent_run with an existing job, or
# create_job_from_artifacts), the stage MUST be normalized to a valid run
# phase. Without this, a run could land in a phase that is not a key in any
# allow-list, and every gated tool would return out_of_order with no legal
# way out (a silently bricked run). Stages that already match a run-phase
# string are passed through unchanged via normalize_job_stage_to_phase.
JOB_STAGE_TO_PHASE: dict[str, str] = {
    "created": PHASE_BOOTSTRAP,
    "source_ingestion": PHASE_SOURCE_INGESTION,
    "research": PHASE_RESEARCH_PLANNING,
}


def normalize_job_stage_to_phase(stage: str | None) -> str:
    """Map an EssayJob.current_stage to a valid run phase.

    Stages that are already valid run phases pass through unchanged.
    Unknown stages fall back to ``bootstrap`` rather than bricking the
    run with a phase no tool allows.
    """
    if stage is None:
        return PHASE_BOOTSTRAP
    if stage in JOB_STAGE_TO_PHASE:
        return JOB_STAGE_TO_PHASE[stage]
    if stage in ALL_PHASES:
        return stage
    return PHASE_BOOTSTRAP


# Early phases are permissive: source-card and writing-style ingestion may
# happen in any of these phases. Once topic_ideation or later begins, the
# bulk-ingestion tools are no longer expected.
EARLY_PHASES: frozenset[str] = frozenset({
    PHASE_BOOTSTRAP,
    PHASE_SOURCE_INGESTION,
    PHASE_WRITING_STYLE_INGESTION,
    PHASE_TASK_SPEC,
    PHASE_JOB_CREATION,
    PHASE_WRITING_STYLE_GATE,
})


# Tools that read state without changing it. Allowed in any phase.
READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "get_harness_instructions",
    "recover_agent_run",
    "get_agent_run_state",
    "list_agent_runs",
    "checkpoint_agent_run",
    "list_work_packets",
    "get_work_packet",
    "list_work_results",
    "get_work_result",
    "list_sources",
    "get_source_card",
    "search_source",
    "read_source_packet",
    "get_source_packet_bundle",
    "list_drafts",
    "get_draft",
    "get_job_summary",
    "run_deterministic_checks",
})


# submit_work_result is allowed in any active phase. The packet itself
# carries phase context and the facade does payload-schema validation.
# dispatch_subagent is the same shape: it acts on a packet, not on a
# phase, so the gate must not restrict it by phase.
PACKET_SUBMIT_TOOLS: frozenset[str] = frozenset({
    "submit_work_result",
    "dispatch_subagent",
})


# start_agent_run runs before any run exists; the gate skips it entirely.
NO_RUN_TOOLS: frozenset[str] = frozenset({
    "start_agent_run",
    "get_harness_instructions",
    "list_agent_runs",
})


# Per-tool allowed phases. Tools not in this map are not gated.
TOOL_ALLOWED_PHASES: dict[str, frozenset[str]] = {
    # Source ingestion (any early phase before topic_ideation begins).
    "ingest_source_file": EARLY_PHASES,
    "prepare_source_card": EARLY_PHASES,
    "commit_source_card": EARLY_PHASES,

    # Writing-style ingestion (allowed broadly so the user can drop samples
    # at any point before topic_ideation begins).
    "ingest_writing_style_sample": EARLY_PHASES,
    "prepare_writing_style_content": EARLY_PHASES,
    "commit_writing_style_content": EARLY_PHASES,
    "attach_writing_style_to_job": EARLY_PHASES,
    "skip_writing_style_calibration": EARLY_PHASES,

    # Task spec.
    "prepare_task_spec": frozenset({
        PHASE_BOOTSTRAP, PHASE_SOURCE_INGESTION,
        PHASE_WRITING_STYLE_INGESTION, PHASE_TASK_SPEC,
    }),
    "commit_task_spec": frozenset({PHASE_TASK_SPEC}),

    # Job creation. Idempotent re-calls are common (the orchestrator may
    # re-call with the same artifact ids to recover state), so allow this
    # broadly from any phase up through topic_selection.
    "create_job_from_artifacts": frozenset({
        PHASE_BOOTSTRAP, PHASE_SOURCE_INGESTION,
        PHASE_TASK_SPEC, PHASE_JOB_CREATION,
        PHASE_WRITING_STYLE_GATE, PHASE_TOPIC_IDEATION,
        PHASE_TOPIC_SELECTION,
    }),

    # Topic ideation and selection.
    "prepare_topics": frozenset({
        PHASE_TOPIC_IDEATION, PHASE_TOPIC_SELECTION,
    }),
    "commit_topics": frozenset({PHASE_TOPIC_IDEATION}),
    "select_topic": frozenset({PHASE_TOPIC_SELECTION}),
    "reject_topic": frozenset({PHASE_TOPIC_SELECTION}),

    # Research planning and source resolution.
    "create_research_plan": frozenset({
        PHASE_TOPIC_SELECTION, PHASE_RESEARCH_PLANNING,
    }),
    "resolve_source_requests": frozenset({
        PHASE_RESEARCH_PLANNING, PHASE_SOURCE_RESOLUTION,
    }),

    # Research notes.
    "prepare_research_notes": frozenset({
        PHASE_SOURCE_RESOLUTION, PHASE_RESEARCH_NOTES,
    }),
    "commit_research_notes": frozenset({PHASE_RESEARCH_NOTES}),

    # Outline.
    "prepare_outline": frozenset({
        PHASE_RESEARCH_NOTES, PHASE_OUTLINE,
    }),
    "commit_outline": frozenset({PHASE_OUTLINE}),

    # Drafting.
    "prepare_draft": frozenset({
        PHASE_OUTLINE, PHASE_DRAFTING,
    }),
    "commit_draft": frozenset({PHASE_DRAFTING}),

    # Style revision. Allowed from drafting so the orchestrator may
    # skip style revision on short or opt-out drafts.
    "prepare_style_revision": frozenset({
        PHASE_DRAFTING, PHASE_STYLE_REVISION,
    }),
    "prepare_style_revision_window": frozenset({PHASE_STYLE_REVISION}),
    "commit_style_revision": frozenset({PHASE_STYLE_REVISION}),

    # Anti-AI audit (allowed from drafting onward so a draft that skipped
    # style_revision can still be audited).
    "prepare_anti_ai_audit": frozenset({
        PHASE_DRAFTING, PHASE_STYLE_REVISION, PHASE_ANTI_AI_AUDIT,
        PHASE_ANTI_AI_REVISION, PHASE_VALIDATION, PHASE_REVISION,
        PHASE_EXPORT, PHASE_COMPLETE,
    }),
    "commit_anti_ai_audit": frozenset({PHASE_ANTI_AI_AUDIT}),

    # Validation. Allowed from drafting onward so the orchestrator may
    # run validation directly after a draft when style/audit are skipped.
    "prepare_validation": frozenset({
        PHASE_DRAFTING, PHASE_STYLE_REVISION,
        PHASE_ANTI_AI_AUDIT, PHASE_ANTI_AI_REVISION,
        PHASE_VALIDATION, PHASE_REVISION,
    }),
    "commit_validation": frozenset({PHASE_VALIDATION}),

    # Revision loop.
    "prepare_revision": frozenset({
        PHASE_VALIDATION, PHASE_REVISION,
        PHASE_ANTI_AI_AUDIT, PHASE_ANTI_AI_REVISION,
    }),
    "commit_revision": frozenset({
        PHASE_VALIDATION, PHASE_REVISION,
        PHASE_ANTI_AI_AUDIT, PHASE_ANTI_AI_REVISION,
    }),

    # Manual edits invalidate validation/audit state and reopen the
    # anti-AI audit loop. They are allowed late in the workflow because users
    # often edit after validation/export and then need to re-audit.
    "save_user_edit": frozenset({
        PHASE_DRAFTING, PHASE_STYLE_REVISION, PHASE_ANTI_AI_AUDIT,
        PHASE_ANTI_AI_REVISION, PHASE_VALIDATION, PHASE_REVISION,
        PHASE_EXPORT, PHASE_COMPLETE,
    }),

    # Export and cleanup.
    "export_markdown": frozenset({
        PHASE_VALIDATION, PHASE_EXPORT, PHASE_COMPLETE,
    }),
    # Cleanup is allowed from any phase. An orphan run (started but never
    # tied to a job) should still be cleanable.
    "cleanup_agent_run": ALL_PHASES,
}


# Legal phase-to-phase transitions. ``from -> from`` (self) is always legal.
# This table is consulted by mechanism (A3) when it lands; it is informational
# for now and is also used by ``is_legal_transition``.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    PHASE_BOOTSTRAP: frozenset({
        PHASE_BOOTSTRAP, PHASE_SOURCE_INGESTION,
        PHASE_WRITING_STYLE_INGESTION, PHASE_TASK_SPEC,
    }),
    PHASE_SOURCE_INGESTION: frozenset({
        PHASE_SOURCE_INGESTION, PHASE_WRITING_STYLE_INGESTION,
        PHASE_TASK_SPEC, PHASE_BOOTSTRAP,
    }),
    PHASE_WRITING_STYLE_INGESTION: frozenset({
        PHASE_WRITING_STYLE_INGESTION, PHASE_SOURCE_INGESTION,
        PHASE_TASK_SPEC, PHASE_BOOTSTRAP,
    }),
    PHASE_TASK_SPEC: frozenset({
        PHASE_TASK_SPEC, PHASE_JOB_CREATION,
        PHASE_SOURCE_INGESTION, PHASE_WRITING_STYLE_INGESTION,
    }),
    PHASE_JOB_CREATION: frozenset({
        PHASE_JOB_CREATION, PHASE_WRITING_STYLE_GATE,
        PHASE_TOPIC_IDEATION, PHASE_WRITING_STYLE_INGESTION,
    }),
    PHASE_WRITING_STYLE_GATE: frozenset({
        PHASE_WRITING_STYLE_GATE, PHASE_TOPIC_IDEATION,
        PHASE_WRITING_STYLE_INGESTION,
    }),
    PHASE_TOPIC_IDEATION: frozenset({
        PHASE_TOPIC_IDEATION, PHASE_TOPIC_SELECTION,
        PHASE_WRITING_STYLE_GATE,
    }),
    PHASE_TOPIC_SELECTION: frozenset({
        PHASE_TOPIC_SELECTION, PHASE_TOPIC_IDEATION,
        PHASE_RESEARCH_PLANNING,
    }),
    PHASE_RESEARCH_PLANNING: frozenset({
        PHASE_RESEARCH_PLANNING, PHASE_SOURCE_RESOLUTION,
        PHASE_TOPIC_SELECTION,
    }),
    PHASE_SOURCE_RESOLUTION: frozenset({
        PHASE_SOURCE_RESOLUTION, PHASE_RESEARCH_NOTES,
        PHASE_RESEARCH_PLANNING,
    }),
    PHASE_RESEARCH_NOTES: frozenset({
        PHASE_RESEARCH_NOTES, PHASE_OUTLINE,
        PHASE_SOURCE_RESOLUTION,
    }),
    PHASE_OUTLINE: frozenset({
        PHASE_OUTLINE, PHASE_DRAFTING, PHASE_RESEARCH_NOTES,
    }),
    PHASE_DRAFTING: frozenset({
        PHASE_DRAFTING, PHASE_STYLE_REVISION,
        PHASE_ANTI_AI_AUDIT, PHASE_VALIDATION,
        PHASE_OUTLINE,
    }),
    PHASE_STYLE_REVISION: frozenset({
        PHASE_STYLE_REVISION, PHASE_ANTI_AI_AUDIT,
        PHASE_VALIDATION, PHASE_DRAFTING,
    }),
    PHASE_ANTI_AI_AUDIT: frozenset({
        PHASE_ANTI_AI_AUDIT, PHASE_VALIDATION,
        PHASE_ANTI_AI_REVISION, PHASE_STYLE_REVISION,
    }),
    PHASE_ANTI_AI_REVISION: frozenset({
        PHASE_ANTI_AI_REVISION, PHASE_VALIDATION,
        PHASE_ANTI_AI_AUDIT,
    }),
    PHASE_VALIDATION: frozenset({
        PHASE_VALIDATION, PHASE_REVISION,
        PHASE_EXPORT, PHASE_COMPLETE,
        PHASE_ANTI_AI_AUDIT,
    }),
    PHASE_REVISION: frozenset({
        PHASE_REVISION, PHASE_VALIDATION,
    }),
    PHASE_EXPORT: frozenset({
        PHASE_EXPORT, PHASE_COMPLETE, PHASE_CLEANUP,
    }),
    PHASE_COMPLETE: frozenset({
        PHASE_COMPLETE, PHASE_EXPORT, PHASE_CLEANUP,
    }),
    PHASE_CLEANUP: frozenset({
        PHASE_CLEANUP, PHASE_COMPLETE,
    }),
}


@dataclass(frozen=True)
class PhaseCheckResult:
    """Result of a phase gate check."""

    allowed: bool
    current_phase: str
    expected_phases: list[str]
    reason: str | None = None
    suggested_next_tools: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # frozen dataclass + mutable default workaround
        if self.suggested_next_tools is None:
            object.__setattr__(self, "suggested_next_tools", [])


def expected_phases_for(tool_name: str) -> list[str]:
    """Return the sorted list of phases ``tool_name`` is legal in.

    Returns an empty list for read-only/no-run/unmapped tools.
    """
    if tool_name in READ_ONLY_TOOLS or tool_name in PACKET_SUBMIT_TOOLS:
        return []
    if tool_name in NO_RUN_TOOLS:
        return []
    allowed = TOOL_ALLOWED_PHASES.get(tool_name)
    if allowed is None:
        return []
    return sorted(allowed)


def is_legal_transition(from_phase: str, to_phase: str) -> bool:
    """Return True iff ``from_phase -> to_phase`` is a declared transition."""
    if from_phase == to_phase:
        return True
    legal = LEGAL_TRANSITIONS.get(from_phase, frozenset())
    return to_phase in legal


def suggested_next_tools_for_phase(current_phase: str) -> list[str]:
    """Return the tools that are legal to call from ``current_phase``.

    Used as the ``next_suggested_tools`` hint in ``out_of_order`` errors.
    """
    suggestions: list[str] = []
    for tool_name, allowed in TOOL_ALLOWED_PHASES.items():
        if current_phase in allowed:
            suggestions.append(tool_name)
    suggestions.sort()
    return suggestions


def check_tool_allowed(
    tool_name: str,
    *,
    current_phase: str,
    phase_mode: str = PHASE_MODE_STRICT,
) -> PhaseCheckResult:
    """Check whether ``tool_name`` may run in ``current_phase``.

    Legacy-mode runs always pass. Read-only / packet-submit / no-run
    tools always pass. Unmapped tools always pass (default allow).
    """
    if phase_mode != PHASE_MODE_STRICT:
        return PhaseCheckResult(
            allowed=True,
            current_phase=current_phase,
            expected_phases=[],
            reason=None,
        )

    if tool_name in READ_ONLY_TOOLS or tool_name in PACKET_SUBMIT_TOOLS:
        return PhaseCheckResult(
            allowed=True,
            current_phase=current_phase,
            expected_phases=[],
            reason=None,
        )

    if tool_name in NO_RUN_TOOLS:
        return PhaseCheckResult(
            allowed=True,
            current_phase=current_phase,
            expected_phases=[],
            reason=None,
        )

    allowed_phases = TOOL_ALLOWED_PHASES.get(tool_name)
    if allowed_phases is None:
        return PhaseCheckResult(
            allowed=True,
            current_phase=current_phase,
            expected_phases=[],
            reason=None,
        )

    if current_phase in allowed_phases:
        return PhaseCheckResult(
            allowed=True,
            current_phase=current_phase,
            expected_phases=sorted(allowed_phases),
            reason=None,
        )

    sorted_expected = sorted(allowed_phases)
    return PhaseCheckResult(
        allowed=False,
        current_phase=current_phase,
        expected_phases=sorted_expected,
        reason=(
            f"Tool {tool_name!r} requires phase in {sorted_expected!r}; "
            f"current phase is {current_phase!r}."
        ),
        suggested_next_tools=suggested_next_tools_for_phase(current_phase),
    )


__all__ = [
    "ALL_PHASES",
    "EARLY_PHASES",
    "LEGAL_TRANSITIONS",
    "NO_RUN_TOOLS",
    "PACKET_SUBMIT_TOOLS",
    "PHASE_ANTI_AI_AUDIT",
    "PHASE_ANTI_AI_REVISION",
    "PHASE_BOOTSTRAP",
    "PHASE_CLEANUP",
    "PHASE_COMPLETE",
    "PHASE_DRAFTING",
    "PHASE_EXPORT",
    "PHASE_JOB_CREATION",
    "PHASE_MODE_LEGACY",
    "PHASE_MODE_STRICT",
    "PHASE_OUTLINE",
    "PHASE_RESEARCH_NOTES",
    "PHASE_RESEARCH_PLANNING",
    "PHASE_REVISION",
    "PHASE_SOURCE_INGESTION",
    "PHASE_SOURCE_RESOLUTION",
    "PHASE_STYLE_REVISION",
    "PHASE_TASK_SPEC",
    "PHASE_TOPIC_IDEATION",
    "PHASE_TOPIC_SELECTION",
    "PHASE_VALIDATION",
    "PHASE_WRITING_STYLE_GATE",
    "PHASE_WRITING_STYLE_INGESTION",
    "PhaseCheckResult",
    "READ_ONLY_TOOLS",
    "TOOL_ALLOWED_PHASES",
    "check_tool_allowed",
    "expected_phases_for",
    "is_legal_transition",
    "suggested_next_tools_for_phase",
]
