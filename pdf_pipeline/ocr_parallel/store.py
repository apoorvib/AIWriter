from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pdf_pipeline.models import DocumentExtractionResult
from pdf_pipeline.ocr_parallel.schema import (
    CalibrationProfile,
    OcrPageResult,
    OcrRunSummary,
    WorkerPlan,
)


class OcrArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def init_document(self, document_id: str, config: dict[str, Any], worker_plan: WorkerPlan) -> None:
        doc_dir = self._doc_dir(document_id)
        (doc_dir / "pages").mkdir(parents=True, exist_ok=True)
        (doc_dir / "merged").mkdir(parents=True, exist_ok=True)
        (doc_dir / "runs").mkdir(parents=True, exist_ok=True)
        payload = {
            "config": _json_ready(config),
            "worker_plan": _json_ready(asdict(worker_plan)),
        }
        self._write_json(doc_dir / "config.json", payload)

    def save_page_result(self, result: OcrPageResult) -> Path:
        path = self._page_path(result.document_id, result.page_number)
        self._write_json(path, _json_ready(asdict(result)))
        return path

    def load_page_result(self, document_id: str, page_number: int) -> OcrPageResult:
        payload = json.loads(self._page_path(document_id, page_number).read_text(encoding="utf-8"))
        return OcrPageResult(**payload)

    def try_load_successful_page_result(
        self, document_id: str, page_number: int
    ) -> OcrPageResult | None:
        path = self._page_path(document_id, page_number)
        if not path.exists():
            return None
        try:
            result = self.load_page_result(document_id, page_number)
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        if not result.succeeded:
            return None
        return result

    def save_run_summary(self, summary: OcrRunSummary) -> Path:
        path = self._doc_dir(summary.document_id) / "runs" / f"{summary.run_id}.json"
        self._write_json(path, _json_ready(asdict(summary)))
        return path

    def save_calibration_profile(self, profile: CalibrationProfile) -> Path:
        path = self._doc_dir(profile.document_id) / "calibration" / "latest.json"
        self._write_json(path, _json_ready(asdict(profile)))
        return path

    def save_merged_result(
        self,
        document_id: str,
        result: DocumentExtractionResult,
        version: int = 1,
    ) -> Path:
        path = self._doc_dir(document_id) / "merged" / f"v{version}.json"
        payload = {
            "source_path": result.source_path,
            "page_count": result.page_count,
            "pages": [asdict(page) for page in result.pages],
        }
        self._write_json(path, payload)
        return path

    def _doc_dir(self, document_id: str) -> Path:
        return self.root / document_id

    def _page_path(self, document_id: str, page_number: int) -> Path:
        return self._doc_dir(document_id) / "pages" / f"{page_number:06d}.json"

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2)
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)


def _json_ready(value):
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value
