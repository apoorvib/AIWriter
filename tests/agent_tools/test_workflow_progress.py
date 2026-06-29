from essay_writer.agent_tools.schemas import AgentRun
from essay_writer.agent_tools.workflow_progress import build_workflow_progress


def test_no_job_reports_prep_segment_first_step(tmp_path):
    from essay_writer.agent_tools.stores import AgentStoreBundle
    stores = AgentStoreBundle.from_data_dir(tmp_path)
    run = AgentRun(agent_run_id="run-1", objective="x", job_id=None)
    progress = build_workflow_progress(run, stores)
    assert progress["segment"] == "prep"
    assert progress["all_required_done"] is False
    # Pre-job (Option A): the driver is pointed at job_created, whose MCP gate
    # enforces the cards+task-spec+writing-style prelude. The parallel prep
    # steps cannot be verified before a job exists, so the loop must not select
    # source_cards (which would deadlock — it never creates a job).
    assert progress["next_required_step"] == "job_created"
    step_ids = [s["step_id"] for s in progress["steps"]]
    assert "source_cards" in step_ids and "task_spec" in step_ids and "job_created" in step_ids


def test_step_status_is_pending_when_artifact_absent(tmp_path):
    from essay_writer.agent_tools.stores import AgentStoreBundle
    stores = AgentStoreBundle.from_data_dir(tmp_path)
    run = AgentRun(agent_run_id="run-1", objective="x", job_id=None)
    progress = build_workflow_progress(run, stores)
    by_id = {s["step_id"]: s for s in progress["steps"]}
    assert by_id["task_spec"]["status"] == "pending"
    assert by_id["topics"]["blocked_by"]  # blocked by earlier prep steps


def test_writing_style_decision_ordered_after_job_created(tmp_path):
    # writing_style_decision lives ON the job, so it must come AFTER job_created.
    # If it preceded job_created (non-serial), next_required_step could point at a
    # step that cannot be completed before the job exists, stalling the prep loop.
    from essay_writer.agent_tools.stores import AgentStoreBundle
    stores = AgentStoreBundle.from_data_dir(tmp_path)
    run = AgentRun(agent_run_id="run-1", objective="x", job_id=None)
    progress = build_workflow_progress(run, stores)
    order = [s["step_id"] for s in progress["steps"]]
    assert order.index("job_created") < order.index("writing_style_decision")
    # With no job yet, the loop must never select writing_style_decision; under
    # Option A it is pointed at job_created (the prelude's gated endpoint).
    assert progress["next_required_step"] == "job_created"
    by_id = {s["step_id"]: s for s in progress["steps"]}
    # It is a serial step gated behind the pending job_created step.
    assert by_id["writing_style_decision"]["status"] == "blocked"
    assert "job_created" in by_id["writing_style_decision"]["blocked_by"]


def test_draft_present_but_audit_absent_keeps_audit_pending(tmp_path):
    import dataclasses
    from essay_writer.agent_tools.stores import AgentStoreBundle
    from essay_writer.drafting.schema import EssayDraft

    stores = AgentStoreBundle.from_data_dir(tmp_path)
    job = stores.workflow.create_job(task_spec_id="ts-1", source_ids=["src-1"])
    # Move the job into the write segment with all pre-audit required steps done
    # (topic_selected, research_plan, research_notes, outline, draft), but no
    # anti-AI audit on the draft so the anti_ai_audit step stays pending.
    draft = EssayDraft(
        id="draft-1", job_id=job.id, version=1,
        selected_topic_id="topic-1", content="A.\n\nB.",
    )
    stores.draft_store.save(draft)
    stores.job_store.save(dataclasses.replace(
        job,
        selected_topic_id="topic-1",
        research_plan_id="plan-1",
        evidence_map_id="em-1",
        outline_id="outline-1",
        draft_id="draft-1",
    ))

    run = AgentRun(agent_run_id="run-1", objective="x", job_id=job.id)
    progress = build_workflow_progress(run, stores)
    by_id = {s["step_id"]: s for s in progress["steps"]}
    assert progress["segment"] == "write"
    assert by_id["anti_ai_audit"]["status"] == "pending"
    assert progress["next_required_step"] == "anti_ai_audit"
    assert progress["all_required_done"] is False
