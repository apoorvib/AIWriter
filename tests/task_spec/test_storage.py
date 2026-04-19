from __future__ import annotations

import pytest

from essay_writer.task_spec.parser import TaskSpecParser
from essay_writer.task_spec.storage import TaskSpecStore
from tests.task_spec._tmp import LocalTempDir


def test_task_spec_store_round_trips_latest() -> None:
    with LocalTempDir() as tmp_path:
        store = TaskSpecStore(tmp_path)
        spec_v1 = TaskSpecParser().parse("Write 1000 words.", task_id="task1", version=1)
        spec_v2 = TaskSpecParser().parse("Write 1200 words.", task_id="task1", version=2)

        store.save(spec_v1)
        store.save(spec_v2)
        loaded = store.load_latest("task1")

        assert loaded.version == 2
        assert loaded.raw_text == "Write 1200 words."


def test_task_spec_store_rejects_overwrite() -> None:
    with LocalTempDir() as tmp_path:
        store = TaskSpecStore(tmp_path)
        spec = TaskSpecParser().parse("Use MLA.", task_id="task1", version=1)

        store.save(spec)
        with pytest.raises(FileExistsError):
            store.save(spec)
