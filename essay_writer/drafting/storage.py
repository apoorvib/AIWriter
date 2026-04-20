from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.drafting.schema import EssayDraft, SectionSourceMap


class DraftStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, draft: EssayDraft) -> None:
        path = self._path(draft.job_id, draft.version)
        if path.exists():
            raise FileExistsError(f"draft version already exists: {path}")
        _write_json(path, asdict(draft))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def load_latest(self, job_id: str) -> EssayDraft:
        versions = self._versions(job_id)
        if not versions:
            raise KeyError(job_id)
        return self.load(job_id, versions[-1])

    def load(self, job_id: str, version: int) -> EssayDraft:
        path = self._path(job_id, version)
        if not path.exists():
            raise KeyError(f"{job_id} draft v{version}")
        return _draft_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def _path(self, job_id: str, version: int) -> Path:
        return self.root / job_id / f"draft_v{version:03d}.json"

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self.root / job_id
        if not dir_.exists():
            return []
        versions = []
        for path in dir_.glob("draft_v*.json"):
            suffix = path.stem.removeprefix("draft_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)


def _draft_from_payload(payload: dict) -> EssayDraft:
    payload = dict(payload)
    payload["section_source_map"] = [
        SectionSourceMap(**item) for item in payload.get("section_source_map", [])
    ]
    return EssayDraft(**payload)


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
