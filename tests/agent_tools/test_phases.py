"""Tests for the phase model + gate.

These tests cover the pure functions in ``essay_writer/agent_tools/phases.py``.
They do not touch the run store or the facade; those integrations are
tested separately.
"""
from __future__ import annotations

import pytest

from essay_writer.agent_tools.phases import (
    ALL_PHASES,
    JOB_STAGE_TO_PHASE,
    LEGAL_TRANSITIONS,
    NO_RUN_TOOLS,
    PACKET_SUBMIT_TOOLS,
    PHASE_BOOTSTRAP,
    PHASE_DRAFTING,
    PHASE_EXPORT,
    PHASE_JOB_CREATION,
    PHASE_MODE_LEGACY,
    PHASE_MODE_STRICT,
    PHASE_OUTLINE,
    PHASE_TASK_SPEC,
    PHASE_TOPIC_IDEATION,
    PHASE_TOPIC_SELECTION,
    PHASE_VALIDATION,
    PHASE_WRITING_STYLE_GATE,
    READ_ONLY_TOOLS,
    TOOL_ALLOWED_PHASES,
    check_tool_allowed,
    expected_phases_for,
    is_legal_transition,
    normalize_job_stage_to_phase,
    suggested_next_tools_for_phase,
)


# ---------------------------------------------------------------------------
# Job-stage -> run-phase normalization (Tier-1 brick-bug fix)
# ---------------------------------------------------------------------------


def test_every_normalization_target_is_a_valid_phase() -> None:
    for stage, phase in JOB_STAGE_TO_PHASE.items():
        assert phase in ALL_PHASES, (
            f"job stage {stage!r} normalizes to unknown phase {phase!r}"
        )


def test_unknown_job_stages_normalize_to_valid_phases() -> None:
    # The three job-store stages that are NOT run-phase strings must map
    # to valid phases rather than bricking the run.
    for stage in ("created", "source_ingestion", "research"):
        phase = normalize_job_stage_to_phase(stage)
        assert phase in ALL_PHASES, f"{stage!r} -> {phase!r} is not a valid phase"


def test_matching_stage_passes_through() -> None:
    # A stage that already equals a run phase is returned unchanged.
    assert normalize_job_stage_to_phase("drafting") == "drafting"
    assert normalize_job_stage_to_phase("validation") == "validation"
    assert normalize_job_stage_to_phase("topic_ideation") == "topic_ideation"


def test_none_and_garbage_fall_back_to_bootstrap() -> None:
    assert normalize_job_stage_to_phase(None) == PHASE_BOOTSTRAP
    assert normalize_job_stage_to_phase("not_a_real_stage") == PHASE_BOOTSTRAP


# ---------------------------------------------------------------------------
# Table consistency
# ---------------------------------------------------------------------------


def test_every_legal_transition_targets_a_known_phase() -> None:
    for from_phase, tos in LEGAL_TRANSITIONS.items():
        assert from_phase in ALL_PHASES, f"Unknown from_phase: {from_phase}"
        for to_phase in tos:
            assert to_phase in ALL_PHASES, (
                f"Transition {from_phase} -> {to_phase} targets unknown phase"
            )


def test_every_tool_allowed_phase_is_known() -> None:
    for tool_name, allowed in TOOL_ALLOWED_PHASES.items():
        for phase in allowed:
            assert phase in ALL_PHASES, (
                f"Tool {tool_name!r} maps to unknown phase {phase!r}"
            )


def test_read_only_and_packet_submit_tools_do_not_overlap() -> None:
    assert READ_ONLY_TOOLS.isdisjoint(PACKET_SUBMIT_TOOLS)
    assert READ_ONLY_TOOLS.isdisjoint(TOOL_ALLOWED_PHASES.keys())
    assert PACKET_SUBMIT_TOOLS.isdisjoint(TOOL_ALLOWED_PHASES.keys())


def test_self_transition_is_always_legal() -> None:
    for phase in ALL_PHASES:
        assert is_legal_transition(phase, phase), (
            f"Self-transition for {phase} should be legal"
        )


# ---------------------------------------------------------------------------
# expected_phases_for
# ---------------------------------------------------------------------------


def test_expected_phases_for_known_tool() -> None:
    expected = expected_phases_for("prepare_draft")
    # prepare_draft is allowed from outlining (the user has just finished
    # the outline) and from drafting (re-drafting on top of an existing
    # draft). Both names match the existing facade phase strings.
    assert PHASE_DRAFTING in expected
    assert PHASE_OUTLINE in expected


def test_expected_phases_for_read_only_tool_is_empty() -> None:
    assert expected_phases_for("get_harness_instructions") == []


def test_expected_phases_for_packet_submit_tool_is_empty() -> None:
    assert expected_phases_for("submit_work_result") == []


def test_expected_phases_for_unmapped_tool_is_empty() -> None:
    assert expected_phases_for("some_future_tool_we_have_not_added") == []


# ---------------------------------------------------------------------------
# is_legal_transition
# ---------------------------------------------------------------------------


def test_legal_transition_topic_ideation_to_topic_selection() -> None:
    assert is_legal_transition(PHASE_TOPIC_IDEATION, PHASE_TOPIC_SELECTION)


def test_illegal_transition_topic_ideation_to_drafting() -> None:
    assert not is_legal_transition(PHASE_TOPIC_IDEATION, PHASE_DRAFTING)


def test_revision_loops_back_to_validation() -> None:
    from essay_writer.agent_tools.phases import (
        PHASE_REVISION,
    )

    # validation -> revision -> validation (loop)
    assert is_legal_transition(PHASE_VALIDATION, PHASE_REVISION)
    assert is_legal_transition(PHASE_REVISION, PHASE_VALIDATION)


# ---------------------------------------------------------------------------
# check_tool_allowed
# ---------------------------------------------------------------------------


def test_check_allowed_in_correct_phase() -> None:
    result = check_tool_allowed(
        "prepare_draft",
        current_phase=PHASE_DRAFTING,
        phase_mode=PHASE_MODE_STRICT,
    )
    assert result.allowed is True
    assert result.current_phase == PHASE_DRAFTING
    assert result.reason is None


def test_check_blocked_in_wrong_phase() -> None:
    result = check_tool_allowed(
        "prepare_draft",
        current_phase=PHASE_TOPIC_IDEATION,
        phase_mode=PHASE_MODE_STRICT,
    )
    assert result.allowed is False
    assert result.current_phase == PHASE_TOPIC_IDEATION
    assert PHASE_DRAFTING in result.expected_phases
    assert PHASE_OUTLINE in result.expected_phases
    assert result.reason is not None
    assert "topic_ideation" in result.reason
    assert "drafting" in result.reason


def test_check_blocked_returns_suggested_next_tools() -> None:
    result = check_tool_allowed(
        "prepare_draft",
        current_phase=PHASE_TOPIC_IDEATION,
        phase_mode=PHASE_MODE_STRICT,
    )
    assert result.allowed is False
    # In topic_ideation, prepare_topics and commit_topics should be suggested.
    assert "prepare_topics" in result.suggested_next_tools
    assert "commit_topics" in result.suggested_next_tools


def test_read_only_tool_always_allowed_strict() -> None:
    for phase in ALL_PHASES:
        result = check_tool_allowed(
            "get_harness_instructions",
            current_phase=phase,
            phase_mode=PHASE_MODE_STRICT,
        )
        assert result.allowed is True, f"Should allow get_harness_instructions in {phase}"


def test_submit_work_result_always_allowed_strict() -> None:
    for phase in ALL_PHASES:
        result = check_tool_allowed(
            "submit_work_result",
            current_phase=phase,
            phase_mode=PHASE_MODE_STRICT,
        )
        assert result.allowed is True


def test_legacy_mode_bypasses_gate() -> None:
    # In legacy mode, even nonsensical tool/phase pairs pass.
    result = check_tool_allowed(
        "prepare_draft",
        current_phase=PHASE_TOPIC_IDEATION,
        phase_mode=PHASE_MODE_LEGACY,
    )
    assert result.allowed is True
    assert result.reason is None


def test_unmapped_tool_defaults_to_allow_strict() -> None:
    result = check_tool_allowed(
        "some_future_tool",
        current_phase=PHASE_DRAFTING,
        phase_mode=PHASE_MODE_STRICT,
    )
    assert result.allowed is True


def test_writing_style_skip_tool_allowed_in_writing_style_gate() -> None:
    result = check_tool_allowed(
        "skip_writing_style_calibration",
        current_phase=PHASE_WRITING_STYLE_GATE,
        phase_mode=PHASE_MODE_STRICT,
    )
    assert result.allowed is True


def test_writing_style_skip_tool_blocked_in_drafting() -> None:
    result = check_tool_allowed(
        "skip_writing_style_calibration",
        current_phase=PHASE_DRAFTING,
        phase_mode=PHASE_MODE_STRICT,
    )
    assert result.allowed is False


def test_create_job_allowed_during_topic_ideation_for_idempotent_retry() -> None:
    # create_job_from_artifacts is idempotent; the orchestrator may
    # re-call it with the same artifact ids to recover state. Allow it
    # broadly through topic_selection.
    result = check_tool_allowed(
        "create_job_from_artifacts",
        current_phase=PHASE_TOPIC_IDEATION,
        phase_mode=PHASE_MODE_STRICT,
    )
    assert result.allowed is True


def test_create_job_blocked_during_drafting() -> None:
    # By the time we are in drafting, re-calling create_job_from_artifacts
    # is a real out-of-order signal. The gate should block it.
    result = check_tool_allowed(
        "create_job_from_artifacts",
        current_phase=PHASE_DRAFTING,
        phase_mode=PHASE_MODE_STRICT,
    )
    assert result.allowed is False
    assert PHASE_JOB_CREATION in result.expected_phases


def test_post_export_edit_can_reenter_anti_ai_audit() -> None:
    audit_result = check_tool_allowed(
        "prepare_anti_ai_audit",
        current_phase=PHASE_EXPORT,
        phase_mode=PHASE_MODE_STRICT,
    )
    edit_result = check_tool_allowed(
        "save_user_edit",
        current_phase=PHASE_EXPORT,
        phase_mode=PHASE_MODE_STRICT,
    )

    assert audit_result.allowed is True
    assert edit_result.allowed is True


# ---------------------------------------------------------------------------
# suggested_next_tools_for_phase
# ---------------------------------------------------------------------------


def test_suggested_next_tools_for_outline() -> None:
    suggestions = suggested_next_tools_for_phase(PHASE_OUTLINE)
    assert "prepare_outline" in suggestions
    assert "commit_outline" in suggestions
    # prepare_draft is also legal from outlining (transition between
    # stages). Tools far out of scope must not appear.
    assert "create_job_from_artifacts" not in suggestions
    assert "prepare_source_card" not in suggestions


def test_suggested_next_tools_for_writing_style_gate() -> None:
    suggestions = suggested_next_tools_for_phase(PHASE_WRITING_STYLE_GATE)
    assert "attach_writing_style_to_job" in suggestions
    assert "skip_writing_style_calibration" in suggestions
    # Writing-style ingestion tools are still legal here too.
    assert "ingest_writing_style_sample" in suggestions


# ---------------------------------------------------------------------------
# Workflow happy-path walk
# ---------------------------------------------------------------------------


HAPPY_PATH = [
    PHASE_BOOTSTRAP,
    PHASE_TASK_SPEC,
    PHASE_JOB_CREATION,
    PHASE_WRITING_STYLE_GATE,
    PHASE_TOPIC_IDEATION,
    PHASE_TOPIC_SELECTION,
    "research_planning",
    "source_resolution",
    "research_notes",
    PHASE_OUTLINE,
    PHASE_DRAFTING,
    "style_revision",
    "anti_ai_audit",
    PHASE_VALIDATION,
    "export",
    "complete",
]


def test_happy_path_is_walkable() -> None:
    """Walk the documented happy path and check each step is a legal transition."""
    for from_phase, to_phase in zip(HAPPY_PATH, HAPPY_PATH[1:]):
        assert is_legal_transition(from_phase, to_phase), (
            f"Happy-path transition {from_phase} -> {to_phase} is not in LEGAL_TRANSITIONS"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
