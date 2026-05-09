from __future__ import annotations

from pathlib import Path

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.sources.schema import SourceCard, SourceIngestionConfig
from pdf_pipeline.models import DocumentExtractionResult, PageText
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import ExplodingLLMClient


class FakeExtractor:
    def __init__(self, result: DocumentExtractionResult) -> None:
        self.result = result
        self.calls: list[Path] = []

    def extract(self, document_path: str | Path) -> DocumentExtractionResult:
        self.calls.append(Path(document_path))
        return self.result


def test_ingest_source_file_materializes_text_without_source_card_or_llm() -> None:
    with LocalAgentTempDir() as tmp:
        source_path = _touch_pdf(tmp / "source.pdf")
        facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            source_ingestion_config=SourceIngestionConfig(min_text_chars_per_page=5),
            document_reader=FakeExtractor(
                _result(
                    source_path,
                    page_count=1,
                    page_texts=["Readable uploaded source evidence."],
                )
            ),
            llm_guard=ExplodingLLMClient(),
        )

        result = facade.ingest_source_file(str(source_path), source_id="src-materialized")
        source_dir = tmp / "data" / "sources" / "src-materialized"
        assert (source_dir / "source.json").exists()
        assert (source_dir / "pages.jsonl").exists()
        assert (source_dir / "chunks.jsonl").exists()
        assert (source_dir / "source_map.json").exists()
        assert not (source_dir / "source_card.json").exists()

        assert result.ok is True
        assert result.data["source_id"] == "src-materialized"
        assert result.data["source_card_status"] == "pending"
        assert result.next_suggested_tools == ["prepare_source_card"]


def test_ingest_source_file_reuses_existing_materialized_source_without_extracting() -> None:
    with LocalAgentTempDir() as tmp:
        source_path = _touch_pdf(tmp / "source.pdf")
        first_reader = FakeExtractor(
            _result(
                source_path,
                page_count=1,
                page_texts=["Readable uploaded source evidence."],
            )
        )
        facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            source_ingestion_config=SourceIngestionConfig(min_text_chars_per_page=5),
            document_reader=first_reader,
        )

        first = facade.ingest_source_file(source_path, source_id="src-materialized")
        second_reader = FakeExtractor(
            _result(source_path, page_count=1, page_texts=["This should not be read."])
        )
        second_facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            source_ingestion_config=SourceIngestionConfig(min_text_chars_per_page=5),
            document_reader=second_reader,
        )
        second = second_facade.ingest_source_file(source_path, source_id="src-materialized")

    assert first.ok is True
    assert second.ok is True
    assert first_reader.calls == [source_path]
    assert second_reader.calls == []
    assert second.data["source_id"] == "src-materialized"
    assert second.data["char_count"] == first.data["char_count"]


def test_ingest_source_file_rejects_unsupported_suffix() -> None:
    with LocalAgentTempDir() as tmp:
        source_path = tmp / "source.exe"
        source_path.write_bytes(b"not-a-source")
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.ingest_source_file(source_path, source_id="src-unsupported")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unsupported_source_type"
    assert "unsupported source file type" in result.error.message


def test_ingest_source_file_rejects_directory_path() -> None:
    with LocalAgentTempDir() as tmp:
        source_path = tmp / "source.pdf"
        source_path.mkdir()
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.ingest_source_file(source_path, source_id="src-directory")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "source_document_not_file"


def test_ingest_source_file_does_not_advertise_missing_manifest() -> None:
    with LocalAgentTempDir() as tmp:
        source_path = _touch_pdf(tmp / "source.pdf")
        facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            source_ingestion_config=SourceIngestionConfig(
                index_sources=False,
                min_text_chars_per_page=5,
            ),
            document_reader=FakeExtractor(
                _result(
                    source_path,
                    page_count=1,
                    page_texts=["Readable uploaded source evidence."],
                )
            ),
        )

        result = facade.ingest_source_file(source_path, source_id="src-no-manifest")

    assert result.ok is True
    assert "source_map" in result.data["artifact_refs"]
    assert "manifest" not in result.data["artifact_refs"]


def test_missing_agent_run_does_not_materialize_source() -> None:
    with LocalAgentTempDir() as tmp:
        source_path = _touch_pdf(tmp / "source.pdf")
        reader = FakeExtractor(
            _result(
                source_path,
                page_count=1,
                page_texts=["Readable uploaded source evidence."],
            )
        )
        facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            source_ingestion_config=SourceIngestionConfig(min_text_chars_per_page=5),
            document_reader=reader,
        )

        result = facade.ingest_source_file(
            source_path,
            source_id="src-missing-run",
            agent_run_id="missing-run",
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "agent_run_not_found"
    assert reader.calls == []
    assert not (tmp / "data" / "sources" / "src-missing-run").exists()


def test_source_card_status_is_committed_after_source_card_is_saved() -> None:
    with LocalAgentTempDir() as tmp:
        source_path = _touch_pdf(tmp / "source.pdf")
        facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            source_ingestion_config=SourceIngestionConfig(min_text_chars_per_page=5),
            document_reader=FakeExtractor(
                _result(
                    source_path,
                    page_count=1,
                    page_texts=["Readable uploaded source evidence."],
                )
            ),
        )
        materialized = facade.ingest_source_file(source_path, source_id="src-materialized")
        facade.stores.source_store.save_source_card(
            "src-materialized",
            SourceCard(
                source_id="src-materialized",
                title="Uploaded Source",
                source_type="pdf",
                page_count=1,
                extraction_method="pypdf",
                brief_summary="Summary.",
            ),
        )

        refreshed = facade.ingest_source_file(source_path, source_id="src-materialized")

    assert materialized.data["source_card_status"] == "pending"
    assert refreshed.ok is True
    assert refreshed.data["source_card_status"] == "committed"


def _touch_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-pretend-for-fake-extractor")
    return path


def _result(
    source_path: Path,
    *,
    page_count: int,
    page_texts: list[str],
    method: str = "pypdf",
) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        source_path=str(source_path),
        page_count=page_count,
        pages=[
            PageText(
                page_number=idx,
                text=text,
                char_count=len(text),
                extraction_method=method,
            )
            for idx, text in enumerate(page_texts, start=1)
        ],
    )
