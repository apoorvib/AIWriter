from __future__ import annotations

from essay_writer.sources.index import SQLiteChunkIndex
from essay_writer.sources.schema import SourceChunk, SourceIndexManifest
from essay_writer.sources.storage import SourceStore
from essay_writer.topic_ideation.schema import (
    CandidateTopic,
    RetrievedTopicEvidence,
    SelectedTopic,
    TopicEvidenceChunk,
    TopicIdeationResult,
    TopicSourceLead,
)


class TopicEvidenceRetriever:
    def __init__(self, source_store: SourceStore) -> None:
        self._source_store = source_store

    def retrieve_for_result(
        self,
        result: TopicIdeationResult,
        *,
        index_manifests: list[SourceIndexManifest],
        per_query_limit: int = 3,
        max_chunks_per_topic: int = 12,
    ) -> list[RetrievedTopicEvidence]:
        return [
            self.retrieve_for_topic(
                topic,
                index_manifests=index_manifests,
                per_query_limit=per_query_limit,
                max_chunks=max_chunks_per_topic,
            )
            for topic in result.candidates
        ]

    def retrieve_for_topic(
        self,
        topic: CandidateTopic,
        *,
        index_manifests: list[SourceIndexManifest],
        per_query_limit: int = 3,
        max_chunks: int = 12,
    ) -> RetrievedTopicEvidence:
        if per_query_limit < 1:
            raise ValueError("per_query_limit must be >= 1")
        if max_chunks < 1:
            raise ValueError("max_chunks must be >= 1")

        return self._retrieve(
            topic_id=topic.id,
            source_leads=topic.source_leads,
            index_manifests=index_manifests,
            per_query_limit=per_query_limit,
            max_chunks=max_chunks,
        )

    def retrieve_for_selected_topic(
        self,
        selected_topic: SelectedTopic,
        *,
        index_manifests: list[SourceIndexManifest],
        per_query_limit: int = 3,
        max_chunks: int = 12,
    ) -> RetrievedTopicEvidence:
        if per_query_limit < 1:
            raise ValueError("per_query_limit must be >= 1")
        if max_chunks < 1:
            raise ValueError("max_chunks must be >= 1")
        return self._retrieve(
            topic_id=selected_topic.topic_id,
            source_leads=selected_topic.source_leads,
            index_manifests=index_manifests,
            per_query_limit=per_query_limit,
            max_chunks=max_chunks,
        )

    def _retrieve(
        self,
        *,
        topic_id: str,
        source_leads: list[TopicSourceLead],
        index_manifests: list[SourceIndexManifest],
        per_query_limit: int,
        max_chunks: int,
    ) -> RetrievedTopicEvidence:
        manifests = {manifest.source_id: manifest for manifest in index_manifests}
        chunks: list[TopicEvidenceChunk] = []
        seen: set[str] = set()
        warnings: list[str] = []

        for lead in source_leads:
            manifest = manifests.get(lead.source_id)
            if manifest is None:
                warnings.append(f"No index manifest available for source_id={lead.source_id}.")
                continue

            for chunk in self._load_explicit_chunks(lead.source_id, lead.chunk_ids, warnings):
                _append_chunk(
                    chunks,
                    seen,
                    TopicEvidenceChunk(
                        source_id=chunk.source_id,
                        chunk_id=chunk.id,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        text=chunk.text,
                        score=None,
                        retrieval_method="manifest_chunk_id",
                    ),
                    max_chunks,
                )
                if len(chunks) >= max_chunks:
                    return RetrievedTopicEvidence(topic_id=topic_id, chunks=chunks, warnings=warnings)

            for query in lead.suggested_source_search_queries:
                with SQLiteChunkIndex(manifest.index_path) as index:
                    results = index.search(query, limit=per_query_limit)
                for result in results:
                    _append_chunk(
                        chunks,
                        seen,
                        TopicEvidenceChunk(
                            source_id=result.source_id,
                            chunk_id=result.chunk_id,
                            page_start=result.page_start,
                            page_end=result.page_end,
                            text=result.text,
                            score=result.score,
                            retrieval_method=f"fts:{query}",
                        ),
                        max_chunks,
                    )
                    if len(chunks) >= max_chunks:
                        return RetrievedTopicEvidence(topic_id=topic_id, chunks=chunks, warnings=warnings)

        return RetrievedTopicEvidence(topic_id=topic_id, chunks=chunks, warnings=warnings)

    def _load_explicit_chunks(
        self,
        source_id: str,
        chunk_ids: list[str],
        warnings: list[str],
    ) -> list[SourceChunk]:
        if not chunk_ids:
            return []
        try:
            chunks = self._source_store.load_chunks(source_id)
        except (FileNotFoundError, KeyError):
            warnings.append(f"Could not load chunks for source_id={source_id}.")
            return []
        chunk_by_id = {chunk.id: chunk for chunk in chunks}
        found: list[SourceChunk] = []
        for chunk_id in chunk_ids:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                warnings.append(f"Chunk id not found: {chunk_id}.")
                continue
            found.append(chunk)
        return found


def _append_chunk(
    chunks: list[TopicEvidenceChunk],
    seen: set[str],
    chunk: TopicEvidenceChunk,
    max_chunks: int,
) -> None:
    if len(chunks) >= max_chunks or chunk.chunk_id in seen:
        return
    chunks.append(chunk)
    seen.add(chunk.chunk_id)
