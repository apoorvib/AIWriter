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


def _block_is_structural(block_lines: list[str]) -> bool:
    """A block is structural (no direct prose guidance to apply to a draft)
    when every non-blank line is a Markdown heading or a fence/rule (``---``).

    Structural blocks get a light ``status: "context"`` row in the audit
    instead of full draft evidence, which is what keeps the per-block payload
    small.
    """

    non_blank = [line for line in block_lines if line.strip()]
    if not non_blank:
        return True
    return all(
        line.lstrip().startswith("#") or line.strip() == "---" for line in non_blank
    )


def anti_ai_block_manifest() -> dict[str, object]:
    """Return a block-level manifest for the anti-AI skill document.

    Blocks are blank-line-separated paragraphs of the raw file, in order,
    1-indexed and contiguous. Each block carries the exact line span it covers
    and a hash of its exact text, so ``commit_anti_ai_audit`` can require one
    audit row per block and verify the auditor had the exact block bytes. This
    replaces the per-line manifest for audit coverage; the ~191 blocks keep the
    audit payload small enough to submit inline.
    """

    raw = load_anti_ai_skill_document_raw()
    lines = raw.splitlines()
    blocks: list[dict[str, object]] = []
    current: list[str] = []
    current_start = 0
    block_index = 0

    def _flush(end_line: int) -> None:
        nonlocal current, current_start, block_index
        if not current:
            return
        block_index += 1
        text = "\n".join(current)
        blocks.append(
            {
                "block_index": block_index,
                "start_line": current_start,
                "end_line": end_line,
                "text": text,
                "block_text_sha256": _sha256_text(text),
                "is_structural": _block_is_structural(current),
            }
        )
        current = []
        current_start = 0

    for line_number, line in enumerate(lines, start=1):
        if line.strip() == "":
            _flush(line_number - 1)
            continue
        if not current:
            current_start = line_number
        current.append(line)
    _flush(len(lines))

    return {
        "path": str(ANTI_AI_SKILL_PATH),
        "sha256": _sha256_text(raw),
        "skill_line_count": len(lines),
        "block_count": len(blocks),
        "blocks": blocks,
    }


ANTI_AI_SKILL_DOCUMENT = load_anti_ai_skill_document()
ANTI_AI_SKILL_SHA256 = str(anti_ai_skill_manifest()["sha256"])
