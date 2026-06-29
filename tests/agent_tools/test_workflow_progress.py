from essay_writer.agent_tools.schemas import AgentRun
from essay_writer.agent_tools.workflow_progress import build_workflow_progress


def test_no_job_reports_prep_segment_first_step(tmp_path):
    from essay_writer.agent_tools.stores import AgentStoreBundle
    stores = AgentStoreBundle.from_data_dir(tmp_path)
    run = AgentRun(agent_run_id="run-1", objective="x", job_id=None)
    progress = build_workflow_progress(run, stores)
    assert progress["segment"] == "prep"
    assert progress["all_required_done"] is False
    assert progress["next_required_step"] == "source_cards"
    step_ids = [s["step_id"] for s in progress["steps"]]
    assert "task_spec" in step_ids and "job_created" in step_ids


def test_step_status_is_pending_when_artifact_absent(tmp_path):
    from essay_writer.agent_tools.stores import AgentStoreBundle
    stores = AgentStoreBundle.from_data_dir(tmp_path)
    run = AgentRun(agent_run_id="run-1", objective="x", job_id=None)
    progress = build_workflow_progress(run, stores)
    by_id = {s["step_id"]: s for s in progress["steps"]}
    assert by_id["task_spec"]["status"] == "pending"
    assert by_id["topics"]["blocked_by"]  # blocked by earlier prep steps
