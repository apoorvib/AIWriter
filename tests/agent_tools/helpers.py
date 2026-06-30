from __future__ import annotations

from essay_writer.agent_tools.schemas import WorkProducer
from essay_writer.drafting.anti_ai_skill import anti_ai_skill_manifest, draft_sha256


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
    omit_last_line: bool = False,
) -> dict[str, object]:
    manifest = anti_ai_skill_manifest()
    lines = manifest["lines"][:-1] if omit_last_line else manifest["lines"]
    draft_quote = draft_text.strip().splitlines()[0][:120] if draft_text.strip() else ""
    paragraph_count_reviewed = len([part for part in draft_text.split("\n\n") if part.strip()])
    line_rows = []
    for line in lines:
        line_number = int(line["line_number"])
        line_text = str(line["text"])
        status = "context" if not line_text.strip() else "passed"
        excerpt = line_text.strip()[:80] or "<blank>"
        line_rows.append(
            {
                "line_number": line_number,
                "line_text_sha256": line["sha256"],
                "requirement": f"Line {line_number} requirement from skill text: {excerpt}",
                "status": status,
                "evidence": f"Line {line_number} checked against draft and workflow contract.",
                "draft_evidence": [
                    {
                        "kind": "not_applicable" if status == "context" else "draft_quote",
                        "reference": (
                            f"line {line_number} is context-only"
                            if status == "context"
                            else draft_quote
                        ),
                        "explanation": (
                            f"Line {line_number} has no direct prose requirement."
                            if status == "context"
                            else f"Line {line_number} was checked against this exact draft sentence."
                        ),
                    }
                ],
                "whole_essay_evidence": {
                    "scope": "whole_essay",
                    "paragraph_count_reviewed": paragraph_count_reviewed,
                    "method": (
                        f"Reviewed all {paragraph_count_reviewed} paragraphs before "
                        f"deciding skill line {line_number}."
                    ),
                    "finding": (
                        f"Whole-essay review for line {line_number} found the fixture "
                        "draft acceptable or context-only."
                    ),
                },
                "line_application": (
                    f"Line {line_number} applies to the fixture draft through the quoted "
                    f"sentence or is classified as context: {excerpt}"
                ),
                "action_taken": f"Applied or classified line {line_number} during audit.",
            }
        )
    return {
        "pass": passes,
        "anti_ai_self_check": {
            "skill_file": manifest["path"],
            "skill_sha256": manifest["sha256"],
            "skill_line_count": manifest["line_count"],
            "draft_sha256": draft_sha256(draft_text),
            "line_audit": line_rows,
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
