from __future__ import annotations

import hashlib
import re
from pathlib import Path


ANTI_AI_SKILL_PATH = Path(__file__).resolve().parents[2] / "anti-ai-detection-SKILL.md"

# A canonical rule begins with a bold `**R<n> — <title>.**` marker. The em dash
# or a hyphen is accepted so the marker survives a dash-normalization pass.
_RULE_MARKER_RE = re.compile(r"^\*\*R(\d+)\s+[—–-]\s")
_RULE_TITLE_RE = re.compile(r"^\*\*R\d+\s+[—–-]\s+(.*?)\.\*\*")
_H2_RE = re.compile(r"^##\s+(.*)$")


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


class AntiAISkillManifestError(ValueError):
    """Raised when the skill file drifts from the canonical `R#` rule layout."""


def anti_ai_rule_manifest(path: Path | str | None = None) -> dict[str, object]:
    """Return a rule-level manifest for the anti-AI skill document.

    A *rule* is the span from a `**R<n> — ...**` marker to the next such marker,
    the next `##` section heading, or the next `---` horizontal rule, whichever
    comes first. Each rule carries its 1-indexed `rule_id`, exact text, and a
    hash of that text, so ``commit_anti_ai_audit`` can require one audit row per
    rule and verify the auditor had the exact rule bytes. Framing prose (Reality
    Check, Core Prose Standard, the How-to-use header, section headings) is bound
    by the whole-file ``skill_sha256`` and is not itself audited, which is what
    collapses the audit from ~138 blocks to ~31 rule rows plus one ``self_check``
    row.

    Raises ``AntiAISkillManifestError`` at load time if the file drifts from the
    canonical layout (non-contiguous rule numbers, a rule that lost its marker),
    so a bad edit fails loud instead of silently miscounting the audit surface.
    """

    skill_path = Path(path) if path is not None else ANTI_AI_SKILL_PATH
    raw = skill_path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    section_starts = [
        (index, match.group(1).strip())
        for index, line in enumerate(lines)
        if (match := _H2_RE.match(line))
    ]

    def section_of(index: int) -> str:
        current = "<preamble>"
        for start, name in section_starts:
            if start <= index:
                current = name
            else:
                break
        return current

    marker_indexes = [i for i, line in enumerate(lines) if _RULE_MARKER_RE.match(line)]
    if not marker_indexes:
        raise AntiAISkillManifestError(
            f"no `**R<n> —` rule markers found in {skill_path}; "
            "the per-rule audit requires the canonical rule-numbered skill file"
        )
    hr_indexes = {i for i, line in enumerate(lines) if line.strip() == "---"}
    boundaries = set(marker_indexes) | {i for i, _ in section_starts} | hr_indexes

    rules: list[dict[str, object]] = []
    covered_lines: set[int] = set()
    for start in marker_indexes:
        end = len(lines) - 1
        for candidate in range(start + 1, len(lines)):
            if candidate in boundaries:
                end = candidate - 1
                break
        text = "\n".join(lines[start : end + 1]).rstrip()
        ordinal = int(_RULE_MARKER_RE.match(lines[start]).group(1))
        title_match = _RULE_TITLE_RE.match(lines[start])
        rules.append(
            {
                "rule_id": f"R{ordinal}",
                "ordinal": ordinal,
                "title": title_match.group(1) if title_match else "",
                "section": section_of(start),
                "start_line": start + 1,
                "end_line": end + 1,
                "text": text,
                "rule_text_sha256": _sha256_text(text),
            }
        )
        covered_lines.update(range(start, end + 1))

    ordinals = [int(rule["ordinal"]) for rule in rules]
    if sorted(ordinals) != list(range(1, len(ordinals) + 1)):
        raise AntiAISkillManifestError(
            f"anti-AI rule ids must be contiguous R1..R{len(ordinals)}; got {sorted(ordinals)}"
        )

    # Every content line inside a rule-bearing section must belong to exactly one
    # rule span. An orphan means a rule lost its `**R#` marker (drift).
    rule_sections = {section_of(i) for i in marker_indexes}
    for index, line in enumerate(lines):
        if not line.strip() or _H2_RE.match(line) or line.strip() == "---":
            continue
        if section_of(index) in rule_sections and index not in covered_lines:
            raise AntiAISkillManifestError(
                f"line {index + 1} in rule section {section_of(index)!r} is not covered "
                f"by any rule span (a rule may have lost its `**R#` marker): {line[:60]!r}"
            )

    self_check: dict[str, object] | None = None
    for position, (start, name) in enumerate(section_starts):
        if name.lower().startswith("self-check"):
            end = (
                section_starts[position + 1][0] - 1
                if position + 1 < len(section_starts)
                else len(lines) - 1
            )
            text = "\n".join(lines[start : end + 1]).rstrip()
            self_check = {
                "rule_id": "self_check",
                "section": name,
                "start_line": start + 1,
                "end_line": end + 1,
                "text": text,
                "rule_text_sha256": _sha256_text(text),
            }
            break

    return {
        "path": str(skill_path),
        "sha256": _sha256_text(raw),
        "skill_line_count": len(lines),
        "rule_count": len(rules),
        "rules": rules,
        "self_check": self_check,
    }


ANTI_AI_SKILL_DOCUMENT = load_anti_ai_skill_document()
ANTI_AI_SKILL_SHA256 = str(anti_ai_skill_manifest()["sha256"])
