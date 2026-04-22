from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.validation.schema import (
    AssignmentFit,
    CitationIssue,
    CitationMetadataWarning,
    DeterministicCheckResult,
    LLMJudgmentResult,
    LengthCheck,
    ParagraphLengthProfile,
    RubricScore,
    SentenceRun,
    StyleIssue,
    UnsupportedClaim,
    ValidationDiagnostic,
    ValidationReport,
    VocabHit,
)


class ValidationStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, job_id: str, report: ValidationReport, *, version: int = 1) -> None:
        path = self._path(job_id, version)
        if path.exists():
            raise FileExistsError(f"validation report version already exists: {path}")
        _write_json(path, asdict(report))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def load_latest(self, job_id: str) -> ValidationReport:
        versions = self._versions(job_id)
        if not versions:
            raise KeyError(job_id)
        return self.load(job_id, versions[-1])

    def load(self, job_id: str, version: int) -> ValidationReport:
        path = self._path(job_id, version)
        if not path.exists():
            raise KeyError(f"{job_id} validation v{version}")
        return _report_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def _path(self, job_id: str, version: int) -> Path:
        return self.root / job_id / f"validation_report_v{version:03d}.json"

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self.root / job_id
        if not dir_.exists():
            return []
        versions = []
        for path in dir_.glob("validation_report_v*.json"):
            suffix = path.stem.removeprefix("validation_report_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)


def _report_from_payload(payload: dict) -> ValidationReport:
    payload = dict(payload)
    payload["deterministic"] = _deterministic_from_payload(payload["deterministic"])
    payload["llm_judgment"] = _judgment_from_payload(payload["llm_judgment"])
    payload["metadata_citation_warnings"] = [
        CitationMetadataWarning(**item) for item in payload.get("metadata_citation_warnings", [])
    ]
    return ValidationReport(**payload)


def _deterministic_from_payload(payload: dict) -> DeterministicCheckResult:
    payload = dict(payload)
    payload["tier1_vocab_hits"] = [VocabHit(**item) for item in payload.get("tier1_vocab_hits", [])]
    payload["consecutive_similar_sentence_runs"] = [
        SentenceRun(**item) for item in payload.get("consecutive_similar_sentence_runs", [])
    ]
    if payload.get("paragraph_length_profile") is not None:
        payload["paragraph_length_profile"] = ParagraphLengthProfile(**payload["paragraph_length_profile"])
    return DeterministicCheckResult(**payload)


def _judgment_from_payload(payload: dict) -> LLMJudgmentResult:
    payload = dict(payload)
    payload["unsupported_claims"] = [
        UnsupportedClaim(**item) for item in payload.get("unsupported_claims", [])
    ]
    payload["citation_issues"] = [
        CitationIssue(**item) for item in payload.get("citation_issues", [])
    ]
    payload["rubric_scores"] = [
        RubricScore(**item) for item in payload.get("rubric_scores", [])
    ]
    payload["assignment_fit"] = AssignmentFit(**payload["assignment_fit"])
    payload["length_check"] = LengthCheck(**payload["length_check"])
    payload["style_issues"] = [
        StyleIssue(**item) for item in payload.get("style_issues", [])
    ]
    payload["diagnostics"] = [
        ValidationDiagnostic(**item) for item in payload.get("diagnostics", [])
    ]
    payload.setdefault("revision_suggestions", [])
    return LLMJudgmentResult(**payload)


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
