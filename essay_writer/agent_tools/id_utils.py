from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone


def safe_slug(
    value: object,
    *,
    fallback: str = "item",
    max_length: int | None = 80,
) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-._")
    if max_length is not None:
        slug = slug[:max_length].strip("-._")
    return slug or fallback


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def content_hash(payload: object) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def short_hash(payload: object, *, chars: int = 12, length: int | None = None) -> str:
    size = chars if length is None else length
    return content_hash(payload).split(":", 1)[1][:size]


def timestamp_id(prefix: str, *parts: object) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffixes = [safe_slug(part, max_length=40) for part in parts if part is not None]
    if suffixes:
        return "_".join([safe_slug(prefix, max_length=24), *suffixes, stamp])
    return f"{safe_slug(prefix, max_length=24)}_{stamp}"
