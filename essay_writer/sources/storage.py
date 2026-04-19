from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from essay_writer.sources.schema import (
    SourceCard,
    SourceChunk,
    SourceDocument,
    SourceIndexEntry,
    SourceIndexManifest,
    SourceIngestionResult,
    SourcePage,
)


class SourceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def source_dir(self, source_id: str) -> Path:
        return self.root / source_id

    def save_result(self, result: SourceIngestionResult) -> SourceIngestionResult:
        dir_ = self.source_dir(result.source.id)
        dir_.mkdir(parents=True, exist_ok=True)
        source = SourceDocument(
            **{
                **asdict(result.source),
                "artifact_dir": str(dir_),
                "source_card_path": str(dir_ / "source_card.json"),
                "index_path": str(dir_ / "index.sqlite") if result.indexed else None,
                "index_manifest_path": str(dir_ / "index_manifest.json")
                if result.index_manifest is not None
                else None,
            }
        )
        saved = SourceIngestionResult(
            source=source,
            pages=result.pages,
            chunks=result.chunks,
            source_card=result.source_card,
            indexed=result.indexed,
            full_text_available=result.full_text_available,
            index_manifest=result.index_manifest,
            warnings=result.warnings,
        )
        _write_json(dir_ / "source.json", asdict(source))
        _write_jsonl(dir_ / "pages.jsonl", (asdict(page) for page in result.pages))
        _write_jsonl(dir_ / "chunks.jsonl", (asdict(chunk) for chunk in result.chunks))
        _write_text(dir_ / "full_text.txt", _full_text(result.pages))
        _write_json(dir_ / "source_card.json", asdict(result.source_card))
        if result.index_manifest is not None:
            _write_json(dir_ / "index_manifest.json", asdict(result.index_manifest))
        return saved

    def load_source(self, source_id: str) -> SourceDocument:
        payload = _read_json(self.source_dir(source_id) / "source.json")
        return SourceDocument(**payload)

    def load_pages(self, source_id: str) -> list[SourcePage]:
        return [SourcePage(**item) for item in _read_jsonl(self.source_dir(source_id) / "pages.jsonl")]

    def load_chunks(self, source_id: str) -> list[SourceChunk]:
        return [SourceChunk(**item) for item in _read_jsonl(self.source_dir(source_id) / "chunks.jsonl")]

    def load_source_card(self, source_id: str) -> SourceCard:
        payload = _read_json(self.source_dir(source_id) / "source_card.json")
        return SourceCard(**payload)

    def load_index_manifest(self, source_id: str) -> SourceIndexManifest:
        payload = _read_json(self.source_dir(source_id) / "index_manifest.json")
        entries = [SourceIndexEntry(**item) for item in payload.get("entries", [])]
        payload = dict(payload)
        payload["entries"] = entries
        return SourceIndexManifest(**payload)


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=True, indent=2))


def _write_jsonl(path: Path, payloads: Iterable[dict]) -> None:
    text = "".join(json.dumps(payload, ensure_ascii=True) + "\n" for payload in payloads)
    _write_text(path, text)


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


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _full_text(pages: list[SourcePage]) -> str:
    return "\n\n".join(page.text for page in pages if page.text)
