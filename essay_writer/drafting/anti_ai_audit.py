"""Bounded single-skill anti-AI audit stage.

This stage runs AFTER a draft has been committed and AFTER the style-revision pass
has assembled per-window outputs. Its only job is to audit the assembled draft
against the anti-AI writing skill and produce a structured `anti_ai_self_check`
report that gets attached to the draft.

The split exists because:

1. `prepare_draft` is doing too much: voice match, grounding, citations, schema
   shape, AND anti-AI patterns. Single-focus stages outperform multi-goal stages.

2. Windowed style revision cannot see whole-draft structural patterns (paragraph
   variance, first-sentence chain, argument advancement). The audit looks at the
   assembled draft.

3. The audit subagent gets ONLY the anti-AI skill in its system prompt. No
   grounding rules, no source-packet evidence, no outline. That focuses the
   model's attention on the one job that matters here.
"""
from __future__ import annotations

from typing import Any

from essay_writer.drafting.anti_ai_skill import ANTI_AI_SKILL_DOCUMENT
from essay_writer.drafting.prompts import ANTI_AI_SELF_CHECK_SCHEMA


_WHOLE_ESSAY_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "scope",
        "paragraph_count_reviewed",
        "method",
        "finding",
    ],
    "properties": {
        "scope": {"type": "string", "enum": ["whole_essay"]},
        "paragraph_count_reviewed": {"type": "integer", "minimum": 0},
        "method": {"type": "string"},
        "finding": {"type": "string"},
    },
}


# One audit row per blank-line block of anti-ai-detection-SKILL.md (~191 blocks)
# instead of one per line (~458). Block coverage keeps the audit payload small
# enough to submit inline while still forcing full, hash-bound coverage of the
# skill. `whole_essay_evidence` is optional here: it is required by the commit
# validator only for non-`context` rows, so the ~69 structural blocks stay
# light and only the ~122 guidance blocks carry a full whole-essay review.
ANTI_AI_BLOCK_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "block_index",
            "block_text_sha256",
            "status",
            "draft_evidence",
            "finding",
            "block_application",
        ],
        "properties": {
            "block_index": {"type": "integer", "minimum": 1},
            "block_text_sha256": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["passed", "failed", "blocked", "not_applicable", "context"],
            },
            "draft_evidence": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "reference", "explanation"],
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "paragraph_reference",
                                "draft_quote",
                                "deterministic_check",
                                "not_applicable",
                            ],
                        },
                        "reference": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                },
            },
            "finding": {"type": "string"},
            "block_application": {"type": "string"},
            "whole_essay_evidence": _WHOLE_ESSAY_EVIDENCE_SCHEMA,
        },
    },
}


ANTI_AI_AUDIT_SELF_CHECK_SCHEMA: dict[str, Any] = {
    **ANTI_AI_SELF_CHECK_SCHEMA,
    "required": [
        "skill_file",
        "skill_sha256",
        "skill_line_count",
        "draft_sha256",
        "block_audit",
        *ANTI_AI_SELF_CHECK_SCHEMA["required"],
        "unmet_requirements",
        "final_decision",
    ],
    "properties": {
        **ANTI_AI_SELF_CHECK_SCHEMA["properties"],
        "skill_file": {"type": "string"},
        "skill_sha256": {"type": "string"},
        "skill_line_count": {"type": "integer", "minimum": 1},
        "draft_sha256": {"type": "string"},
        "block_audit": ANTI_AI_BLOCK_AUDIT_SCHEMA,
        "unmet_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["block_index", "section", "status", "reason", "risk"],
                "properties": {
                    "block_index": {"type": "integer", "minimum": 1},
                    "section": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["failed", "blocked"],
                    },
                    "reason": {"type": "string"},
                    "risk": {"type": "string"},
                },
            },
        },
        "final_decision": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "hard_rules_pass",
                "soft_rules_pass",
                "safe_to_claim_detector_reduction",
                "reason",
            ],
            "properties": {
                "hard_rules_pass": {"type": "boolean"},
                "soft_rules_pass": {"type": "boolean"},
                "safe_to_claim_detector_reduction": {"type": "boolean"},
                "reason": {"type": "string"},
            },
        },
    },
}


ANTI_AI_AUDIT_SYSTEM_PROMPT = f"""You are an anti-AI prose auditor.

You receive a committed essay draft and the user's writing-style guidance (if any).
Your only job is to score the draft against the anti-AI writing skill and return
a structured audit. You do not rewrite, do not invent facts, and do not change the
draft. You produce the audit.

The audit is the contract. Empty arrays and zero counts will be treated as a
failed audit unless the deterministic data attached to the user message confirms
they are correct.

Apply the anti-AI writing skill below. It is the only rubric for this stage.

<anti_ai_detection_skill>
{ANTI_AI_SKILL_DOCUMENT}
</anti_ai_detection_skill>

ANTI-AI SELF-CHECK (this is what you return):

For each item in the 7-step self-check in the skill, populate the matching field
in `anti_ai_self_check`. The user message also contains:

- `block_manifest`: every blank-line-separated block (paragraph) of the
  repo-local anti-AI skill document, with a `block_index`, the exact block
  `text`, a `block_text_sha256`, and an `is_structural` hint. You MUST produce
  exactly one `block_audit` row for every block. Use `status: "context"` for
  structural blocks (headings, the `---` frontmatter/rules, and blocks that
  carry no prose requirement — `is_structural: true` is your hint). For every
  guidance block, apply that block's guidance to the WHOLE draft.
- `deterministic_findings`: counts the application already computed (em dashes,
  filler hits, paragraph counts). Use these as ground truth for the count-shaped
  fields, but list the actual offending phrases in the array fields.
- `whole_draft_context`: the first-sentence chain and paragraph length profile
  across the entire essay. Use these for `first_sentence_chain_summarizes_essay`,
  `paragraph_count`, and `paragraphs_under_50_words`.
- `style_guidance_checklist`: one bullet per writing-style guidance item the user
  wants graded. Produce one `style_guidance_grades` row per bullet.

If the draft fails one of the 7 steps, populate the relevant arrays so the
revision stage knows exactly what to fix. Be specific: paragraph numbers,
quoted phrases, named patterns.

Also bind the audit to the exact files you read:
- copy `skill_file`, `skill_sha256`, and `skill_line_count` from the user
  message into `anti_ai_self_check`.
- copy `draft_sha256` from the user message into `anti_ai_self_check`.
- every `block_audit.block_index` and `block_audit.block_text_sha256` must match
  the supplied `block_manifest`; missing, extra, or mismatched block rows cause
  commit rejection.
- every non-context `block_audit` row must include `draft_evidence` tied to the
  audited draft: a valid paragraph reference, an exact draft quote, or a named
  deterministic check. Do not use `not_applicable` for a prose rule that was
  actually checked against the draft.
- every non-context `block_audit` row must include `whole_essay_evidence` with
  `scope: "whole_essay"` and `paragraph_count_reviewed` equal to the actual
  audited draft paragraph count. This proves the block was checked against the
  entire essay, not only a convenient local excerpt. Structural `context` rows
  may omit `whole_essay_evidence`.
- every non-context `block_audit` row must include `block_application`: a
  block-specific explanation of how that exact skill block affected the audit
  decision.
- list every blocked or failed skill block in `unmet_requirements`, referencing
  its `block_index`.
- fill `final_decision` honestly. If voice calibration is missing, do not claim
  detector-risk reduction is safe.

Set `pass`:
- `pass: true` iff `paragraph_first_sentences` reads as a real argument arc
  (not a topic-sentence chain), `paragraphs_under_50_words > 0` for any draft
  over 1000 words, `filler_phrases_used`, `significance_inflation_phrases`,
  and `vague_attributions_used` are empty, and `concrete_source_handles` is
  non-empty. Otherwise `pass: false`.

A response that returns empty arrays for everything will be rejected.
"""


ANTI_AI_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pass", "anti_ai_self_check", "revision_targets"],
    "properties": {
        "pass": {"type": "boolean"},
        "anti_ai_self_check": ANTI_AI_AUDIT_SELF_CHECK_SCHEMA,
        # When `pass` is false, list the specific paragraphs (1-indexed) and a one-line
        # diagnosis each. The downstream revision stage uses these to scope its edits.
        "revision_targets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["paragraph", "issue", "action"],
                "properties": {
                    "paragraph": {"type": "integer", "minimum": 1},
                    "issue": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": [
                            "split_into_short_paragraph",
                            "remove_filler",
                            "remove_significance_inflation",
                            "name_specific_source",
                            "advance_argument",
                            "vary_opener",
                            "rewrite_closing",
                            "remove_signposting",
                            "other",
                        ],
                    },
                },
            },
        },
    },
}
