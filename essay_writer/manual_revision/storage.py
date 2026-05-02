from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.manual_revision.schema import ManualRevisionRequest, ManualRevisionRun
from essay_writer.tone_alignment.schema import ToneAlignmentConflict, ToneAlignmentReport
from essay_writer.validation.schema import (
    AssignmentFit,
    CitationIssue,
    CitationMetadataWarning,
    DeterministicCheckResult,
    LengthCheck,
    LLMJudgmentResult,
    ParagraphLengthProfile,
    RubricScore,
    SentenceRun,
    StyleIssue,
    UnsupportedClaim,
    ValidationDiagnostic,
    ValidationReport,
    VocabHit,
)


class ManualRevisionRequestStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, request: ManualRevisionRequest, *, version: int) -> None:
        path = self._path(request.job_id, version)
        if path.exists():
            raise FileExistsError(f"manual revision request version already exists: {path}")
        _write_json(path, asdict(request))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def list_versions(self, job_id: str) -> list[ManualRevisionRequest]:
        return [self.load(job_id, version) for version in self._versions(job_id)]

    def load(self, job_id: str, version: int) -> ManualRevisionRequest:
        path = self._path(job_id, version)
        if not path.exists():
            raise KeyError(f"{job_id} manual request v{version}")
        return ManualRevisionRequest(**json.loads(path.read_text(encoding="utf-8")))

    def find_by_id(self, job_id: str, request_id: str) -> ManualRevisionRequest:
        for request in self.list_versions(job_id):
            if request.id == request_id:
                return request
        raise KeyError(f"{job_id} {request_id}")

    def _path(self, job_id: str, version: int) -> Path:
        return self.root / job_id / f"request_v{version:03d}.json"

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self.root / job_id
        if not dir_.exists():
            return []
        versions: list[int] = []
        for path in dir_.glob("request_v*.json"):
            suffix = path.stem.removeprefix("request_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)


class ManualRevisionRunStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, run: ManualRevisionRun, *, version: int) -> None:
        path = self._path(run.job_id, version)
        if path.exists():
            raise FileExistsError(f"manual revision run version already exists: {path}")
        _write_json(path, asdict(run))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def list_versions(self, job_id: str) -> list[ManualRevisionRun]:
        return [self.load(job_id, version) for version in self._versions(job_id)]

    def load(self, job_id: str, version: int) -> ManualRevisionRun:
        path = self._path(job_id, version)
        if not path.exists():
            raise KeyError(f"{job_id} manual run v{version}")
        return _run_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def find_by_id(self, job_id: str, run_id: str) -> ManualRevisionRun:
        for run in self.list_versions(job_id):
            if run.id == run_id:
                return run
        raise KeyError(f"{job_id} {run_id}")

    def _path(self, job_id: str, version: int) -> Path:
        return self.root / job_id / f"run_v{version:03d}.json"

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self.root / job_id
        if not dir_.exists():
            return []
        versions: list[int] = []
        for path in dir_.glob("run_v*.json"):
            suffix = path.stem.removeprefix("run_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)


def _run_from_payload(payload: dict) -> ManualRevisionRun:
    payload = dict(payload)
    for key in [
        "pre_revision_validation",
        "post_revision_validation",
    ]:
        if payload.get(key) is not None:
            payload[key] = _validation_from_payload(payload[key])
    for key in [
        "pre_revision_tone_alignment",
        "post_revision_tone_alignment",
    ]:
        if payload.get(key) is not None:
            payload[key] = _tone_alignment_from_payload(payload[key])
    for key in [
        "pre_revision_anti_ai",
        "post_revision_anti_ai",
    ]:
        if payload.get(key) is not None:
            payload[key] = _deterministic_from_payload(payload[key])
    return ManualRevisionRun(**payload)


def _validation_from_payload(payload: dict) -> ValidationReport:
    payload = dict(payload)
    payload["deterministic"] = _deterministic_from_payload(payload["deterministic"])
    payload["llm_judgment"] = _judgment_from_payload(payload["llm_judgment"])
    payload["metadata_citation_warnings"] = [
        CitationMetadataWarning(**item)
        for item in payload.get("metadata_citation_warnings", [])
    ]
    return ValidationReport(**payload)


def _deterministic_from_payload(payload: dict) -> DeterministicCheckResult:
    payload = dict(payload)
    payload["tier1_vocab_hits"] = [VocabHit(**item) for item in payload.get("tier1_vocab_hits", [])]
    payload["consecutive_similar_sentence_runs"] = [
        SentenceRun(**item) for item in payload.get("consecutive_similar_sentence_runs", [])
    ]
    profile = payload.get("paragraph_length_profile")
    payload["paragraph_length_profile"] = ParagraphLengthProfile(**profile) if profile is not None else None
    return DeterministicCheckResult(**payload)


def _judgment_from_payload(payload: dict) -> LLMJudgmentResult:
    payload = dict(payload)
    payload["unsupported_claims"] = [UnsupportedClaim(**item) for item in payload.get("unsupported_claims", [])]
    payload["citation_issues"] = [CitationIssue(**item) for item in payload.get("citation_issues", [])]
    payload["rubric_scores"] = [RubricScore(**item) for item in payload.get("rubric_scores", [])]
    payload["assignment_fit"] = AssignmentFit(**payload["assignment_fit"])
    payload["length_check"] = LengthCheck(**payload["length_check"])
    payload["style_issues"] = [StyleIssue(**item) for item in payload.get("style_issues", [])]
    payload["diagnostics"] = [ValidationDiagnostic(**item) for item in payload.get("diagnostics", [])]
    return LLMJudgmentResult(**payload)


def _tone_alignment_from_payload(payload: dict) -> ToneAlignmentReport:
    payload = dict(payload)
    payload["anti_ai_conflicts"] = [ToneAlignmentConflict(**item) for item in payload.get("anti_ai_conflicts", [])]
    return ToneAlignmentReport(**payload)


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
