from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.deps import (
    DATA_DIR,
    get_writing_style_ingestion_service,
    get_writing_style_sample_store,
)
from backend.schemas import WritingSampleResponse
from backend.writing_style_support import SUPPORTED_WRITING_SAMPLE_SUFFIXES, sync_existing_human_samples

router = APIRouter(prefix="/writing-style", tags=["writing-style"])


def _suffix_for_upload(file: UploadFile) -> str:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_WRITING_SAMPLE_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_WRITING_SAMPLE_SUFFIXES))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Supported: {supported}.")
    return suffix


@router.get("/samples", response_model=list[WritingSampleResponse])
def list_writing_samples():
    store = get_writing_style_sample_store()
    ingestion = get_writing_style_ingestion_service()
    sync_existing_human_samples(store, ingestion, DATA_DIR / "human_samples")
    return [_sample_response(sample) for sample in store.list_samples()]


@router.post("/samples/upload", response_model=WritingSampleResponse)
async def upload_writing_sample(file: UploadFile = File(...)):
    suffix = _suffix_for_upload(file)
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        sample = get_writing_style_ingestion_service().ingest(tmp_path, title=Path(file.filename or "").stem)
    finally:
        tmp_path.unlink(missing_ok=True)
    return _sample_response(sample)


def _sample_response(sample) -> WritingSampleResponse:
    return WritingSampleResponse(
        sample_id=sample.id,
        title=sample.title,
        source_filename=sample.source_filename,
        source_type=sample.source_type,
        page_count=sample.page_count,
        word_count=sample.word_count,
        warnings=sample.warnings,
    )
