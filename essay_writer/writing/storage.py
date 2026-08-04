from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Generic, TypeVar

from essay_writer.agent_tools.json_io import read_json, write_json_atomic
from essay_writer.writing.schema import (
    WritingBrief, WritingContextItem, WritingDraft, WritingOutput, WritingPlan,
    WritingResearch, WritingReview, WritingRun, utc_now_iso,
)

T = TypeVar("T")


def _versions(directory: Path, prefix: str) -> list[int]:
    if not directory.exists():
        return []
    values: list[int] = []
    for path in directory.glob(f"{prefix}_v*.json"):
        suffix = path.stem.removeprefix(f"{prefix}_v")
        if suffix.isdigit():
            values.append(int(suffix))
    return sorted(values)


class WritingRunStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, run: WritingRun) -> WritingRun:
        path = self._path(run.writing_run_id)
        if path.exists():
            raise FileExistsError(f"writing run already exists: {run.writing_run_id}")
        write_json_atomic(path, asdict(run))
        return run

    def update(self, run: WritingRun) -> WritingRun:
        if not self._path(run.writing_run_id).exists():
            raise KeyError(run.writing_run_id)
        current = replace(run, updated_at=utc_now_iso())
        write_json_atomic(self._path(run.writing_run_id), asdict(current))
        return current

    def load(self, writing_run_id: str) -> WritingRun:
        path = self._path(writing_run_id)
        if not path.exists():
            raise KeyError(writing_run_id)
        return WritingRun.from_dict(read_json(path))

    def list(self) -> list[WritingRun]:
        runs = [self.load(path.parent.name) for path in self.root.glob("*/run.json")]
        return sorted(runs, key=lambda run: (run.created_at, run.writing_run_id), reverse=True)

    def _path(self, writing_run_id: str) -> Path:
        return self.root / writing_run_id / "run.json"


class RunVersionStore(Generic[T]):
    def __init__(self, root: Path, prefix: str, parser: Callable[[dict], T]) -> None:
        self.root, self.prefix, self.parser = root, prefix, parser
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, value: T) -> T:
        run_id, version = str(getattr(value, "writing_run_id")), int(getattr(value, "version"))
        path = self._path(run_id, version)
        if path.exists():
            raise FileExistsError(f"{self.prefix} version already exists: {path}")
        write_json_atomic(path, asdict(value))  # type: ignore[arg-type]
        return value

    def load(self, writing_run_id: str, version: int) -> T:
        path = self._path(writing_run_id, version)
        if not path.exists():
            raise KeyError(f"{writing_run_id} {self.prefix} v{version}")
        return self.parser(read_json(path))

    def load_latest(self, writing_run_id: str) -> T:
        versions = self.versions(writing_run_id)
        if not versions:
            raise KeyError(writing_run_id)
        return self.load(writing_run_id, versions[-1])

    def next_version(self, writing_run_id: str) -> int:
        versions = self.versions(writing_run_id)
        return versions[-1] + 1 if versions else 1

    def versions(self, writing_run_id: str) -> list[int]:
        return _versions(self.root / writing_run_id, self.prefix)

    def _path(self, writing_run_id: str, version: int) -> Path:
        return self.root / writing_run_id / f"{self.prefix}_v{version:03d}.json"


class DeliverableVersionStore(Generic[T]):
    def __init__(self, root: Path, prefix: str, parser: Callable[[dict], T]) -> None:
        self.root, self.prefix, self.parser = root, prefix, parser
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, value: T) -> T:
        run_id = str(getattr(value, "writing_run_id"))
        deliverable_id = str(getattr(value, "deliverable_id"))
        version = int(getattr(value, "version"))
        path = self._path(run_id, deliverable_id, version)
        if path.exists():
            raise FileExistsError(f"{self.prefix} version already exists: {path}")
        write_json_atomic(path, asdict(value))  # type: ignore[arg-type]
        return value

    def load(self, writing_run_id: str, deliverable_id: str, version: int) -> T:
        path = self._path(writing_run_id, deliverable_id, version)
        if not path.exists():
            raise KeyError(f"{writing_run_id} {deliverable_id} {self.prefix} v{version}")
        return self.parser(read_json(path))

    def load_latest(self, writing_run_id: str, deliverable_id: str) -> T:
        versions = self.versions(writing_run_id, deliverable_id)
        if not versions:
            raise KeyError(f"{writing_run_id} {deliverable_id}")
        return self.load(writing_run_id, deliverable_id, versions[-1])

    def next_version(self, writing_run_id: str, deliverable_id: str) -> int:
        versions = self.versions(writing_run_id, deliverable_id)
        return versions[-1] + 1 if versions else 1

    def versions(self, writing_run_id: str, deliverable_id: str) -> list[int]:
        return _versions(self.root / writing_run_id / deliverable_id, self.prefix)

    def _path(self, writing_run_id: str, deliverable_id: str, version: int) -> Path:
        return self.root / writing_run_id / deliverable_id / f"{self.prefix}_v{version:03d}.json"


class WritingContextStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, item: WritingContextItem, content: str) -> WritingContextItem:
        directory = self.root / item.writing_run_id / item.context_id
        path = directory / "metadata.json"
        if path.exists():
            existing = self.load(item.writing_run_id, item.context_id)
            if existing == item and self.load_content(existing) == content:
                return existing
            raise FileExistsError(f"writing context already exists: {item.context_id}")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "content.txt").write_text(content, encoding="utf-8")
        write_json_atomic(path, asdict(item))
        return item

    def load(self, writing_run_id: str, context_id: str) -> WritingContextItem:
        path = self.root / writing_run_id / context_id / "metadata.json"
        if not path.exists():
            raise KeyError(context_id)
        return WritingContextItem.from_dict(read_json(path))

    def load_content(self, item: WritingContextItem) -> str:
        return Path(item.content_path).read_text(encoding="utf-8")

    def list(self, writing_run_id: str) -> list[WritingContextItem]:
        directory = self.root / writing_run_id
        if not directory.exists():
            return []
        return [WritingContextItem.from_dict(read_json(path)) for path in sorted(directory.glob("*/metadata.json"))]


class WritingOutputStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, output: WritingOutput) -> WritingOutput:
        path = self._path(output.writing_run_id)
        if path.exists():
            existing = WritingOutput.from_dict(read_json(path))
            if existing == output:
                return existing
            raise FileExistsError(f"writing output {output.output_id} has a different payload")
        write_json_atomic(path, asdict(output))
        return output

    def load(self, writing_run_id: str) -> WritingOutput:
        path = self._path(writing_run_id)
        if not path.exists():
            raise KeyError(writing_run_id)
        return WritingOutput.from_dict(read_json(path))

    def _path(self, writing_run_id: str) -> Path:
        return self.root / writing_run_id / "output.json"


@dataclass(frozen=True)
class WritingStores:
    root: Path
    runs: WritingRunStore
    briefs: RunVersionStore[WritingBrief]
    context: WritingContextStore
    research: RunVersionStore[WritingResearch]
    plans: DeliverableVersionStore[WritingPlan]
    drafts: DeliverableVersionStore[WritingDraft]
    reviews: DeliverableVersionStore[WritingReview]
    outputs: WritingOutputStore

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> "WritingStores":
        root = Path(data_dir) / "writing"
        root.mkdir(parents=True, exist_ok=True)
        return cls(
            root, WritingRunStore(root / "runs"),
            RunVersionStore(root / "briefs", "brief", WritingBrief.from_dict),
            WritingContextStore(root / "context"),
            RunVersionStore(root / "research", "research", WritingResearch.from_dict),
            DeliverableVersionStore(root / "plans", "plan", WritingPlan.from_dict),
            DeliverableVersionStore(root / "drafts", "draft", WritingDraft.from_dict),
            DeliverableVersionStore(root / "reviews", "review", WritingReview.from_dict),
            WritingOutputStore(root / "outputs"),
        )
