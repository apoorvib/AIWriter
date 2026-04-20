from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

from essay_writer.jobs.schema import EssayJob, EssayJobErrorState, utc_now_iso


class EssayJobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._jobs_dir = self.root / "jobs"
        self._jobs_dir.mkdir(parents=True, exist_ok=True)

    def save(self, job: EssayJob) -> EssayJob:
        current = replace(job, updated_at=utc_now_iso())
        _write_json(self._path(current.id), asdict(current))
        return current

    def create(self, job: EssayJob) -> EssayJob:
        path = self._path(job.id)
        if path.exists():
            raise FileExistsError(f"essay job already exists: {job.id}")
        return self.save(job)

    def load(self, job_id: str) -> EssayJob:
        path = self._path(job_id)
        if not path.exists():
            raise KeyError(job_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _job_from_payload(payload)

    def _path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"


def _job_from_payload(payload: dict) -> EssayJob:
    payload = dict(payload)
    if payload.get("error_state") is not None:
        payload["error_state"] = EssayJobErrorState(**payload["error_state"])
    return EssayJob(**payload)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, indent=2))
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
