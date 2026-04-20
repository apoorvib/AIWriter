from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.topic_ideation.schema import (
    CandidateTopic,
    RejectedTopic,
    SelectedTopic,
    TopicIdeationRound,
    TopicSourceLead,
)


class TopicRoundStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_round(self, round_: TopicIdeationRound) -> None:
        dir_ = self._job_dir(round_.job_id)
        dir_.mkdir(parents=True, exist_ok=True)
        path = dir_ / f"round_{round_.round_number:03d}.json"
        if path.exists():
            raise FileExistsError(f"topic round already exists: {path}")
        _write_json(path, asdict(round_))

    def load_round(self, job_id: str, round_number: int) -> TopicIdeationRound:
        path = self._job_dir(job_id) / f"round_{round_number:03d}.json"
        if not path.exists():
            raise KeyError(f"{job_id} round {round_number}")
        return _round_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def list_rounds(self, job_id: str) -> list[TopicIdeationRound]:
        dir_ = self._job_dir(job_id)
        if not dir_.exists():
            return []
        return [
            _round_from_payload(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(dir_.glob("round_*.json"))
        ]

    def save_selected_topic(self, selected: SelectedTopic) -> None:
        dir_ = self._job_dir(selected.job_id)
        dir_.mkdir(parents=True, exist_ok=True)
        _write_json(dir_ / "selected_topic.json", asdict(selected))

    def load_selected_topic(self, job_id: str) -> SelectedTopic:
        path = self._job_dir(job_id) / "selected_topic.json"
        if not path.exists():
            raise KeyError(f"selected topic for {job_id}")
        return _selected_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def save_rejected_topic(self, rejected: RejectedTopic) -> None:
        dir_ = self._job_dir(rejected.job_id) / "rejected_topics"
        dir_.mkdir(parents=True, exist_ok=True)
        path = dir_ / f"{_safe_file_part(rejected.round_id)}__{_safe_file_part(rejected.topic_id)}.json"
        if path.exists():
            raise FileExistsError(f"topic rejection already exists: {path}")
        _write_json(path, asdict(rejected))

    def list_rejected_topics(self, job_id: str) -> list[RejectedTopic]:
        dir_ = self._job_dir(job_id) / "rejected_topics"
        if not dir_.exists():
            return []
        return [
            RejectedTopic(**json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(dir_.glob("*.json"))
        ]

    def _job_dir(self, job_id: str) -> Path:
        return self.root / job_id


def _round_from_payload(payload: dict) -> TopicIdeationRound:
    payload = dict(payload)
    payload["candidates"] = [_candidate_from_payload(item) for item in payload.get("candidates", [])]
    return TopicIdeationRound(**payload)


def _selected_from_payload(payload: dict) -> SelectedTopic:
    payload = dict(payload)
    payload["source_leads"] = [_source_lead_from_payload(item) for item in payload.get("source_leads", [])]
    return SelectedTopic(**payload)


def _candidate_from_payload(payload: dict) -> CandidateTopic:
    payload = dict(payload)
    payload["source_leads"] = [_source_lead_from_payload(item) for item in payload.get("source_leads", [])]
    return CandidateTopic(**payload)


def _source_lead_from_payload(payload: dict) -> TopicSourceLead:
    return TopicSourceLead(**payload)


def _safe_file_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


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
