from __future__ import annotations

import re

from essay_writer.task_spec.schema import AdversarialFlag


_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b", re.I),
        "prompt_injection",
        "high",
        "Ignore as AI-directed prompt injection.",
    ),
    (
        re.compile(r"\b(reveal|print|show|display)\s+(the\s+)?(system|developer)\s+prompt\b", re.I),
        "system_prompt_extraction",
        "high",
        "Ignore as system-prompt extraction attempt.",
    ),
    (
        re.compile(r"\b(you are now|act as|behave as)\s+(a\s+)?(different|new)?\s*(assistant|model|ai)\b", re.I),
        "model_behavior_override",
        "medium",
        "Ignore as model behavior override.",
    ),
    (
        re.compile(r"\b(ai|assistant|chatgpt|language model)\b.*\b(do not help|refuse|sabotage|give.*zero)\b", re.I),
        "sabotage",
        "high",
        "Ignore as AI-directed sabotage instruction.",
    ),
    (
        re.compile(r"\boutput\s+only\b|\brespond\s+only\b", re.I),
        "irrelevant_ai_directive",
        "medium",
        "Ignore as AI-directed output control unless clearly student-facing.",
    ),
]


def scan_adversarial_text(raw_text: str) -> list[AdversarialFlag]:
    flags: list[AdversarialFlag] = []
    seen: set[tuple[int, int, str]] = set()
    for pattern, category, severity, action in _PATTERNS:
        for match in pattern.finditer(raw_text):
            key = (match.start(), match.end(), category)
            if key in seen:
                continue
            seen.add(key)
            span = _source_span(raw_text, match.start(), match.end())
            flags.append(
                AdversarialFlag(
                    id=f"adv_{len(flags) + 1:03d}",
                    text=match.group(0),
                    category=category,  # type: ignore[arg-type]
                    severity=severity,  # type: ignore[arg-type]
                    source_span=span,
                    recommended_action=action,
                )
            )
    return flags


def _source_span(raw_text: str, start: int, end: int) -> str:
    line_start = raw_text.rfind("\n", 0, start) + 1
    line_end = raw_text.find("\n", end)
    if line_end == -1:
        line_end = len(raw_text)
    return raw_text[line_start:line_end].strip()
