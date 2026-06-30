from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import main_agent
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
    _seed_job_through_validation,
)


def _seed_job_with_failing_validation(facade: AgentToolFacade) -> None:
    """Drive a job to a committed validation that does NOT pass."""
    _seed_job_through_draft(facade)
    prepared = facade.prepare_validation("job1")
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload={
            "unsupported_claims": [],
            "citation_issues": [],
            "rubric_scores": [],
            # assignment_fit.passes=False makes the report.passes property False.
            "assignment_fit": {"passes": False, "explanation": "Off topic."},
            "length_check": {"actual_words": 12, "target_words": None, "passes": True},
            "style_issues": [],
            "diagnostics": [],
            "revision_suggestions": [],
            "overall_quality": 0.4,
        },
        producer=main_agent(),
    )
    committed = facade.commit_validation(
        work_result_id=str(submitted.data["work_result_id"])
    )
    assert committed.ok is True


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
    assert "## Source Map" not in exported.data["content"]
    assert "## Validation" not in exported.data["content"]
    assert job.final_export_id == "final_export_001"


def test_export_refuses_failed_validation() -> None:
    """Tier-1 fix: a draft whose validation did not pass must not be
    exportable by default."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_with_failing_validation(facade)
        result = facade.export_markdown("job1")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "validation_not_passing"
    assert "prepare_revision" in result.next_suggested_tools


def test_export_allows_failed_validation_with_explicit_override() -> None:
    """The override exists for the deliberate case."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_with_failing_validation(facade)
        result = facade.export_markdown("job1", allow_failed_validation=True)
    assert result.ok is True
    assert result.data["format"] == "markdown"
