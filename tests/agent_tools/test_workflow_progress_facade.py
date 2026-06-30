# tests/agent_tools/test_workflow_progress_facade.py
from essay_writer.agent_tools.facade import AgentToolFacade


def test_get_workflow_progress_returns_ledger(tmp_path):
    facade = AgentToolFacade.from_data_dir(
        tmp_path, enforce_attention_challenge=False,
        require_agent_run=False, require_anti_ai_audit=False,
    )
    start = facade.start_agent_run(objective="essay")
    run_id = start.data["agent_run_id"]
    result = facade.get_workflow_progress(agent_run_id=run_id)
    assert result.ok is True
    assert result.tool_name == "get_workflow_progress"
    assert result.data["segment"] == "prep"
    # Pre-job the driver is pointed at job_created (Option A scripted prelude).
    assert result.data["next_required_step"] == "job_created"


def test_get_workflow_progress_missing_run(tmp_path):
    facade = AgentToolFacade.from_data_dir(tmp_path)
    result = facade.get_workflow_progress(agent_run_id="nope")
    assert result.ok is False
    # _missing_run_result uses code="agent_run_not_found" (not "missing_run")
    assert result.error.code == "agent_run_not_found"


from essay_writer.agent_tools.phases import READ_ONLY_TOOLS


def test_get_workflow_progress_is_read_only():
    assert "get_workflow_progress" in READ_ONLY_TOOLS
