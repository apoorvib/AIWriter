from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.research_planning.schema import ResearchPlan, SourceReadingPriority
from essay_writer.sources.access_schema import locator_from_payload


class ResearchPlanStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, plan: ResearchPlan) -> None:
        path = self._path(plan.job_id, plan.version)
        if path.exists():
            raise FileExistsError(f"research plan version already exists: {path}")
        _write_json(path, asdict(plan))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def load_latest(self, job_id: str) -> ResearchPlan:
        versions = self._versions(job_id)
        if not versions:
            raise KeyError(job_id)
        return self.load(job_id, versions[-1])

    def load(self, job_id: str, version: int) -> ResearchPlan:
        path = self._path(job_id, version)
        if not path.exists():
            raise KeyError(f"{job_id} research plan v{version}")
        return _plan_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def _path(self, job_id: str, version: int) -> Path:
        return self.root / job_id / f"research_plan_v{version:03d}.json"

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self.root / job_id
        if not dir_.exists():
            return []
        versions = []
        for path in dir_.glob("research_plan_v*.json"):
            suffix = path.stem.removeprefix("research_plan_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)


def _plan_from_payload(payload: dict) -> ResearchPlan:
    payload = dict(payload)
    payload["uploaded_source_priorities"] = [
        SourceReadingPriority(**item) for item in payload.get("uploaded_source_priorities", [])
    ]
    payload["source_requests"] = [locator_from_payload(item) for item in payload.get("source_requests", [])]
    return ResearchPlan(**payload)


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
