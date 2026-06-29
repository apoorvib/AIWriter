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


ANTI_AI_LINE_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "line_number",
            "line_text_sha256",
            "requirement",
            "status",
            "evidence",
            "draft_evidence",
            "whole_essay_evidence",
            "line_application",
            "action_taken",
        ],
        "properties": {
            "line_number": {"type": "integer", "minimum": 1},
            "line_text_sha256": {"type": "string"},
            "requirement": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["passed", "failed", "blocked", "context"],
            },
            "evidence": {"type": "string"},
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
            "whole_essay_evidence": {
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
            },
            "line_application": {"type": "string"},
            "action_taken": {"type": "string"},
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
        "line_audit",
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
        "line_audit": ANTI_AI_LINE_AUDIT_SCHEMA,
        "unmet_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["line_number", "section", "status", "reason", "risk"],
                "properties": {
                    "line_number": {"type": "integer", "minimum": 1},
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

- `skill_line_manifest`: every line in the repo-local anti-AI skill document,
  with line numbers and SHA-256 hashes. You MUST produce one `line_audit` row
  for every line, including frontmatter, headings, bullets, blank lines, and
  examples. Use `status: "context"` for lines that are structural/contextual
  rather than direct requirements.
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
- every `line_audit.line_number` and `line_audit.line_text_sha256` must match
  the supplied `skill_line_manifest`; missing or mismatched line rows cause
  commit rejection.
- every non-context `line_audit` row must include `draft_evidence` tied to the
  audited draft: a valid paragraph reference, an exact draft quote, or a named
  deterministic check. Do not use `not_applicable` for a prose rule that was
  actually checked against the draft.
- every `line_audit` row must include `whole_essay_evidence` with
  `scope: "whole_essay"` and `paragraph_count_reviewed` equal to the actual
  audited draft paragraph count. This proves the line was checked against the
  entire essay, not only a convenient local excerpt.
- every `line_audit` row must include `line_application`: a line-specific
  explanation of how that exact skill-file line affected the audit decision.
- list every blocked or failed skill-line requirement in `unmet_requirements`.
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
