from __future__ import annotations

import json
from typing import Any

from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.validation.schema import DeterministicCheckResult
from essay_writer.writing_style.prompts import build_writing_style_prompt_block
from essay_writer.writing_style.schema import WritingStylePayload


TONE_ALIGNMENT_SYSTEM_PROMPT = """You compare an essay draft against the user's real writing samples.

The writing samples are style exemplars only. They are not evidence, not source material, and not content to copy.

Your job:
- judge whether the draft sounds like the user
- identify which habits match and which do not
- identify where generic anti-AI heuristics conflict with the user's authentic voice
- prefer the user's authentic voice when a conflict is real
- produce revision targets only for tone and style alignment, never for factual content

Rules:
- do not ask for more evidence
- do not evaluate citations or source grounding
- do not recommend copying facts, examples, or citations from the samples
- if a pattern appears consistently in the user's own samples, treat it as authentic voice rather than an automatic AI tell
- only mark requires_revision true when the style mismatch is material enough to justify another prose pass
"""


TONE_ALIGNMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "overall_alignment",
        "requires_revision",
        "matched_habits",
        "mismatched_habits",
        "preserve_points",
        "revision_targets",
        "anti_ai_conflicts",
    ],
    "properties": {
        "overall_alignment": {"type": "number"},
        "requires_revision": {"type": "boolean"},
        "matched_habits": {"type": "array", "items": {"type": "string"}},
        "mismatched_habits": {"type": "array", "items": {"type": "string"}},
        "preserve_points": {"type": "array", "items": {"type": "string"}},
        "revision_targets": {"type": "array", "items": {"type": "string"}},
        "anti_ai_conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["issue_type", "anti_ai_signal", "tone_signal", "resolution", "rationale"],
                "properties": {
                    "issue_type": {"type": "string"},
                    "anti_ai_signal": {"type": "string"},
                    "tone_signal": {"type": "string"},
                    "resolution": {"type": "string"},
                    "rationale": {"type": "string"},
                },
            },
        },
    },
}


def build_tone_alignment_user_message(
    *,
    draft_text: str,
    task_spec: TaskSpecification,
    det: DeterministicCheckResult,
    writing_style_payload: WritingStylePayload,
) -> str:
    context = {
        "task_spec": {
            "essay_type": task_spec.essay_type,
            "academic_level": task_spec.academic_level,
            "citation_style": task_spec.citation_style,
            "professor_constraints": task_spec.professor_constraints,
        },
        "anti_ai_signals": {
            "em_dash_count": det.em_dash_count,
            "en_dash_count": det.en_dash_count,
            "decorative_hyphen_pause_count": det.decorative_hyphen_pause_count,
            "colon_explanation_pattern_count": det.colon_explanation_pattern_count,
            "tier1_vocab_hits": [{"word": item.word, "count": item.count} for item in det.tier1_vocab_hits],
            "bad_conclusion_opener": det.bad_conclusion_opener,
            "participial_phrase_rate_per_300_words": round(det.participial_phrase_rate, 2),
            "contrastive_negation_count": det.contrastive_negation_count,
            "signposting_hits": det.signposting_hits,
            "triplet_contrastive_combo_count": det.triplet_contrastive_combo_count,
            "clustered_triplet_count": det.clustered_triplet_count,
            "paragraph_length_variance_warning": det.paragraph_length_variance_warning,
            "mechanical_burstiness_count": det.mechanical_burstiness_count,
            "concrete_engagement_present": det.concrete_engagement_present,
        },
    }
    return (
        f"{json.dumps(context, ensure_ascii=False)}\n\n"
        f"{build_writing_style_prompt_block(writing_style_payload)}\n\n"
        f"<essay_draft>\n{draft_text}\n</essay_draft>"
    )

