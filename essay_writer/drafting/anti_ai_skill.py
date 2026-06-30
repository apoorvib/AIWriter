from __future__ import annotations

import hashlib
from pathlib import Path


ANTI_AI_SKILL_PATH = Path(__file__).resolve().parents[2] / "anti-ai-detection-SKILL.md"


def _sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def load_anti_ai_skill_document_raw() -> str:
    try:
        return ANTI_AI_SKILL_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Anti-AI skill document is missing: {ANTI_AI_SKILL_PATH}") from exc


def load_anti_ai_skill_document() -> str:
    return load_anti_ai_skill_document_raw().strip()


def draft_sha256(content: str) -> str:
    """Return the hash used to bind an anti-AI audit to exact draft text."""

    return _sha256_text(content)


def anti_ai_skill_manifest() -> dict[str, object]:
    """Return a line-level manifest for the repo anti-AI skill document."""

    raw = load_anti_ai_skill_document_raw()
    lines = raw.splitlines()
    return {
        "path": str(ANTI_AI_SKILL_PATH),
        "sha256": _sha256_text(raw),
        "line_count": len(lines),
        "lines": [
            {
                "line_number": index,
                "text": line,
                "sha256": _sha256_text(line),
            }
            for index, line in enumerate(lines, start=1)
        ],
    }


ANTI_AI_SKILL_DOCUMENT = load_anti_ai_skill_document()
ANTI_AI_SKILL_SHA256 = str(anti_ai_skill_manifest()["sha256"])
