from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.outlining.schema import OutlineSection, ThesisOutline


class ThesisOutlineStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, outline: ThesisOutline) -> None:
        path = self._path(outline.job_id, outline.version)
        if path.exists():
            raise FileExistsError(f"thesis outline version already exists: {path}")
        _write_json(path, asdict(outline))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def load_latest(self, job_id: str) -> ThesisOutline:
        versions = self._versions(job_id)
        if not versions:
            raise KeyError(job_id)
        return self.load(job_id, versions[-1])

    def load(self, job_id: str, version: int) -> ThesisOutline:
        path = self._path(job_id, version)
        if not path.exists():
            raise KeyError(f"{job_id} thesis outline v{version}")
        return _outline_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def _path(self, job_id: str, version: int) -> Path:
        return self.root / job_id / f"thesis_outline_v{version:03d}.json"

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self.root / job_id
        if not dir_.exists():
            return []
        versions = []
        for path in dir_.glob("thesis_outline_v*.json"):
            suffix = path.stem.removeprefix("thesis_outline_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)


def _outline_from_payload(payload: dict) -> ThesisOutline:
    payload = dict(payload)
    payload["sections"] = [OutlineSection(**item) for item in payload.get("sections", [])]
    return ThesisOutline(**payload)


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
