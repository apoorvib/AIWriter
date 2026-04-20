from __future__ import annotations

import pytest

from essay_writer.drafting.schema import EssayDraft, SectionSourceMap
from essay_writer.exporting.service import FinalExportService
from essay_writer.exporting.storage import FinalExportStore
from essay_writer.jobs.schema import EssayJob
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.validation.schema import (
    AssignmentFit,
    DeterministicCheckResult,
    LLMJudgmentResult,
    LengthCheck,
    ValidationReport,
)
from tests.task_spec._tmp import LocalTempDir


def test_final_export_service_creates_markdown_with_source_map() -> None:
    draft = EssayDraft(
        id="draft1",
        job_id="job1",
        version=1,
        selected_topic_id="topic_001",
        content="Essay body.",
        section_source_map=[
            SectionSourceMap(
                section_id="s1",
                heading="Body",
                note_ids=["note_001"],
                source_ids=["src1"],
            )
        ],
    )
    export = FinalExportService().create_markdown_export(
        job=EssayJob(id="job1", draft_id="draft1", validation_report_id="draft1:v001"),
        task_spec=TaskSpecification(id="task1", version=1, raw_text="Assignment.", assignment_title="Assignment Title"),
        draft=draft,
        validation=_report("draft1"),
    )

    assert export.id == "final_export_001"
    assert export.export_format == "markdown"
    assert "# Assignment Title" in export.content
    assert "Essay body." in export.content
    assert export.source_map[0]["note_ids"] == ["note_001"]


def test_final_export_store_saves_markdown_and_json() -> None:
    draft = EssayDraft(id="draft1", job_id="job1", version=1, selected_topic_id="topic_001", content="Essay body.")
    export = FinalExportService().create_markdown_export(
        job=EssayJob(id="job1", draft_id="draft1", validation_report_id="draft1:v001"),
        task_spec=TaskSpecification(id="task1", version=1, raw_text="Assignment."),
        draft=draft,
        validation=_report("draft1"),
    )

    with LocalTempDir() as tmp_path:
        store = FinalExportStore(tmp_path / "exports")
        store.save(export)
        loaded = store.load_latest("job1")

        assert (tmp_path / "exports" / "job1" / "final_export_001.md").exists()
        with pytest.raises(FileExistsError):
            store.save(export)

    assert loaded == export


def _report(draft_id: str) -> ValidationReport:
    return ValidationReport(
        draft_id=draft_id,
        task_spec_id="task1",
        deterministic=DeterministicCheckResult(
            word_count=2,
            em_dash_count=0,
            tier1_vocab_hits=[],
            bad_conclusion_opener=False,
            consecutive_similar_sentence_runs=[],
            participial_phrase_count=0,
            participial_phrase_rate=0.0,
            contrastive_negation_count=0,
            signposting_hits=[],
        ),
        llm_judgment=LLMJudgmentResult(
            unsupported_claims=[],
            citation_issues=[],
            rubric_scores=[],
            assignment_fit=AssignmentFit(passes=True, explanation="Fits."),
            length_check=LengthCheck(actual_words=2, target_words=None, passes=True),
            style_issues=[],
            revision_suggestions=[],
            overall_quality=0.8,
        ),
    )
