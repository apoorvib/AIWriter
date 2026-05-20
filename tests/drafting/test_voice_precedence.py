"""Tests for the explicit precedence block that pins voice vs anti-AI hierarchy."""
from __future__ import annotations

from essay_writer.drafting.prompts import DRAFTING_SYSTEM_PROMPT
from essay_writer.drafting.style_revision import STYLE_REVISION_SYSTEM_PROMPT
from essay_writer.writing_style.prompts import build_writing_style_prompt_block
from essay_writer.writing_style.schema import (
    StyleAnchorExcerpt,
    WritingStyleContent,
    WritingStylePayload,
)


# Snippets that should appear in the prompt's hard-tier list. Same list shape
# as the deterministic commit gates so prompt and gate stay in sync.
HARD_TIER_PATTERNS = (
    "em dash",
    "en dash",
    "decorative hyphen",
    "high-risk vocabulary",
    "signposting",
    "in conclusion",
    "triplet",
)


def _has_precedence_block(prompt: str) -> bool:
    lower = prompt.lower()
    return (
        "precedence" in lower
        and "voice" in lower
        and "wins" in lower
        and "hard" in lower
    )


def test_drafting_system_prompt_declares_voice_precedence_with_hard_tier_exceptions() -> None:
    assert _has_precedence_block(DRAFTING_SYSTEM_PROMPT)
    lower = DRAFTING_SYSTEM_PROMPT.lower()
    for pattern in HARD_TIER_PATTERNS:
        assert pattern in lower, f"hard-tier pattern '{pattern}' missing from DRAFTING_SYSTEM_PROMPT"


def test_style_revision_system_prompt_declares_voice_precedence_with_hard_tier_exceptions() -> None:
    assert _has_precedence_block(STYLE_REVISION_SYSTEM_PROMPT)
    lower = STYLE_REVISION_SYSTEM_PROMPT.lower()
    for pattern in HARD_TIER_PATTERNS:
        assert pattern in lower, f"hard-tier pattern '{pattern}' missing from STYLE_REVISION_SYSTEM_PROMPT"


def test_writing_style_prompt_block_repeats_voice_precedence_reminder() -> None:
    payload = WritingStylePayload(
        style_content=WritingStyleContent(
            id="style-test",
            version=1,
            sample_ids=["sample-1"],
            sample_fingerprint="abc",
            guidance=["Prefer long sentences."],
            anchor_excerpts=[
                StyleAnchorExcerpt(
                    sample_id="sample-1",
                    excerpt_id="ex01",
                    text="Long passage about cities.",
                    role="tone",
                    reason="rhythm",
                )
            ],
        ),
        samples=[],
    )
    block = build_writing_style_prompt_block(payload)

    assert "precedence" in block.lower()
    assert "voice" in block.lower()
    assert "em dash" in block.lower() or "em-dash" in block.lower()
