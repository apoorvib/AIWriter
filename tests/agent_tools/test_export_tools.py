from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.test_outline_draft_validation_tools import _seed_job_through_validation


def test_export_markdown_persists_export_and_updates_job() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_validation(facade)

        exported = facade.export_markdown("job1")
        job = facade.stores.workflow.load_job("job1")

    assert exported.ok is True
    assert exported.data["export_id"] == "final_export_001"
    assert exported.data["format"] == "markdown"
    assert "# " in exported.data["preview"]
    assert job.final_export_id == "final_export_001"
