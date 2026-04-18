"""Versioned, immutable file-backed storage for DocumentOutlines."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from pdf_pipeline.outline.schema import DocumentOutline, OutlineEntry


class OutlineStore:
    """Simple versioned store keyed by source_id.

    Each outline is written to {root}/{source_id}/v{version}.json and is
    immutable — attempting to overwrite raises FileExistsError. load_latest
    picks the highest version number present.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, outline: DocumentOutline) -> None:
        dir_ = self._root / outline.source_id
        dir_.mkdir(parents=True, exist_ok=True)
        path = dir_ / f"v{outline.version}.json"
        if path.exists():
            raise FileExistsError(f"outline version already exists: {path}")
        payload = {
            "source_id": outline.source_id,
            "version": outline.version,
            "entries": [asdict(e) for e in outline.entries],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_latest(self, source_id: str) -> DocumentOutline:
        dir_ = self._root / source_id
        if not dir_.exists():
            raise KeyError(source_id)
        versions = sorted(
            (int(p.stem.lstrip("v")) for p in dir_.glob("v*.json")),
            reverse=True,
        )
        if not versions:
            raise KeyError(source_id)
        path = dir_ / f"v{versions[0]}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = [OutlineEntry(**e) for e in payload["entries"]]
        return DocumentOutline(
            source_id=payload["source_id"],
            version=payload["version"],
            entries=entries,
        )
