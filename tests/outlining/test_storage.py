from __future__ import annotations

import pytest

from essay_writer.outlining.schema import OutlineSection, ThesisOutline
from essay_writer.outlining.storage import ThesisOutlineStore
from tests.task_spec._tmp import LocalTempDir


def test_thesis_outline_store_saves_loads_latest_and_next_version() -> None:
    with LocalTempDir() as tmp_path:
        store = ThesisOutlineStore(tmp_path / "outlines")
        store.save(_outline(1))
        store.save(_outline(2))

        latest = store.load_latest("job1")
        next_version = store.next_version("job1")

    assert latest.version == 2
    assert latest.sections[0].heading == "Introduction"
    assert next_version == 3


def test_thesis_outline_store_rejects_overwrite() -> None:
    with LocalTempDir() as tmp_path:
        store = ThesisOutlineStore(tmp_path / "outlines")
        store.save(_outline(1))

        with pytest.raises(FileExistsError):
            store.save(_outline(1))


def _outline(version: int) -> ThesisOutline:
    return ThesisOutline(
        id=f"thesis_outline_v{version:03d}",
        job_id="job1",
        selected_topic_id="topic_001",
        research_plan_id="research_plan_v001",
        evidence_map_id="evidence_map_v001",
        version=version,
        working_thesis="Thesis.",
        sections=[
            OutlineSection(
                id="section_001",
                heading="Introduction",
                purpose="intro",
            )
        ],
    )
