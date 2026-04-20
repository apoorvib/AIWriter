from __future__ import annotations

import pytest

from essay_writer.validation.schema import (
    AssignmentFit,
    CitationMetadataWarning,
    DeterministicCheckResult,
    LLMJudgmentResult,
    LengthCheck,
    ValidationReport,
)
from essay_writer.validation.storage import ValidationStore
from tests.task_spec._tmp import LocalTempDir


def test_validation_store_saves_and_loads_latest() -> None:
    with LocalTempDir() as tmp_path:
        store = ValidationStore(tmp_path / "validation_store")
        store.save("job1", _report("draft1"), version=1)
        store.save("job1", _report("draft2"), version=2)

        loaded = store.load_latest("job1")

    assert loaded.draft_id == "draft2"
    assert loaded.passes is True


def test_validation_store_rejects_overwrite() -> None:
    with LocalTempDir() as tmp_path:
        store = ValidationStore(tmp_path / "validation_store")
        report = _report("draft1")

        store.save("job1", report, version=1)
        with pytest.raises(FileExistsError):
            store.save("job1", report, version=1)


def test_validation_store_round_trips_metadata_citation_warnings() -> None:
    with LocalTempDir() as tmp_path:
        store = ValidationStore(tmp_path / "validation_store")
        report = _report("draft1", metadata_warnings=[
            CitationMetadataWarning(source_id="src1", description="Missing source metadata.")
        ])

        store.save("job1", report, version=1)
        loaded = store.load_latest("job1")

    assert loaded.metadata_citation_warnings[0].source_id == "src1"
    assert loaded.metadata_citation_warnings[0].description == "Missing source metadata."


def _report(
    draft_id: str,
    *,
    metadata_warnings: list[CitationMetadataWarning] | None = None,
) -> ValidationReport:
    return ValidationReport(
        draft_id=draft_id,
        task_spec_id="task1",
        deterministic=DeterministicCheckResult(
            word_count=10,
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
            length_check=LengthCheck(actual_words=10, target_words=None, passes=True),
            style_issues=[],
            revision_suggestions=[],
            overall_quality=0.8,
        ),
        metadata_citation_warnings=metadata_warnings or [],
    )
