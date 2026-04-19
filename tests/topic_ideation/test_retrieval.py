from __future__ import annotations

from essay_writer.sources.index import SQLiteChunkIndex
from essay_writer.sources.manifest import build_index_manifest
from essay_writer.sources.schema import SourceCard, SourceChunk, SourceDocument, SourceIngestionResult, SourcePage
from essay_writer.sources.storage import SourceStore
from essay_writer.topic_ideation.retrieval import TopicEvidenceRetriever
from essay_writer.topic_ideation.schema import CandidateTopic, TopicSourceLead
from tests.task_spec._tmp import LocalTempDir


def test_topic_evidence_retriever_uses_explicit_chunk_ids_and_suggested_searches() -> None:
    with LocalTempDir() as tmp_path:
        store = SourceStore(tmp_path / "source_store")
        source_id = "src1"
        index_path = store.source_dir(source_id) / "index.sqlite"
        chunks = [
            SourceChunk(
                id="src1-chunk-0001",
                source_id=source_id,
                ordinal=1,
                page_start=1,
                page_end=1,
                text="Urban heat affects renters in older housing.",
                char_count=44,
            ),
            SourceChunk(
                id="src1-chunk-0002",
                source_id=source_id,
                ordinal=2,
                page_start=2,
                page_end=3,
                text="Tree canopy and cooling centers are common adaptation policies.",
                char_count=63,
            ),
        ]
        manifest = build_index_manifest(source_id=source_id, index_path=str(index_path), chunks=chunks)
        with SQLiteChunkIndex(index_path) as index:
            index.add_chunks(chunks)
        store.save_result(
            SourceIngestionResult(
                source=SourceDocument(
                    id=source_id,
                    original_path="source.pdf",
                    file_name="source.pdf",
                    source_type="pdf",
                    page_count=3,
                    char_count=sum(chunk.char_count for chunk in chunks),
                    extraction_method="pypdf",
                    text_quality="readable",
                    full_text_available=True,
                    indexed=True,
                    index_path=str(index_path),
                    index_manifest_path=str(store.source_dir(source_id) / "index_manifest.json"),
                ),
                pages=[
                    SourcePage(
                        source_id=source_id,
                        page_number=1,
                        text=chunks[0].text,
                        char_count=chunks[0].char_count,
                        extraction_method="pypdf",
                    )
                ],
                chunks=chunks,
                source_card=SourceCard(
                    source_id=source_id,
                    title="Urban Heat",
                    source_type="pdf",
                    page_count=3,
                    extraction_method="pypdf",
                    brief_summary="Urban heat and adaptation.",
                ),
                indexed=True,
                full_text_available=True,
                index_manifest=manifest,
            )
        )
        topic = CandidateTopic(
            id="topic_001",
            title="Urban heat and housing",
            research_question="How does heat affect housing inequality?",
            tentative_thesis_direction="Heat adaptation should include housing policy.",
            rationale="Source has chunks on renters and adaptation.",
            source_leads=[
                TopicSourceLead(
                    source_id=source_id,
                    chunk_ids=["src1-chunk-0001"],
                    suggested_search_queries=["cooling centers adaptation"],
                )
            ],
        )

        evidence = TopicEvidenceRetriever(store).retrieve_for_topic(topic, index_manifests=[manifest])

    assert evidence.topic_id == "topic_001"
    assert [chunk.chunk_id for chunk in evidence.chunks] == ["src1-chunk-0001", "src1-chunk-0002"]
    assert evidence.chunks[0].retrieval_method == "manifest_chunk_id"
    assert evidence.chunks[1].retrieval_method.startswith("fts:")
