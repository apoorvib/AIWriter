"""Windowed style-revision tests: long drafts must fan out into per-window packets."""
from __future__ import annotations

from dataclasses import replace

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.drafting.schema import EssayDraft
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import main_agent
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


SHORT_PARAGRAPH = (
    "Cooling access in rental housing is uneven. The source documents the gap "
    "between buildings with central air conditioning and those without."
)


def _replace_draft_with_long_content(facade: AgentToolFacade, *, paragraphs: int) -> EssayDraft:
    previous = facade.stores.draft_store.load_latest("job1")
    long_content = "\n\n".join([SHORT_PARAGRAPH] * paragraphs)
    next_version = facade.stores.draft_store.next_version("job1")
    new_draft = replace(
        previous,
        id=f"draft_long_{next_version:03d}",
        version=next_version,
        content=long_content,
    )
    facade.stores.draft_store.save(new_draft)
    return new_draft


def test_prepare_style_revision_returns_single_packet_for_short_draft() -> None:
    """Short drafts must keep the existing single-packet behavior (no windowing)."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)

        prepared = facade.prepare_style_revision("job1")

    assert prepared.ok is True
    assert prepared.data.get("windowing", {}).get("mode", "single") == "single"
    # Single-packet packets keep stage="style_revision" and a direct work_packet_id
    assert prepared.data["stage"] == "style_revision"
    assert "work_packet_id" in prepared.data


def test_prepare_style_revision_returns_windowing_plan_for_long_draft() -> None:
    """Drafts above the threshold must return a windowing plan instead of a single packet."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        # SHORT_PARAGRAPH is ~22 words; 80 paragraphs = ~1760 words, above 1200 threshold
        _replace_draft_with_long_content(facade, paragraphs=80)

        prepared = facade.prepare_style_revision("job1")

    assert prepared.ok is True
    assert prepared.data["windowing"]["mode"] == "windowed"
    windows = prepared.data["windowing"]["windows"]
    assert len(windows) >= 2
    # Windows must cover the entire draft contiguously
    assert windows[0]["paragraph_start"] == 0
    for prev, curr in zip(windows, windows[1:]):
        assert curr["paragraph_start"] == prev["paragraph_end"]
    assert windows[-1]["paragraph_end"] == 80
    # Each window should be reasonably sized (around the target)
    for window in windows:
        assert 1 <= window["word_count"] <= 1000
    assert "parent_packet_id" in prepared.data
    assert prepared.next_suggested_tools == ["prepare_style_revision_window"]


def test_prepare_style_revision_window_returns_per_window_packet_with_skill_prompt() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        _replace_draft_with_long_content(facade, paragraphs=80)

        prepared = facade.prepare_style_revision("job1")
        parent_id = prepared.data["parent_packet_id"]
        total = len(prepared.data["windowing"]["windows"])

        window0 = facade.prepare_style_revision_window(parent_id, 0)
        window_last = facade.prepare_style_revision_window(parent_id, total - 1)

    assert window0.ok is True
    assert window_last.ok is True
    assert window0.data["commit_tool"] == "commit_style_revision"
    assert window0.data["stage"] == "style_revision_window"
    assert window0.data["window_index"] == 0
    assert window_last.data["window_index"] == total - 1
    # full anti-AI skill must be in every window's system_prompt
    assert "<anti_ai_detection_skill>" in window0.data["system_prompt"]
    assert "<anti_ai_detection_skill>" in window_last.data["system_prompt"]
    # each window packet must declare its parent and total
    assert window0.data["parent_packet_id"] == parent_id
    assert window0.data["total_windows"] == total


def test_prepare_style_revision_window_rejects_out_of_range_index() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        _replace_draft_with_long_content(facade, paragraphs=80)
        prepared = facade.prepare_style_revision("job1")
        parent_id = prepared.data["parent_packet_id"]
        total = len(prepared.data["windowing"]["windows"])

        result = facade.prepare_style_revision_window(parent_id, total)  # one past end

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "window_index_out_of_range"


def test_commit_style_revision_assembles_window_results_into_single_draft() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        previous = _replace_draft_with_long_content(facade, paragraphs=80)

        prepared = facade.prepare_style_revision("job1")
        parent_id = prepared.data["parent_packet_id"]
        windows = prepared.data["windowing"]["windows"]

        result_ids: list[str] = []
        for window_meta in windows:
            window_packet = facade.prepare_style_revision_window(
                parent_id, window_meta["index"]
            )
            revised_window_text = f"Revised window {window_meta['index']}. Plain prose."
            submitted = facade.submit_work_result(
                str(window_packet.data["work_packet_id"]),
                payload={
                    "content": revised_window_text,
                    "style_changes": [],
                    "preservation_notes": [],
                    "known_risks": [],
                },
                producer=main_agent(),
            )
            result_ids.append(str(submitted.data["work_result_id"]))

        committed = facade.commit_style_revision(work_result_ids=result_ids)
        revised_draft = facade.stores.draft_store.load_latest("job1")

    assert committed.ok is True
    assert committed.data["already_committed"] is False
    assert revised_draft.version == previous.version + 1
    assert revised_draft.origin == "style_revision"
    # assembled content must include each window's text in window-index order
    for window_meta in windows:
        marker = f"Revised window {window_meta['index']}."
        assert marker in revised_draft.content
    # window-0 text must appear before window-1 text
    if len(windows) >= 2:
        assert revised_draft.content.index("Revised window 0.") < revised_draft.content.index(
            "Revised window 1."
        )
