from __future__ import annotations

import re

from essay_writer.agent_tools.schemas import WorkProducer
from essay_writer.drafting.anti_ai_skill import (
    anti_ai_block_manifest,
    anti_ai_skill_manifest,
    draft_sha256,
)


class ExplodingLLMClient:
    def chat_json(self, *args, **kwargs):
        raise AssertionError("Agent Tool Mode must not call LLMClient.chat_json")


def main_agent() -> WorkProducer:
    return WorkProducer(type="main_agent", role="orchestrator", name=None)


def dispatched_subagent(
    facade,
    work_packet_id: str,
    role: str,
    *,
    model_tier: str = "frontier",
) -> WorkProducer:
    """Convenience helper for tests: dispatch a subagent and return a
    ``WorkProducer`` carrying the issued token, ready to pass to
    ``submit_work_result``. Used to satisfy mechanism (B)'s delegation
    gate without each test having to wire the token plumbing inline.
    """
    dispatch = facade.dispatch_subagent(
        work_packet_id=work_packet_id,
        role=role,
        model_tier=model_tier,
    )
    if not dispatch.ok:
        raise AssertionError(
            f"dispatch_subagent failed: {dispatch.error}"
        )
    return WorkProducer(
        type="subagent",
        role=role,
        name=f"{role}-test",
        subagent_token=str(dispatch.data["subagent_token"]),
    )


def anti_ai_block_rows(
    draft_text: str,
    *,
    omit_last_block: bool = False,
) -> list[dict[str, object]]:
    """Build one valid ``block_audit`` row per block of the skill file.

    Structural blocks get a light ``status="context"`` row; guidance blocks get
    a full row (draft quote evidence, whole-essay review, block-tied reasoning)
    that passes every ``commit_anti_ai_audit`` gate.
    """
    block_manifest = anti_ai_block_manifest()
    blocks = block_manifest["blocks"]
    if omit_last_block:
        blocks = blocks[:-1]
    draft_quote = draft_text.strip().splitlines()[0][:120] if draft_text.strip() else "n/a"
    paragraph_count_reviewed = len(
        [part for part in re.split(r"\n\s*\n", draft_text) if part.strip()]
    )
    rows: list[dict[str, object]] = []
    for block in blocks:
        block_index = int(block["block_index"])
        is_structural = bool(block["is_structural"])
        # Keep guidance rows lean (just over each validator threshold) so the
        # fixture reflects an economical real audit, not a padded worst case.
        row: dict[str, object] = {
            "block_index": block_index,
            "block_text_sha256": block["block_text_sha256"],
            "status": "context" if is_structural else "passed",
            "finding": (
                f"Block {block_index}: structural context."
                if is_structural
                else f"Block {block_index}: guidance met by draft."
            ),
            "block_application": (
                "" if is_structural else f"Block {block_index} applied to whole draft."
            ),
            "draft_evidence": [
                {
                    "kind": "not_applicable" if is_structural else "draft_quote",
                    "reference": (
                        f"block {block_index} context" if is_structural else draft_quote
                    ),
                    "explanation": (
                        "structural context line"
                        if is_structural
                        else f"block {block_index} vs draft sentence"
                    ),
                }
            ],
        }
        if not is_structural:
            row["whole_essay_evidence"] = {
                "scope": "whole_essay",
                "paragraph_count_reviewed": paragraph_count_reviewed,
                "method": f"reviewed all {paragraph_count_reviewed} paragraphs for block {block_index}",
                "finding": f"whole-essay review block {block_index}: draft acceptable",
            }
        rows.append(row)
    return rows


def anti_ai_audit_payload(
    *,
    draft_text: str = "Cooling access should be treated as housing policy.",
    passes: bool = True,
    paragraph_count: int = 1,
    paragraph_first_sentences: list[str] | None = None,
    first_sentence_chain_summarizes_essay: bool = False,
    paragraphs_under_50_words: int = 1,
    paragraphs_opening_with_topic_sentence: int = 1,
    filler_phrases_used: list[str] | None = None,
    concrete_source_handles: list[str] | None = None,
    self_check_notes: list[str] | None = None,
    revision_targets: list[dict[str, object]] | None = None,
    omit_last_block: bool = False,
) -> dict[str, object]:
    manifest = anti_ai_skill_manifest()
    block_rows = anti_ai_block_rows(draft_text, omit_last_block=omit_last_block)
    return {
        "pass": passes,
        "anti_ai_self_check": {
            "skill_file": manifest["path"],
            "skill_sha256": manifest["sha256"],
            "skill_line_count": manifest["line_count"],
            "draft_sha256": draft_sha256(draft_text),
            "block_audit": block_rows,
            "paragraph_count": paragraph_count,
            "paragraph_first_sentences": paragraph_first_sentences or ["A."],
            "first_sentence_chain_summarizes_essay": first_sentence_chain_summarizes_essay,
            "paragraphs_under_50_words": paragraphs_under_50_words,
            "paragraphs_opening_with_topic_sentence": paragraphs_opening_with_topic_sentence,
            "filler_phrases_used": filler_phrases_used or [],
            "significance_inflation_phrases": [],
            "vague_attributions_used": [],
            "concrete_source_handles": concrete_source_handles or ["source p. 1"],
            "style_guidance_grades": [],
            "self_check_notes": self_check_notes or [],
            "unmet_requirements": [],
            "final_decision": {
                "hard_rules_pass": passes,
                "soft_rules_pass": passes,
                "safe_to_claim_detector_reduction": passes,
                "reason": "Test fixture line-level skill audit decision.",
            },
        },
        "revision_targets": revision_targets or [],
    }
