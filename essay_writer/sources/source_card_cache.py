from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from essay_writer.sources.schema import SourceChunk


CACHE_VERSION = 1


class SourceCardCache:
    """Cross-store cache for source-card LLM payloads keyed by the canonical
    LLM input (excerpt texts + summary char limit + model). Identical source
    bytes produce the same cache key regardless of which SourceStore ingested
    them or which source_id was assigned, so re-ingesting the same document
    in a fresh job skips the summary LLM call."""

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_key(
        *,
        excerpts: list[SourceChunk],
        summary_char_limit: int,
        model: str | None,
    ) -> str:
        canonical = json.dumps(
            {
                "v": CACHE_VERSION,
                "excerpts": [chunk.text for chunk in excerpts],
                "summary_char_limit": summary_char_limit,
                "model": model or "",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, payload: dict[str, Any]) -> None:
        path = self._path(key)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{key}.",
            suffix=".tmp",
            dir=str(self.cache_dir),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"
