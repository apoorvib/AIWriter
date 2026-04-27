from __future__ import annotations

import re

from essay_writer.writing_style.schema import NormalizedWritingSampleText


_BLANK_LINES = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_LIST_PREFIX = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|#+\s+|>\s+)")
_MOJIBAKE_MARKERS = ("\u00e2", "\u00c3", "\ufffd", "\u00ef\u00bb\u00bf")


def normalize_writing_sample_text(raw_text: str) -> NormalizedWritingSampleText:
    warnings: list[str] = []
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    repaired = _maybe_fix_utf8_mojibake(text)
    if repaired != text:
        text = repaired
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\u00ad", "")
    blocks = [block for block in re.split(r"\n\s*\n", text) if block.strip()]
    normalized_blocks = [_normalize_block(block) for block in blocks]
    normalized = "\n\n".join(block for block in normalized_blocks if block).strip()
    normalized = _BLANK_LINES.sub("\n\n", normalized)
    if any(marker in normalized for marker in _MOJIBAKE_MARKERS):
        warnings.append("cleaned text may still contain encoding artifacts")
    return NormalizedWritingSampleText(
        text=normalized,
        char_count=len(normalized),
        word_count=_word_count(normalized),
        warnings=warnings,
    )


def _normalize_block(block: str) -> str:
    lines = [line.strip() for line in block.split("\n") if line.strip()]
    if not lines:
        return ""
    if len(lines) == 1 or _looks_structured(lines):
        return "\n".join(lines)
    current = lines[0]
    for next_line in lines[1:]:
        current = _join_wrapped_line(current, next_line)
    return current


def _looks_structured(lines: list[str]) -> bool:
    return any(
        _LIST_PREFIX.match(line)
        or line.startswith("```")
        or line.startswith("    ")
        for line in lines
    )


def _join_wrapped_line(current: str, next_line: str) -> str:
    if not current:
        return next_line
    if current.endswith("-"):
        left = current.rsplit(" ", 1)[-1][:-1]
        right_match = re.match(r"([A-Za-z0-9]+)", next_line)
        right = right_match.group(1) if right_match else ""
        if left.isalpha() and left.islower() and right.isalpha() and right.islower():
            return current[:-1] + next_line
        return current + next_line
    if current.endswith("/"):
        return current + next_line
    return _MULTI_SPACE.sub(" ", f"{current} {next_line}").strip()


def _maybe_fix_utf8_mojibake(text: str) -> str:
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text
    best = text
    for _ in range(2):
        repaired = _repair_mojibake_once(best)
        if repaired == best:
            break
        best = repaired
    return best


def _repair_mojibake_once(text: str) -> str:
    best = text
    best_score = _mojibake_score(text)
    for encoding in ("cp1252", "latin-1"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        score = _mojibake_score(candidate)
        if score < best_score:
            best = candidate
            best_score = score
    return best


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))
