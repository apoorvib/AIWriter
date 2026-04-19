from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.task_spec.schema import AdversarialFlag, ChecklistItem, TaskSpecification


class TaskSpecStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, task_spec: TaskSpecification) -> None:
        dir_ = self._root / task_spec.id
        dir_.mkdir(parents=True, exist_ok=True)
        path = dir_ / f"v{task_spec.version}.json"
        payload = asdict(task_spec)
        serialized = json.dumps(payload, ensure_ascii=True, indent=2)

        fd, tmp_name = tempfile.mkstemp(prefix=f".v{task_spec.version}.", suffix=".tmp", dir=str(dir_))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
            try:
                os.link(tmp_path, path)
            except FileExistsError:
                raise FileExistsError(f"task spec version already exists: {path}")
        finally:
            tmp_path.unlink(missing_ok=True)

    def load_latest(self, task_id: str) -> TaskSpecification:
        dir_ = self._root / task_id
        if not dir_.exists():
            raise KeyError(task_id)
        versions = sorted(
            (int(path.stem.removeprefix("v")) for path in dir_.glob("v*.json")),
            reverse=True,
        )
        if not versions:
            raise KeyError(task_id)
        return self.load(task_id, versions[0])

    def load(self, task_id: str, version: int) -> TaskSpecification:
        path = self._root / task_id / f"v{version}.json"
        if not path.exists():
            raise KeyError(f"{task_id} v{version}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _task_spec_from_payload(payload)


def _task_spec_from_payload(payload: dict) -> TaskSpecification:
    checklist = [ChecklistItem(**item) for item in payload.get("extracted_checklist", [])]
    adversarial = [AdversarialFlag(**item) for item in payload.get("adversarial_flags", [])]
    payload = dict(payload)
    payload["extracted_checklist"] = checklist
    payload["adversarial_flags"] = adversarial
    return TaskSpecification(**payload)
