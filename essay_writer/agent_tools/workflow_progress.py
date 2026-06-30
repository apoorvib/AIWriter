from __future__ import annotations

from dataclasses import asdict, dataclass, field

from essay_writer.agent_tools.workflow_predicates import (
    is_anti_ai_audit_fresh,
    latest_validation_passing,
    writing_style_decision_made,
)


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    tier: str  # "required" | "recommended"
    status: str  # "done" | "pending" | "blocked" | "needs_human"
    next_action: dict
    requires_human: bool = False
    evidence: str | None = None
    blocked_by: list[str] = field(default_factory=list)


# Ordered step specs per segment.
# Tuple shape: (step_id, tier, requires_human, next_action, done_fn, is_serial)
#
# `is_serial=False` marks parallel prep steps: they are evaluated independently
# and do not acquire "blocked" status from each other, though they all gate the
# first serial step that follows.  `is_serial=True` steps become "blocked" when
# any earlier required step is not yet done.
#
# `done(ctx)` returns the evidence id (truthy) when the step is complete, else None.

def _prep_specs():
    return [
        # -- parallel prep (do in any order; neither needs a job yet) --
        ("source_cards", "required", False,
         {"tool": "prepare_source_card", "role": "source_card_writer",
          "commit_tool": "commit_source_card"},
         lambda c: c["source_cards_done"],
         False),
        ("task_spec", "required", False,
         {"tool": "prepare_task_spec", "commit_tool": "commit_task_spec"},
         lambda c: c["task_spec_id"],
         False),
        # -- serial: require all parallel prep steps to be done --
        ("job_created", "required", False,
         {"tool": "create_job_from_artifacts"},
         lambda c: c["job"].id if c["job"] is not None else None,
         True),
        # The writing-style decision lives ON the job (a writing_style_content_id
        # or a writing_style_skip_token), so it can only be evaluated AFTER the
        # job exists. The create_job_from_artifacts gate already forces an
        # agent-run-linked job to carry a decision, so this step is normally
        # satisfied as soon as job_created is done; it stays here as an explicit,
        # ordered checkpoint (and to force resolution before topics if a job ever
        # lacks the decision). Placing it before job_created would let the prep
        # loop point next_required_step at a step that cannot be completed yet.
        ("writing_style_decision", "required", False,
         {"tool": "ingest_writing_style_sample / attach_writing_style_to_job / "
                  "skip_writing_style_calibration"},
         lambda c: "decided" if c["job"] is not None
                   and writing_style_decision_made(c["job"]) else None,
         True),
        ("topics", "required", False,
         {"tool": "prepare_topics", "commit_tool": "commit_topics"},
         lambda c: c["job"].topic_round_ids[-1]
                   if c["job"] is not None and c["job"].topic_round_ids else None,
         True),
    ]


def _write_specs():
    return [
        ("topic_selected", "required", True,
         {"tool": "select_topic"},
         lambda c: c["job"].selected_topic_id if c["job"] is not None else None,
         True),
        ("research_plan", "required", False,
         {"tool": "create_research_plan"},
         lambda c: c["job"].research_plan_id if c["job"] is not None else None,
         True),
        ("research_notes", "required", False,
         {"tool": "prepare_research_notes", "commit_tool": "commit_research_notes"},
         lambda c: c["job"].evidence_map_id if c["job"] is not None else None,
         True),
        ("outline", "required", False,
         {"tool": "prepare_outline", "commit_tool": "commit_outline"},
         lambda c: c["job"].outline_id if c["job"] is not None else None,
         True),
        ("draft", "required", False,
         {"tool": "prepare_draft", "commit_tool": "commit_draft"},
         lambda c: c["job"].draft_id if c["job"] is not None else None,
         True),
        # Scan the whole draft history, not just the latest draft: a later
        # required step (anti_ai_audit / revision / user edit) writes a new
        # draft version with a different origin, which would otherwise flip this
        # step back to pending and emit a false "not done" warning for the rest
        # of the run (bug_005). Once a style_revision draft exists, it stays done.
        ("style_revision", "recommended", False,
         {"tool": "prepare_style_revision", "commit_tool": "commit_style_revision"},
         lambda c: "revised" if c["job"] is not None and any(
             getattr(d, "origin", "") == "style_revision"
             for d in c["stores"].draft_store.list_versions(c["job"].id)
         ) else None,
         True),
        ("anti_ai_audit", "required", False,
         {"tool": "prepare_anti_ai_audit", "role": "anti_ai_auditor",
          "model_tier": "frontier", "commit_tool": "commit_anti_ai_audit"},
         lambda c: c["draft"].id if c["draft"] is not None
                   and is_anti_ai_audit_fresh(c["draft"]) else None,
         True),
        ("validation", "required", False,
         {"tool": "prepare_validation", "commit_tool": "commit_validation"},
         lambda c: c["job"].validation_report_id if c["job"] is not None
                   and latest_validation_passing(c["validation_store"], c["job"])
                   else None,
         True),
        ("export", "required", False,
         {"tool": "export_markdown"},
         lambda c: c["job"].final_export_id if c["job"] is not None else None,
         True),
    ]


def _load_job(run, stores):
    if not run.job_id:
        return None
    try:
        return stores.workflow.load_job(run.job_id)
    except (KeyError, FileNotFoundError):
        return None


def _load_latest_draft(stores, job):
    if job is None or not getattr(job, "draft_id", None):
        return None
    try:
        return stores.draft_store.load_latest(job.id)
    except (KeyError, FileNotFoundError):
        return None


def _source_cards_done(stores, job):
    if job is None or not job.source_ids:
        return None
    if all(stores.source_store.has_source_card(sid) for sid in job.source_ids):
        return "all_source_cards"
    return None


def build_workflow_progress(run, stores) -> dict:
    job = _load_job(run, stores)
    draft = _load_latest_draft(stores, job)
    ctx = {
        "job": job,
        "draft": draft,
        "stores": stores,
        "validation_store": stores.validation_store,
        "task_spec_id": getattr(job, "task_spec_id", None) if job else None,
        "source_cards_done": _source_cards_done(stores, job),
    }

    # The segment is "write" once a topic has been selected; before that, "prep".
    in_write = bool(job is not None and job.selected_topic_id)
    specs = _write_specs() if in_write else _prep_specs()
    segment = "write" if in_write else "prep"

    steps: list[WorkflowStep] = []
    # Accumulates ALL required steps that are not yet done (used to compute
    # blocked_by for serial steps and to gate next_required_step tracking).
    prior_required_pending: list[str] = []
    warnings: list[str] = []
    next_required_step = None
    all_required_done = True

    for step_id, tier, requires_human, next_action, done_fn, is_serial in specs:
        evidence = done_fn(ctx)
        is_done = bool(evidence)

        if is_done:
            status = "done"
        elif is_serial and prior_required_pending:
            # Serial steps wait for every unfinished required step before them.
            status = "blocked"
        elif requires_human:
            status = "needs_human"
        else:
            status = "pending"

        steps.append(WorkflowStep(
            step_id=step_id, tier=tier, status=status,
            next_action=next_action, requires_human=requires_human,
            evidence=evidence if is_done else None,
            # Parallel steps (is_serial=False) are always independent; only serial
            # steps carry the full blocked_by list.
            blocked_by=list(prior_required_pending) if is_serial else [],
        ))

        if tier == "required" and not is_done:
            all_required_done = False
            if next_required_step is None and not requires_human:
                next_required_step = step_id
            prior_required_pending.append(step_id)

        if tier == "recommended" and not is_done:
            warnings.append(f"recommended step '{step_id}' not done")

    # Surface a skip of voice calibration so it stays visible the whole run.
    if (
        job is not None
        and getattr(job, "writing_style_skip_token", None)
        and not getattr(job, "writing_style_content_id", None)
    ):
        warnings.append(
            "writing-style calibration was skipped for this job; generated prose "
            "will not match a user voice (elevated AI-detection risk)"
        )

    # Scripted pre-job prelude (design Option A). Before a job exists the ledger
    # cannot verify pre-job source-card / task-spec completion: there is no job
    # scope yet, and the AgentRun does not track its own source-id list
    # (commits dict-merge and overwrite source_id). The /essay-prep script runs
    # ingest -> source cards -> task spec -> create_job as a deterministic
    # prelude that the create_job_from_artifacts gate already guards (it refuses
    # without committed cards, a task spec, and a writing-style decision). So
    # before a job exists, point the driver straight at job_created instead of
    # at the unverifiable parallel steps, which would otherwise leave
    # next_required_step stuck on source_cards forever and deadlock the loop.
    if segment == "prep" and job is None:
        next_required_step = "job_created"

    return {
        "segment": segment,
        "job_id": run.job_id,
        "steps": [asdict(s) for s in steps],
        "next_required_step": next_required_step,
        "all_required_done": all_required_done,
        "warnings": warnings,
    }
