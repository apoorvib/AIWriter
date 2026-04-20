from __future__ import annotations

import pytest

from essay_writer.research_planning.schema import ResearchPlan, SourceReadingPriority
from essay_writer.research_planning.storage import ResearchPlanStore
from tests.task_spec._tmp import LocalTempDir


def test_research_plan_store_saves_loads_latest_and_next_version() -> None:
    with LocalTempDir() as tmp_path:
        store = ResearchPlanStore(tmp_path / "plans")
        store.save(_plan(1))
        store.save(_plan(2))

        latest = store.load_latest("job1")
        next_version = store.next_version("job1")

    assert latest.version == 2
    assert latest.uploaded_source_priorities[0].source_id == "src1"
    assert next_version == 3


def test_research_plan_store_rejects_overwrite() -> None:
    with LocalTempDir() as tmp_path:
        store = ResearchPlanStore(tmp_path / "plans")
        store.save(_plan(1))

        with pytest.raises(FileExistsError):
            store.save(_plan(1))


def _plan(version: int) -> ResearchPlan:
    return ResearchPlan(
        id=f"research_plan_v{version:03d}",
        job_id="job1",
        selected_topic_id="topic_001",
        version=version,
        research_question="Question?",
        source_requirements=["Use uploaded sources."],
        uploaded_source_priorities=[
            SourceReadingPriority(
                source_id="src1",
                priority="high",
                rationale="Read first.",
                chunk_ids=["c1"],
            )
        ],
        expected_evidence_categories=["thesis_support"],
    )
