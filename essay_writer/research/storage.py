from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.research.schema import (
    EvidenceGroup,
    EvidenceMap,
    FinalTopicResearchResult,
    ResearchNote,
    ResearchReport,
)


class ResearchStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_result(self, result: FinalTopicResearchResult, *, version: int = 1) -> None:
        if version < 1:
            raise ValueError("version must be >= 1")
        dir_ = self._job_dir(result.evidence_map.job_id)
        dir_.mkdir(parents=True, exist_ok=True)
        map_path = dir_ / f"evidence_map_v{version:03d}.json"
        report_path = dir_ / f"research_report_v{version:03d}.json"
        if map_path.exists() or report_path.exists():
            raise FileExistsError(f"research version already exists for job {result.evidence_map.job_id}: {version}")
        _write_json(map_path, asdict(result.evidence_map))
        _write_json(report_path, asdict(result.report))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def load_latest(self, job_id: str) -> FinalTopicResearchResult:
        versions = self._versions(job_id)
        if not versions:
            raise KeyError(job_id)
        return self.load(job_id, versions[-1])

    def load(self, job_id: str, version: int) -> FinalTopicResearchResult:
        dir_ = self._job_dir(job_id)
        map_path = dir_ / f"evidence_map_v{version:03d}.json"
        report_path = dir_ / f"research_report_v{version:03d}.json"
        if not map_path.exists() or not report_path.exists():
            raise KeyError(f"{job_id} research v{version}")
        evidence_map = _evidence_map_from_payload(json.loads(map_path.read_text(encoding="utf-8")))
        report = ResearchReport(**json.loads(report_path.read_text(encoding="utf-8")))
        return FinalTopicResearchResult(evidence_map=evidence_map, report=report)

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self._job_dir(job_id)
        if not dir_.exists():
            return []
        versions = []
        for path in dir_.glob("evidence_map_v*.json"):
            suffix = path.stem.removeprefix("evidence_map_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)

    def _job_dir(self, job_id: str) -> Path:
        return self.root / job_id


def _evidence_map_from_payload(payload: dict) -> EvidenceMap:
    payload = dict(payload)
    payload["notes"] = [ResearchNote(**item) for item in payload.get("notes", [])]
    payload["evidence_groups"] = [
        EvidenceGroup(**item) for item in payload.get("evidence_groups", [])
    ]
    return EvidenceMap(**payload)


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
