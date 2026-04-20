from __future__ import annotations

from pathlib import Path

import pytest

from llm.mock import MockLLMClient
from pdf_pipeline.models import DocumentExtractionResult, PageText
from essay_writer.jobs import EssayJobStore, EssayWorkflow
from essay_writer.sources import SourceIngestionService, SourceStore
from essay_writer.sources.schema import SourceIngestionConfig
from essay_writer.task_spec.parser import TaskSpecParser
from essay_writer.task_spec.storage import TaskSpecStore
from essay_writer.topic_ideation.service import TopicIdeationService
from essay_writer.topic_ideation.storage import TopicRoundStore
from essay_writer.workflow.bootstrap import MvpWorkflowBootstrapper, WorkflowBlockedError
from tests.task_spec._tmp import LocalTempDir


class FakeExtractor:
    def __init__(self, result: DocumentExtractionResult) -> None:
        self.result = result
        self.calls: list[Path] = []

    def extract(self, document_path: str | Path) -> DocumentExtractionResult:
        self.calls.append(Path(document_path))
        return self.result


def test_bootstrap_creates_job_from_pasted_assignment_and_uploaded_sources() -> None:
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "housing.pdf")
        bootstrapper, stores = _bootstrapper(
            tmp_path,
            source_reader=FakeExtractor(
                _result(
                    source_path,
                    [
                        "Urban heat policy and housing vulnerability evidence.",
                        "Renters in older buildings face cooling access gaps.",
                    ],
                )
            ),
        )

        result = bootstrapper.create_job_from_inputs(
            job_id="job1",
            assignment_text="Urban heat essay\nWrite 1000 words in MLA. Cite uploaded sources.",
            source_paths=[source_path],
        )
        loaded_task = stores["task_store"].load_latest(result.task_spec.id)
        loaded_job = stores["job_store"].load(result.job.id)

    assert result.job.status == "sources_ready"
    assert result.job.current_stage == "topic_ideation"
    assert loaded_job.task_spec_id == "job1-task"
    assert loaded_job.source_ids == [result.source_results[0].source.id]
    assert loaded_task.raw_text.startswith("Urban heat essay")
    assert loaded_task.source_document_ids == loaded_job.source_ids
    assert result.source_results[0].indexed is True
    assert result.index_manifests[0].source_id == loaded_job.source_ids[0]


def test_bootstrap_reads_assignment_file_without_treating_it_as_a_source() -> None:
    with LocalTempDir() as tmp_path:
        assignment_path = _touch_pdf(tmp_path / "assignment.pdf")
        assignment_reader = FakeExtractor(
            _result(
                assignment_path,
                [
                    "Research essay assignment.",
                    "Choose one prompt and write 5 pages in APA format.",
                ],
            )
        )
        bootstrapper, stores = _bootstrapper(
            tmp_path,
            assignment_reader=assignment_reader,
            source_reader=FakeExtractor(_result(tmp_path / "unused.pdf", ["unused"])),
        )

        result = bootstrapper.create_job_from_inputs(
            job_id="job1",
            assignment_path=assignment_path,
            selected_prompt="Analyze housing adaptation.",
        )
        loaded_job = stores["job_store"].load("job1")

    assert assignment_reader.calls == [assignment_path]
    assert result.task_spec.raw_text == (
        "Research essay assignment.\n\n"
        "Choose one prompt and write 5 pages in APA format."
    )
    assert result.task_spec.selected_prompt == "Analyze housing adaptation."
    assert loaded_job.status == "task_spec_ready"
    assert loaded_job.current_stage == "source_ingestion"
    assert loaded_job.source_ids == []


def test_bootstrap_can_generate_and_persist_initial_topic_round_with_indexes() -> None:
    with LocalTempDir() as tmp_path:
        source_path = _touch_pdf(tmp_path / "heat.pdf")
        llm = MockLLMClient(responses=[_topic_response()])
        bootstrapper, stores = _bootstrapper(
            tmp_path,
            source_reader=FakeExtractor(
                _result(
                    source_path,
                    [
                        "Urban heat exposure is patterned by housing quality.",
                        "Cooling access is uneven across rental neighborhoods.",
                    ],
                )
            ),
            topic_llm=llm,
        )

        result = bootstrapper.create_job_and_topic_round(
            job_id="job1",
            assignment_text="Write a 1200 word MLA essay using the uploaded sources.",
            source_paths=[source_path],
            user_instruction="Give me policy-oriented choices.",
        )
        loaded_round = stores["topic_store"].load_round("job1", 1)
        loaded_job = stores["job_store"].load("job1")

    assert result.job.status == "topic_selection_ready"
    assert result.topic_round.id == "job1-topic-round-001"
    assert loaded_round.user_instruction == "Give me policy-oriented choices."
    assert loaded_round.candidates[0].title == "Urban heat as housing policy"
    assert loaded_job.topic_round_ids == ["job1-topic-round-001"]
    assert '"source_index_manifests"' in llm.calls[0]["user"]
    assert "Complete chunk index:" in llm.calls[0]["user"]
    assert result.index_manifests[0].total_chunks >= 1


def test_bootstrap_blocks_when_task_spec_has_blocking_questions() -> None:
    with LocalTempDir() as tmp_path:
        llm = MockLLMClient(responses=[_topic_response()])
        bootstrapper, stores = _bootstrapper(
            tmp_path,
            source_reader=FakeExtractor(_result(tmp_path / "unused.pdf", ["unused"])),
            topic_llm=llm,
        )

        result = bootstrapper.create_job_from_inputs(
            job_id="job1",
            assignment_text=(
                "Essay prompt\n"
                "A. Write about urban heat.\n"
                "B. Write about housing affordability.\n"
                "Use MLA format."
            ),
        )
        loaded_job = stores["job_store"].load("job1")

        with pytest.raises(WorkflowBlockedError):
            bootstrapper.create_job_and_topic_round(
                job_id="job2",
                assignment_text=(
                    "Essay prompt\n"
                    "A. Write about urban heat.\n"
                    "B. Write about housing affordability.\n"
                    "Use MLA format."
                ),
            )
        resolved = bootstrapper.resolve_task_spec_block(
            job_id="job1",
            selected_prompt="Write about urban heat.",
        )
        resolved_latest_task = stores["task_store"].load_latest("job1-task")

    assert result.job.status == "blocked"
    assert result.job.current_stage == "task_specification"
    assert result.job.error_state is not None
    assert "Which prompt" in result.job.error_state.message
    assert loaded_job.status == "blocked"
    assert llm.calls == []
    assert resolved.job.status == "task_spec_ready"
    assert resolved.job.current_stage == "source_ingestion"
    assert resolved.job.error_state is None
    assert resolved.task_spec.version == 2
    assert resolved.task_spec.blocking_questions == []
    assert resolved_latest_task.version == 2


def test_bootstrap_records_error_when_source_ingestion_fails_after_job_creation() -> None:
    with LocalTempDir() as tmp_path:
        bootstrapper, stores = _bootstrapper(
            tmp_path,
            source_reader=FakeExtractor(_result(tmp_path / "unused.pdf", ["unused"])),
        )

        with pytest.raises(FileNotFoundError):
            bootstrapper.create_job_from_inputs(
                job_id="job1",
                assignment_text="Write about urban heat in MLA.",
                source_paths=[tmp_path / "missing.pdf"],
            )
        loaded_job = stores["job_store"].load("job1")

    assert loaded_job.status == "error"
    assert loaded_job.current_stage == "source_ingestion"
    assert loaded_job.error_state is not None
    assert "source document not found" in loaded_job.error_state.message


def _bootstrapper(
    tmp_path: Path,
    *,
    source_reader: FakeExtractor,
    assignment_reader: FakeExtractor | None = None,
    topic_llm: MockLLMClient | None = None,
):
    job_store = EssayJobStore(tmp_path / "essay_store")
    topic_store = TopicRoundStore(tmp_path / "topic_store")
    source_store = SourceStore(tmp_path / "source_store")
    stores = {
        "job_store": job_store,
        "topic_store": topic_store,
        "task_store": TaskSpecStore(tmp_path / "task_store"),
        "source_store": source_store,
    }
    return (
        MvpWorkflowBootstrapper(
            workflow=EssayWorkflow(job_store, topic_store),
            task_parser=TaskSpecParser(),
            task_store=stores["task_store"],
            source_ingestion=SourceIngestionService(
                source_store,
                config=SourceIngestionConfig(
                    min_text_chars_per_page=5,
                    source_card_context_char_budget=1_000,
                ),
                document_reader=source_reader,
            ),
            topic_ideation=TopicIdeationService(topic_llm) if topic_llm is not None else None,
            assignment_reader=assignment_reader,
        ),
        stores,
    )


def _touch_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-pretend-for-fake-extractor")
    return path


def _result(source_path: Path, page_texts: list[str]) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        source_path=str(source_path),
        page_count=len(page_texts),
        pages=[
            PageText(
                page_number=idx,
                text=text,
                char_count=len(text),
                extraction_method="pypdf",
            )
            for idx, text in enumerate(page_texts, start=1)
        ],
    )


def _topic_response() -> dict:
    return {
        "candidates": [
            {
                "title": "Urban heat as housing policy",
                "research_question": "How should cities treat cooling access as a housing issue?",
                "tentative_thesis_direction": "Cooling access belongs in housing policy.",
                "rationale": "The uploaded source connects heat exposure to rental housing quality.",
                "source_leads": [],
                "fit_score": 0.9,
                "evidence_score": 0.8,
                "originality_score": 0.7,
            }
        ],
        "blocking_questions": [],
        "warnings": [],
    }
