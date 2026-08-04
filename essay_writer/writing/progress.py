"""Pure completion-ledger derivation for a writing run.

This module is the single authoritative source of "what happens next" in a
writing run. It reads only persisted artifacts (brief, research, plans, drafts,
reviews, output) and derives the next required step. It never trusts a mutable
``current_phase`` field or a subagent's self-report, so a resumed or interrupted
run is always reconstructed from the same durable evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from essay_writer.writing.schema import (
    ResearchPolicy, WriteMode, WritingBrief, WritingDraft, WritingReview,
    WritingRun,
)
from essay_writer.writing.storage import WritingStores

MAX_REVISION_ROUNDS = 2

_NEXT_ACTIONS: dict[str, dict] = {
    "brief": {"tool": "prepare_writing_brief", "commit_tool": "commit_writing_brief"},
    "needs_input": {"tool": "answer_writing_questions"},
    "research": {"tool": "prepare_writing_research", "commit_tool": "commit_writing_research"},
    "plan": {"tool": "prepare_writing_plan", "commit_tool": "commit_writing_plan"},
    "draft": {"tool": "prepare_writing_draft", "commit_tool": "commit_writing_draft"},
    "review": {"tool": "prepare_writing_review", "commit_tool": "commit_writing_review"},
    "revision": {"tool": "prepare_writing_revision", "commit_tool": "commit_writing_revision"},
    "finalize": {"tool": "finalize_writing_run"},
}


@dataclass
class _DeliverableState:
    deliverable_id: str
    format: str
    steps: dict[str, str]
    complete: bool = False
    blocked: bool = False
    next_step: str | None = None
    warnings: list[str] = field(default_factory=list)


def _output_exists(stores: WritingStores, run_id: str) -> bool:
    try:
        stores.outputs.load(run_id)
        return True
    except (KeyError, FileNotFoundError):
        return False


def _load_latest_brief(stores: WritingStores, run_id: str) -> WritingBrief | None:
    if not stores.briefs.versions(run_id):
        return None
    return stores.briefs.load_latest(run_id)


def _research_done(stores: WritingStores, run_id: str) -> bool:
    return bool(stores.research.versions(run_id))


def _load_latest_draft(stores: WritingStores, run_id: str, deliverable_id: str) -> WritingDraft | None:
    if not stores.drafts.versions(run_id, deliverable_id):
        return None
    return stores.drafts.load_latest(run_id, deliverable_id)


def _load_latest_review(stores: WritingStores, run_id: str, deliverable_id: str) -> WritingReview | None:
    if not stores.reviews.versions(run_id, deliverable_id):
        return None
    return stores.reviews.load_latest(run_id, deliverable_id)


def _revision_count(stores: WritingStores, run_id: str, deliverable_id: str) -> int:
    count = 0
    for version in stores.drafts.versions(run_id, deliverable_id):
        if stores.drafts.load(run_id, deliverable_id, version).origin == "revision":
            count += 1
    return count


def _answered_since_brief(stores: WritingStores, run_id: str, brief: WritingBrief) -> bool:
    """True when a human clarification answer was recorded after this brief.

    A blocking brief that has since been answered is stale: the next step is to
    re-run the brief with the added context, not to keep waiting on a human.
    """
    return any(
        item.kind == "answer" and item.created_at > brief.created_at
        for item in stores.context.list(run_id)
    )


def _research_required(run: WritingRun, brief: WritingBrief) -> bool:
    if run.research_policy == ResearchPolicy.OFF:
        return False
    if run.research_policy == ResearchPolicy.REQUIRED:
        return True
    return brief.research_needed


def _deliverable_state(
    stores: WritingStores, run: WritingRun, brief: WritingBrief, deliverable
) -> _DeliverableState:
    run_id = run.writing_run_id
    d_id = deliverable.deliverable_id
    detailed = brief.mode == WriteMode.DETAILED
    steps: dict[str, str] = {}
    state = _DeliverableState(d_id, deliverable.format, steps)

    # Plan (detailed only, before any drafting).
    if detailed:
        plan_done = bool(stores.plans.versions(run_id, d_id))
        steps["plan"] = "done" if plan_done else "pending"
        if not plan_done:
            state.next_step = "plan"
            return state

    # Draft.
    draft = _load_latest_draft(stores, run_id, d_id)
    steps["draft"] = "done" if draft is not None else "pending"
    if draft is None:
        state.next_step = "draft"
        return state

    # Immediate deliverables carry an embedded self-check and finish at the draft.
    if not detailed:
        state.complete = True
        return state

    # Detailed deliverables require a clean-context review bound to this exact draft.
    review = _load_latest_review(stores, run_id, d_id)
    fresh = review is not None and review.draft_sha256 == draft.content_sha256
    steps["review"] = "done" if fresh else "pending"
    if not fresh:
        state.next_step = "review"
        return state
    assert review is not None  # narrowed by `fresh`

    if review.passed:
        state.complete = True
        return state

    # Failing fresh review: revise until the automatic cap, then stop.
    rounds = _revision_count(stores, run_id, d_id)
    if rounds < MAX_REVISION_ROUNDS:
        steps["revision"] = "pending"
        state.next_step = "revision"
        return state

    # Cap reached. Factual/requirement blockers gate on a human; style-only
    # issues are surfaced as warnings and the deliverable finalizes best-effort.
    steps["revision"] = "capped"
    if any(issue.severity == "blocker" for issue in review.issues):
        state.blocked = True
        return state
    state.complete = True
    state.warnings.append(
        f"deliverable '{d_id}' finalized with unresolved style issues after "
        f"{MAX_REVISION_ROUNDS} revision rounds"
    )
    return state


def _result(
    *, status: str, mode: str | None, deliverables: list[dict],
    next_required_step: str | None, next_deliverable_id: str | None,
    requires_human: bool, all_required_done: bool, warnings: list[str],
    next_action: dict,
) -> dict:
    return {
        "status": status,
        "mode": mode,
        "deliverables": deliverables,
        "next_required_step": next_required_step,
        "next_deliverable_id": next_deliverable_id,
        "requires_human": requires_human,
        "all_required_done": all_required_done,
        "warnings": warnings,
        "next_action": next_action,
    }


def build_writing_progress(run: WritingRun, stores: WritingStores) -> dict:
    """Derive the writing run's completion ledger from persisted artifacts only."""
    run_id = run.writing_run_id

    # A persisted output is the terminal, authoritative signal of completion.
    if _output_exists(stores, run_id):
        return _result(
            status="complete", mode=None, deliverables=[],
            next_required_step=None, next_deliverable_id=None,
            requires_human=False, all_required_done=True, warnings=[],
            next_action={},
        )

    brief = _load_latest_brief(stores, run_id)
    if brief is None:
        return _result(
            status="active", mode=None, deliverables=[],
            next_required_step="brief", next_deliverable_id=None,
            requires_human=False, all_required_done=False, warnings=[],
            next_action=dict(_NEXT_ACTIONS["brief"]),
        )

    mode = brief.mode.value

    # Blocking questions pause the run for a human answer — unless one has
    # already been recorded, in which case the brief is re-run with it.
    if brief.blocking_questions:
        if _answered_since_brief(stores, run_id, brief):
            return _result(
                status="active", mode=mode, deliverables=[],
                next_required_step="brief", next_deliverable_id=None,
                requires_human=False, all_required_done=False, warnings=[],
                next_action=dict(_NEXT_ACTIONS["brief"]),
            )
        return _result(
            status="needs_input", mode=mode, deliverables=[],
            next_required_step=None, next_deliverable_id=None,
            requires_human=True, all_required_done=False,
            warnings=[], next_action={
                **_NEXT_ACTIONS["needs_input"],
                "questions": list(brief.blocking_questions),
            },
        )

    # Shared research gate, evaluated before any per-deliverable work.
    if _research_required(run, brief) and not _research_done(stores, run_id):
        return _result(
            status="active", mode=mode, deliverables=[],
            next_required_step="research", next_deliverable_id=None,
            requires_human=False, all_required_done=False, warnings=[],
            next_action=dict(_NEXT_ACTIONS["research"]),
        )

    states = [_deliverable_state(stores, run, brief, d) for d in brief.deliverables]
    warnings: list[str] = []
    for state in states:
        warnings.extend(state.warnings)

    deliverables_view = [
        {
            "deliverable_id": s.deliverable_id,
            "format": s.format,
            "status": (
                "complete" if s.complete
                else "blocked" if s.blocked
                else "active"
            ),
            "steps": s.steps,
        }
        for s in states
    ]

    # First deliverable with an actionable (non-human) step wins the next action.
    for state in states:
        if not state.complete and not state.blocked and state.next_step is not None:
            action = dict(_NEXT_ACTIONS[state.next_step])
            action["deliverable_id"] = state.deliverable_id
            return _result(
                status="active", mode=mode, deliverables=deliverables_view,
                next_required_step=state.next_step,
                next_deliverable_id=state.deliverable_id,
                requires_human=False, all_required_done=False,
                warnings=warnings, next_action=action,
            )

    # No actionable work remains: either everything is done, or the only
    # outstanding deliverables are blocked on a human.
    if any(state.blocked for state in states):
        return _result(
            status="blocked", mode=mode, deliverables=deliverables_view,
            next_required_step=None, next_deliverable_id=None,
            requires_human=True, all_required_done=False, warnings=warnings,
            next_action=dict(_NEXT_ACTIONS["needs_input"]),
        )

    # Every deliverable is complete; the run is ready for deterministic finalization.
    return _result(
        status="active", mode=mode, deliverables=deliverables_view,
        next_required_step="finalize", next_deliverable_id=None,
        requires_human=False, all_required_done=False, warnings=warnings,
        next_action=dict(_NEXT_ACTIONS["finalize"]),
    )
