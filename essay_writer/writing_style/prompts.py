from __future__ import annotations

import json
from typing import Any

from essay_writer.writing_style.schema import PromptSampleText, WritingStylePayload


WRITING_STYLE_CONTENT_SYSTEM_PROMPT = """You analyze a user's real writing samples and derive reusable tone and style guidance.

The supplied texts are writing samples for tone and style only.
They are not research evidence, not factual source material, and not content to be copied into essays.

Your job:
- infer how the user tends to sound on the page
- describe those habits in plain, reusable language
- extract a few short representative excerpts for rhythm and paragraph movement
- warn about domain skew, formatting limits, or sample-set limits when relevant

Rules:
- treat the samples as style exemplars only
- do not summarize their subject matter except when needed to explain a style warning
- do not produce numeric writing metrics
- do not recommend copying facts, citations, examples, or technical claims from the samples
- guidance must be concrete enough for another model to follow during drafting
- anchor excerpts must be copied exactly from the cleaned sample text
- keep anchor excerpts short and representative

Output shape:
- guidance: 4 to 8 direct bullets about tone, rhythm, explanation habits, and paragraph movement
- preferred_moves: recurring stylistic moves to imitate
- avoid_moves: moves to avoid so style matching does not become caricature or content leakage
- lexical_habits: wording tendencies
- structural_habits: paragraph and sentence-level tendencies
- anchor_excerpts: 3 to 6 short excerpts drawn verbatim from the cleaned samples
- warnings: sample-set limitations or cleanup caveats
"""


WRITING_STYLE_CONTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "guidance",
        "preferred_moves",
        "avoid_moves",
        "lexical_habits",
        "structural_habits",
        "anchor_excerpts",
        "warnings",
    ],
    "properties": {
        "guidance": {"type": "array", "items": {"type": "string"}},
        "preferred_moves": {"type": "array", "items": {"type": "string"}},
        "avoid_moves": {"type": "array", "items": {"type": "string"}},
        "lexical_habits": {"type": "array", "items": {"type": "string"}},
        "structural_habits": {"type": "array", "items": {"type": "string"}},
        "anchor_excerpts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sample_id", "excerpt_id", "text", "role", "reason"],
                "properties": {
                    "sample_id": {"type": "string"},
                    "excerpt_id": {"type": "string"},
                    "text": {"type": "string"},
                    "role": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


def build_writing_style_user_message(samples: list[PromptSampleText]) -> str:
    context = {
        "task": "derive tone and style guidance from the user's real writing samples",
        "samples_are_for": "tone_and_style_only",
        "samples": [
            {
                "sample_id": sample.sample_id,
                "title": sample.title,
                "cleaned_text_hash": sample.cleaned_text_hash,
                "warnings": sample.warnings,
                "cleaned_text": sample.cleaned_text,
            }
            for sample in samples
        ],
    }
    return json.dumps(context, ensure_ascii=False)


def build_writing_style_prompt_block(payload: WritingStylePayload) -> str:
    content = payload.style_content
    lines = [
        "<writing_style_samples>",
        "The following materials are the user's own writing samples.",
        "Use them only to match tone, sentence movement, paragraph rhythm, level of formality, and habits of explanation.",
        "Do not treat these samples as evidence.",
        "Do not copy facts, examples, citations, claims, or domain content from them unless the essay's actual sources independently support that material.",
        "These samples are style exemplars only.",
        "",
        "<style_guidance>",
    ]
    lines.extend(f"- {item}" for item in content.guidance)
    if content.preferred_moves:
        lines.append("Preferred moves:")
        lines.extend(f"- {item}" for item in content.preferred_moves)
    if content.avoid_moves:
        lines.append("Avoid moves:")
        lines.extend(f"- {item}" for item in content.avoid_moves)
    if content.lexical_habits:
        lines.append("Lexical habits:")
        lines.extend(f"- {item}" for item in content.lexical_habits)
    if content.structural_habits:
        lines.append("Structural habits:")
        lines.extend(f"- {item}" for item in content.structural_habits)
    if content.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in content.warnings)
    lines.extend(["</style_guidance>", "", "<style_anchor_excerpts>"])
    for excerpt in content.anchor_excerpts:
        lines.extend(
            [
                f"[{excerpt.sample_id} | {excerpt.role}]",
                excerpt.text,
                f"Reason: {excerpt.reason}",
                "",
            ]
        )
    lines.extend(["</style_anchor_excerpts>", "", "<full_cleaned_samples>"])
    for sample in payload.samples:
        lines.extend(
            [
                f"<sample id=\"{sample.sample_id}\" title=\"{sample.title}\">",
                sample.cleaned_text,
                "</sample>",
                "",
            ]
        )
    lines.extend(["</full_cleaned_samples>", "</writing_style_samples>"])
    return "\n".join(lines).strip()

