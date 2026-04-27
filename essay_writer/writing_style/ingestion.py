from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pdf_pipeline.document_reader import DocumentReader
from pdf_pipeline.models import DocumentExtractionResult
from essay_writer.writing_style.normalizer import normalize_writing_sample_text
from essay_writer.writing_style.schema import HumanWritingSample
from essay_writer.writing_style.storage import HumanWritingSampleStore


class HumanWritingSampleIngestionService:
    def __init__(
        self,
        store: HumanWritingSampleStore,
        *,
        reader: DocumentReader | None = None,
        normalizer_version: str = "human-sample-normalizer-v1",
    ) -> None:
        self._store = store
        self._reader = reader or DocumentReader()
        self._normalizer_version = normalizer_version

    def ingest(
        self,
        sample_path: str | Path,
        *,
        title: str | None = None,
        sample_id: str | None = None,
    ) -> HumanWritingSample:
        path = Path(sample_path)
        if not path.exists():
            raise FileNotFoundError(f"human writing sample not found: {path}")
        extraction = self._reader.extract(path)
        extracted_text = _flatten_extraction(extraction).strip()
        normalized = normalize_writing_sample_text(extracted_text)
        chosen_title = title.strip() if title and title.strip() else path.stem
        digest = hashlib.sha1(normalized.text.encode("utf-8")).hexdigest()
        chosen_id = sample_id or _stable_sample_id(chosen_title, digest)
        if self._store.exists(chosen_id):
            return self._store.load(chosen_id)
        extraction_methods = sorted({page.extraction_method for page in extraction.pages if page.extraction_method})
        extraction_method = ",".join(extraction_methods) if extraction_methods else "unknown"
        return self._store.save(
            sample_id=chosen_id,
            title=chosen_title,
            source_path=path,
            source_type=path.suffix.lower().lstrip("."),
            extracted_text=extracted_text,
            cleaned_text=normalized.text,
            cleaned_text_hash=digest,
            page_count=extraction.page_count,
            extraction_method=extraction_method,
            word_count=normalized.word_count,
            warnings=normalized.warnings,
            normalizer_version=self._normalizer_version,
        )


def _flatten_extraction(result: DocumentExtractionResult) -> str:
    return "\n\n".join(page.text.strip() for page in result.pages if page.text.strip())


def _stable_sample_id(title: str, digest: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "sample"
    return f"sample-{slug[:24]}-{digest[:8]}"

