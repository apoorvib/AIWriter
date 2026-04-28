from __future__ import annotations

from pathlib import Path

from essay_writer.writing_style.ingestion import HumanWritingSampleIngestionService
from essay_writer.writing_style.schema import WritingStyleContent, WritingStylePayload
from essay_writer.writing_style.service import (
    WritingStyleContentService,
    build_sample_fingerprint,
    build_writing_style_payload,
)
from essay_writer.writing_style.storage import HumanWritingSampleStore, WritingStyleContentStore


SUPPORTED_WRITING_SAMPLE_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown", ".notes"}


def sync_existing_human_samples(
    sample_store: HumanWritingSampleStore,
    ingestion_service: HumanWritingSampleIngestionService,
    library_dir: str | Path,
) -> list[str]:
    root = Path(library_dir)
    if not root.exists():
        return []
    ingested_ids: list[str] = []
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_WRITING_SAMPLE_SUFFIXES:
            continue
        try:
            sample = ingestion_service.ingest(path)
        except Exception:
            continue
        ingested_ids.append(sample.id)
    return ingested_ids


def resolve_writing_style_payload(
    sample_ids: list[str],
    *,
    sample_store: HumanWritingSampleStore,
    content_store: WritingStyleContentStore,
    content_service: WritingStyleContentService,
) -> WritingStylePayload:
    if not sample_ids:
        raise ValueError("At least one writing style sample is required.")
    samples = sample_store.load_prompt_samples(sample_ids)
    fingerprint = build_sample_fingerprint(
        samples,
        generator_version=content_service.generator_version,
    )
    if content_store.exists_for_fingerprint(fingerprint):
        content = content_store.load_by_fingerprint(fingerprint)
    else:
        content = content_service.generate(samples)
        _save_content_if_missing(content_store, content)
    return build_writing_style_payload(content, samples)


def _save_content_if_missing(store: WritingStyleContentStore, content: WritingStyleContent) -> None:
    try:
        store.save(content)
    except FileExistsError:
        return
