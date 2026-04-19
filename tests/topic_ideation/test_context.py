from __future__ import annotations

import json

from essay_writer.sources.schema import SourceCard, SourceIndexEntry, SourceIndexManifest
from essay_writer.task_spec.schema import ChecklistItem, TaskSpecification
from essay_writer.topic_ideation.context import build_topic_ideation_context


def test_topic_ideation_context_includes_cards_and_complete_manifest_without_index_path() -> None:
    task_spec = TaskSpecification(
        id="task1",
        version=1,
        raw_text="Write an argumentative essay.",
        extracted_checklist=[
            ChecklistItem(
                id="req_001",
                text="Use two sources.",
                category="source",
                required=True,
                source_span="Use two sources.",
                confidence=0.9,
            )
        ],
    )
    card = SourceCard(
        source_id="src1",
        title="Climate Housing Report",
        source_type="pdf",
        page_count=10,
        extraction_method="pypdf",
        brief_summary="A report about climate adaptation and housing.",
        key_topics=["climate adaptation", "housing"],
    )
    manifest = SourceIndexManifest(
        source_id="src1",
        index_path="C:/private/source_store/src1/index.sqlite",
        total_chunks=2,
        total_chars=400,
        entries=[
            SourceIndexEntry(
                chunk_id="src1-chunk-0001",
                ordinal=1,
                page_start=1,
                page_end=2,
                char_count=200,
                heading="Introduction",
                preview="Introduces climate adaptation.",
            ),
            SourceIndexEntry(
                chunk_id="src1-chunk-0002",
                ordinal=2,
                page_start=3,
                page_end=4,
                char_count=200,
                heading="Housing Exposure",
                preview="Discusses housing exposure.",
            ),
        ],
    )

    context = build_topic_ideation_context(task_spec, source_cards=[card], index_manifests=[manifest])
    payload = json.loads(context)

    assert payload["task_specification"]["id"] == "task1"
    assert "Climate Housing Report" in payload["source_cards"][0]["context"]
    assert "src1-chunk-0001" in payload["source_index_manifests"][0]["context"]
    assert "src1-chunk-0002" in payload["source_index_manifests"][0]["context"]
    assert "C:/private" not in context
    assert payload["source_index_manifests"][0]["index_handle"] == "src1"
