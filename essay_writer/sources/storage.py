from __future__ import annotations

import json
import os
import shutil
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
from essay_writer.sources.access_schema import SourceMap, SourceUnit


class SourceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def source_dir(self, source_id: str) -> Path:
        return self.root / source_id

    def save_result(self, result: SourceIngestionResult) -> SourceIngestionResult:
        dir_ = self.source_dir(result.source.id)
        dir_.mkdir(parents=True, exist_ok=True)
        original_path = _persist_original_source(result.source, dir_)
        source = _source_with_artifact_paths(
            result.source,
            dir_,
            original_path=original_path,
            indexed=result.indexed,
            has_index_manifest=result.index_manifest is not None,
            has_source_map=result.source_map is not None,
        )
        saved = SourceIngestionResult(
            source=source,
            pages=result.pages,
            chunks=result.chunks,
            source_card=result.source_card,
            indexed=result.indexed,
            full_text_available=result.full_text_available,
            index_manifest=result.index_manifest,
            source_map=result.source_map,
            warnings=result.warnings,
        )
        _write_json(dir_ / "source.json", asdict(source))
        _write_jsonl(dir_ / "pages.jsonl", (asdict(page) for page in result.pages))
        _write_jsonl(dir_ / "chunks.jsonl", (asdict(chunk) for chunk in result.chunks))
        _write_text(dir_ / "full_text.txt", _full_text(result.pages))
        _write_json(dir_ / "source_card.json", asdict(result.source_card))
        if result.index_manifest is not None:
            _write_json(dir_ / "index_manifest.json", asdict(result.index_manifest))
        if result.source_map is not None:
            _write_json(dir_ / "source_map.json", asdict(result.source_map))
            _write_jsonl(dir_ / "source_units.jsonl", (asdict(unit) for unit in result.source_map.units))
        return saved

    def save_text_artifacts(
        self,
        source: SourceDocument,
        pages: list[SourcePage],
        source_map: SourceMap,
    ) -> SourceDocument:
        dir_ = self.source_dir(source.id)
        dir_.mkdir(parents=True, exist_ok=True)
        saved_source = _source_with_artifact_paths(
            source,
            dir_,
            original_path=source.original_path,
            indexed=source.indexed,
            has_index_manifest=source.index_manifest_path is not None,
            has_source_map=True,
        )
        _write_json(dir_ / "source.json", asdict(saved_source))
        _write_jsonl(dir_ / "pages.jsonl", (asdict(page) for page in pages))
        _write_text(dir_ / "full_text.txt", _full_text(pages))
        _write_json(dir_ / "source_map.json", asdict(source_map))
        _write_jsonl(dir_ / "source_units.jsonl", (asdict(unit) for unit in source_map.units))
        return saved_source

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

    def is_ingested(self, source_id: str) -> bool:
        return (self.source_dir(source_id) / "source_card.json").exists()

    def load_result(self, source_id: str) -> SourceIngestionResult:
        dir_ = self.source_dir(source_id)
        source = self.load_source(source_id)
        pages = self.load_pages(source_id)
        chunks = self.load_chunks(source_id)
        source_card = self.load_source_card(source_id)
        index_manifest = self.load_index_manifest(source_id) if (dir_ / "index_manifest.json").exists() else None
        source_map = self.load_source_map(source_id) if (dir_ / "source_map.json").exists() else None
        return SourceIngestionResult(
            source=source,
            pages=pages,
            chunks=chunks,
            source_card=source_card,
            indexed=source.indexed,
            full_text_available=source.full_text_available,
            index_manifest=index_manifest,
            source_map=source_map,
            warnings=[],
        )

    def load_source_map(self, source_id: str) -> SourceMap:
        payload = _read_json(self.source_dir(source_id) / "source_map.json")
        payload = dict(payload)
        payload["units"] = [SourceUnit(**item) for item in payload.get("units", [])]
        return SourceMap(**payload)


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=True, indent=2))


def _persist_original_source(source: SourceDocument, dir_: Path) -> str:
    original = Path(source.original_path)
    if not original.exists() or not original.is_file():
        return source.original_path
    suffix = original.suffix.lower() or (f".{source.source_type}" if source.source_type else "")
    target = dir_ / f"original{suffix}"
    try:
        if original.resolve() != target.resolve():
            shutil.copy2(original, target)
    except FileNotFoundError:
        return source.original_path
    return str(target)


def _source_with_artifact_paths(
    source: SourceDocument,
    dir_: Path,
    *,
    original_path: str,
    indexed: bool,
    has_index_manifest: bool,
    has_source_map: bool,
) -> SourceDocument:
    return SourceDocument(
        **{
            **asdict(source),
            "original_path": original_path,
            "artifact_dir": str(dir_),
            "source_card_path": str(dir_ / "source_card.json"),
            "index_path": str(dir_ / "index.sqlite") if indexed else None,
            "index_manifest_path": str(dir_ / "index_manifest.json") if has_index_manifest else None,
            "source_map_path": str(dir_ / "source_map.json") if has_source_map else None,
        }
    )


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
