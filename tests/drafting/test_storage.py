from __future__ import annotations

import pytest

from essay_writer.drafting.schema import EssayDraft, SectionSourceMap
from essay_writer.drafting.storage import DraftStore
from tests.task_spec._tmp import LocalTempDir


def test_draft_store_saves_and_loads_latest() -> None:
    with LocalTempDir() as tmp_path:
        store = DraftStore(tmp_path / "draft_store")
        store.save(_draft(version=1, content="First."))
        store.save(_draft(version=2, content="Second."))

        loaded = store.load_latest("job1")

    assert loaded.version == 2
    assert loaded.content == "Second."
    assert loaded.section_source_map[0].note_ids == ["note_001"]


def test_draft_store_rejects_overwrite() -> None:
    with LocalTempDir() as tmp_path:
        store = DraftStore(tmp_path / "draft_store")
        draft = _draft(version=1, content="First.")

        store.save(draft)
        with pytest.raises(FileExistsError):
            store.save(draft)


def _draft(*, version: int, content: str) -> EssayDraft:
    return EssayDraft(
        id=f"draft_{version}",
        job_id="job1",
        version=version,
        selected_topic_id="topic_001",
        content=content,
        section_source_map=[
            SectionSourceMap(
                section_id="s1",
                heading="Body",
                note_ids=["note_001"],
                source_ids=["src1"],
            )
        ],
    )
