from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

from backend.deps import get_ingestion_service
from backend.schemas import AssignmentExtractResponse, SourceUploadResponse
from pdf_pipeline.document_reader import DocumentReader

router = APIRouter(prefix="/sources", tags=["sources"])

SUPPORTED_SOURCE_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown", ".notes"}
SUPPORTED_ASSIGNMENT_SUFFIXES = SUPPORTED_SOURCE_SUFFIXES


def _suffix_for_upload(file: UploadFile, allowed: set[str]) -> str:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        supported = ", ".join(sorted(allowed))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Supported: {supported}.")
    return suffix


@router.post("/upload", response_model=SourceUploadResponse)
async def upload_source(file: UploadFile = File(...)):
    suffix = _suffix_for_upload(file, SUPPORTED_SOURCE_SUFFIXES)

    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        service = get_ingestion_service()
        result = service.ingest(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return SourceUploadResponse(
        source_id=result.source.id,
        title=result.source_card.title,
        source_type=result.source.source_type,
        page_count=result.source.page_count or 0,
        chunk_count=len(result.chunks),
        text_quality=result.source.text_quality,
        warnings=[*result.warnings, *result.source_card.warnings],
    )


@router.post("/assignment/extract", response_model=AssignmentExtractResponse)
async def extract_assignment(file: UploadFile = File(...)):
    suffix = _suffix_for_upload(file, SUPPORTED_ASSIGNMENT_SUFFIXES)

    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        result = DocumentReader().extract(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    text = "\n\n".join(page.text.strip() for page in result.pages if page.text.strip())
    if not text:
        raise HTTPException(status_code=422, detail="No readable assignment text was extracted.")

    methods = sorted({page.extraction_method for page in result.pages})
    return AssignmentExtractResponse(
        text=text,
        page_count=result.page_count,
        extraction_method="+".join(methods) if methods else "unknown",
    )
