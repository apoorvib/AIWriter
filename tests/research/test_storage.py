from __future__ import annotations

import pytest

from essay_writer.research.schema import (
    EvidenceGroup,
    EvidenceMap,
    FinalTopicResearchResult,
    ResearchNote,
    ResearchReport,
)
from essay_writer.research.storage import ResearchStore
from tests.task_spec._tmp import LocalTempDir


def test_research_store_saves_and_loads_latest_version() -> None:
    with LocalTempDir() as tmp_path:
        store = ResearchStore(tmp_path / "research_store")
        store.save_result(_result("job1", "evidence_map_v001"), version=1)
        store.save_result(_result("job1", "evidence_map_v002"), version=2)

        loaded = store.load_latest("job1")

    assert loaded.evidence_map.id == "evidence_map_v002"
    assert loaded.evidence_map.notes[0].chunk_id == "chunk1"
    assert loaded.evidence_map.evidence_groups[0].note_ids == ["note_001"]
    assert loaded.report.note_count == 1


def test_research_store_rejects_overwrite() -> None:
    with LocalTempDir() as tmp_path:
        store = ResearchStore(tmp_path / "research_store")
        result = _result("job1", "evidence_map_v001")

        store.save_result(result, version=1)
        with pytest.raises(FileExistsError):
            store.save_result(result, version=1)


def _result(job_id: str, evidence_map_id: str) -> FinalTopicResearchResult:
    note = ResearchNote(
        id="note_001",
        source_id="src1",
        chunk_id="chunk1",
        page_start=1,
        page_end=1,
        claim="Claim.",
        quote=None,
        paraphrase="Paraphrase.",
        relevance="Relevant.",
        supports_topic=True,
        evidence_type="argument",
        confidence=0.8,
    )
    group = EvidenceGroup(
        id="group_001",
        label="Support",
        purpose="thesis_support",
        note_ids=["note_001"],
        synthesis="Synthesis.",
    )
    evidence_map = EvidenceMap(
        id=evidence_map_id,
        job_id=job_id,
        selected_topic_id="topic_001",
        research_question="Question?",
        thesis_direction="Thesis.",
        notes=[note],
        evidence_groups=[group],
        gaps=[],
        conflicts=[],
        source_ids=["src1"],
    )
    report = ResearchReport(
        job_id=job_id,
        selected_topic_id="topic_001",
        evidence_map_id=evidence_map.id,
        note_count=1,
        source_count=1,
    )
    return FinalTopicResearchResult(evidence_map=evidence_map, report=report)
