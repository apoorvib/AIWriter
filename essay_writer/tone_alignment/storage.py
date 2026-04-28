from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.tone_alignment.schema import ToneAlignmentConflict, ToneAlignmentReport


class ToneAlignmentStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, job_id: str, report: ToneAlignmentReport, *, version: int = 1) -> None:
        path = self._path(job_id, version)
        if path.exists():
            raise FileExistsError(f"tone alignment report version already exists: {path}")
        _write_json(path, asdict(report))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def load_latest(self, job_id: str) -> ToneAlignmentReport:
        versions = self._versions(job_id)
        if not versions:
            raise KeyError(job_id)
        return self.load(job_id, versions[-1])

    def load(self, job_id: str, version: int) -> ToneAlignmentReport:
        path = self._path(job_id, version)
        if not path.exists():
            raise KeyError(f"{job_id} tone alignment v{version}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["anti_ai_conflicts"] = [
            ToneAlignmentConflict(**item) for item in payload.get("anti_ai_conflicts", [])
        ]
        return ToneAlignmentReport(**payload)

    def _path(self, job_id: str, version: int) -> Path:
        return self.root / job_id / f"tone_alignment_report_v{version:03d}.json"

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self.root / job_id
        if not dir_.exists():
            return []
        versions = []
        for path in dir_.glob("tone_alignment_report_v*.json"):
            suffix = path.stem.removeprefix("tone_alignment_report_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)


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

