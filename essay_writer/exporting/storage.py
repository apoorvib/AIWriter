from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.exporting.schema import FinalEssayExport


class FinalExportStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, export: FinalEssayExport) -> None:
        dir_ = self.root / export.job_id
        dir_.mkdir(parents=True, exist_ok=True)
        json_path = dir_ / f"{export.id}.json"
        md_path = dir_ / f"{export.id}.md"
        if json_path.exists() or md_path.exists():
            raise FileExistsError(f"final export already exists: {export.id}")
        _write_text(md_path, export.content)
        _write_json(json_path, asdict(export))

    def load_latest(self, job_id: str) -> FinalEssayExport:
        paths = sorted((self.root / job_id).glob("final_export_*.json"))
        if not paths:
            raise KeyError(job_id)
        return self.load(job_id, paths[-1].stem)

    def load(self, job_id: str, export_id: str) -> FinalEssayExport:
        path = self.root / job_id / f"{export_id}.json"
        if not path.exists():
            raise KeyError(f"{job_id} {export_id}")
        return FinalEssayExport(**json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=True, indent=2))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
