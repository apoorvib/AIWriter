from __future__ import annotations

from essay_writer.manual_revision.schema import ManualRevisionRequest, ManualRevisionRun
from essay_writer.manual_revision.storage import ManualRevisionRequestStore, ManualRevisionRunStore
from tests.task_spec._tmp import LocalTempDir


def test_manual_revision_request_store_saves_lists_and_loads() -> None:
    request = ManualRevisionRequest(
        id="manual_request_001",
        job_id="job1",
        source_draft_id="draft_001",
        mode="review_only",
        instruction="Review this.",
        selected_lenses=["tone", "anti_ai"],
    )

    with LocalTempDir() as tmp_path:
        store = ManualRevisionRequestStore(tmp_path / "manual_requests")
        store.save(request, version=1)

        listed = store.list_versions("job1")
        loaded = store.load("job1", 1)
        found = store.find_by_id("job1", "manual_request_001")

    assert [item.id for item in listed] == ["manual_request_001"]
    assert loaded == request
    assert found == request


def test_manual_revision_run_store_saves_lists_and_loads() -> None:
    run = ManualRevisionRun(
        id="manual_run_001",
        request_id="manual_request_001",
        job_id="job1",
        source_draft_id="draft_001",
        mode="review_only",
        instruction="Review this.",
        selected_lenses=["tone"],
        change_summary=["Word count changed from 100 to 110."],
    )

    with LocalTempDir() as tmp_path:
        store = ManualRevisionRunStore(tmp_path / "manual_runs")
        store.save(run, version=1)

        listed = store.list_versions("job1")
        loaded = store.load("job1", 1)
        found = store.find_by_id("job1", "manual_run_001")

    assert [item.id for item in listed] == ["manual_run_001"]
    assert loaded == run
    assert found == run
