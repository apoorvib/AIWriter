"""Focused tests for the new anti-AI deterministic checks and audit stage.

These tests prove the forcing functions actually fire, so we know the LLM
cannot quietly skip the soft-tier rules the way it could in the previous
build.
"""
from __future__ import annotations

import pytest

from essay_writer.drafting.anti_ai_audit import (
    ANTI_AI_AUDIT_SCHEMA,
    ANTI_AI_AUDIT_SYSTEM_PROMPT,
)
from essay_writer.drafting.prompts import (
    ANTI_AI_SELF_CHECK_SCHEMA,
    DRAFTING_SCHEMA,
    DRAFTING_SYSTEM_PROMPT,
)
from essay_writer.drafting.schema import AntiAISelfCheck, StyleGuidanceGrade
from essay_writer.validation.checks import run_deterministic_checks


# -----------------------------------------------------------------------------
# A. Soft-tier deterministic checks
# -----------------------------------------------------------------------------

def test_soft_tier_flags_filler_phrases():
    text = "In order to test the algorithm, we used a dataset."
    det = run_deterministic_checks(text)
    phrases = {h.word for h in det.soft_tier.filler_phrase_hits}
    assert "in order to" in phrases


def test_soft_tier_flags_significance_inflation():
    text = "The most important consequence is that it scales. What is striking here is the variance."
    det = run_deterministic_checks(text)
    phrases = {h.word for h in det.soft_tier.significance_inflation_hits}
    assert "the most important" in phrases
    assert "what is striking" in phrases


def test_soft_tier_flags_vague_attribution():
    text = "Experts believe that the algorithm is fast. Studies show it scales well."
    det = run_deterministic_checks(text)
    phrases = {h.word for h in det.soft_tier.vague_attribution_hits}
    assert "experts believe" in phrases
    assert "studies show" in phrases


def test_soft_tier_counts_short_paragraphs():
    long_para = " ".join(["word"] * 60)
    short_para = "Short."
    text = f"{long_para}\n\n{short_para}\n\n{long_para}"
    det = run_deterministic_checks(text)
    assert det.soft_tier.paragraphs_under_50_words == 1


def test_soft_tier_captures_first_sentence_chain():
    text = "The first paragraph opens here. Second sentence here.\n\nThis is the second paragraph. More text.\n\nWe then continue. End."
    det = run_deterministic_checks(text)
    assert det.soft_tier.paragraph_first_sentences == [
        "The first paragraph opens here.",
        "This is the second paragraph.",
        "We then continue.",
    ]


def test_soft_tier_counts_topic_sentence_openers():
    text = (
        "The first paragraph opens with the.\n\n"
        "This paragraph opens with this.\n\n"
        "We open with we.\n\n"
        "Yet another paragraph opens with yet."
    )
    det = run_deterministic_checks(text)
    # The, This, We — three topic-sentence openers; Yet is not on the list.
    assert det.soft_tier.paragraphs_opening_with_topic_sentence == 3


# -----------------------------------------------------------------------------
# B + E + G + H. Forcing-function schema / prompt contract
# -----------------------------------------------------------------------------

def test_draft_schema_requires_anti_ai_self_check():
    assert "anti_ai_self_check" in DRAFTING_SCHEMA["required"]
    assert "anti_ai_self_check" in DRAFTING_SCHEMA["properties"]


def test_anti_ai_self_check_schema_requires_audit_fields():
    required = set(ANTI_AI_SELF_CHECK_SCHEMA["required"])
    # Every soft-tier check that has no deterministic check (or whose
    # deterministic check is advisory) must be in the schema's required list,
    # because the schema is the forcing function for those fields.
    assert {
        "paragraph_count",
        "paragraph_first_sentences",
        "first_sentence_chain_summarizes_essay",
        "paragraphs_under_50_words",
        "filler_phrases_used",
        "significance_inflation_phrases",
        "vague_attributions_used",
        "concrete_source_handles",
        "style_guidance_grades",
        "self_check_notes",
    }.issubset(required)


def test_drafting_system_prompt_contains_self_check_contract():
    # The self-check section MUST be at the bottom of the prompt and must
    # explicitly reference the response field, so the model treats it as a
    # contract, not advisory context.
    prompt = DRAFTING_SYSTEM_PROMPT
    assert "ANTI-AI SELF-CHECK" in prompt
    assert "anti_ai_self_check" in prompt
    self_check_index = prompt.index("ANTI-AI SELF-CHECK")
    grounding_index = prompt.index("GROUNDING RULES")
    # Self-check must come AFTER grounding rules so last-instructions-win
    # behavior favors the audit.
    assert self_check_index > grounding_index


# -----------------------------------------------------------------------------
# C. New audit stage
# -----------------------------------------------------------------------------

def test_audit_schema_requires_pass_and_targets():
    assert ANTI_AI_AUDIT_SCHEMA["required"] == [
        "pass",
        "anti_ai_self_check",
        "revision_targets",
    ]


def test_audit_system_prompt_contains_only_one_skill():
    # The audit prompt must NOT contain drafting-specific instructions like
    # GROUNDING RULES or evidence_map references. The whole point is the
    # bounded single-skill audit.
    prompt = ANTI_AI_AUDIT_SYSTEM_PROMPT
    assert "anti-AI prose auditor" in prompt
    assert "anti_ai_detection_skill" in prompt
    assert "GROUNDING RULES" not in prompt
    assert "evidence_map" not in prompt


def test_audit_revision_targets_action_enum():
    actions = (
        ANTI_AI_AUDIT_SCHEMA["properties"]["revision_targets"]["items"]["properties"][
            "action"
        ]["enum"]
    )
    # These are the only revision actions the audit can request. New actions
    # should be added consciously, not silently.
    assert "split_into_short_paragraph" in actions
    assert "remove_filler" in actions
    assert "name_specific_source" in actions
    assert "advance_argument" in actions


# -----------------------------------------------------------------------------
# Schema round-trip: storage must round-trip the new fields
# -----------------------------------------------------------------------------

def test_audit_round_trips_through_storage(tmp_path):
    from essay_writer.drafting.schema import EssayDraft
    from essay_writer.drafting.storage import DraftStore

    audit = AntiAISelfCheck(
        paragraph_count=4,
        paragraph_first_sentences=["A.", "B.", "C.", "D."],
        first_sentence_chain_summarizes_essay=False,
        paragraphs_under_50_words=1,
        paragraphs_opening_with_topic_sentence=2,
        filler_phrases_used=["in order to"],
        significance_inflation_phrases=["the most important"],
        vague_attributions_used=[],
        concrete_source_handles=["p. 5"],
        style_guidance_grades=[
            StyleGuidanceGrade(bullet="open with a definition", followed=True, where="paragraph 1")
        ],
        self_check_notes=["removed 'in essence,' from paragraph 3"],
    )
    draft = EssayDraft(
        id="draft_test",
        job_id="job1",
        version=1,
        selected_topic_id="topic_001",
        content="Hello world.",
        anti_ai_self_check=audit,
    )
    store = DraftStore(tmp_path)
    store.save(draft)
    loaded = store.load("job1", 1)
    assert loaded.anti_ai_self_check is not None
    assert loaded.anti_ai_self_check.paragraph_count == 4
    assert loaded.anti_ai_self_check.first_sentence_chain_summarizes_essay is False
    assert loaded.anti_ai_self_check.filler_phrases_used == ["in order to"]
    assert loaded.anti_ai_self_check.style_guidance_grades[0].bullet == "open with a definition"
    assert loaded.anti_ai_self_check.self_check_notes == [
        "removed 'in essence,' from paragraph 3"
    ]


def test_anti_ai_self_check_default_none_for_legacy_drafts(tmp_path):
    """A draft without anti_ai_self_check round-trips with None."""
    from essay_writer.drafting.schema import EssayDraft
    from essay_writer.drafting.storage import DraftStore

    draft = EssayDraft(
        id="draft_test",
        job_id="job1",
        version=1,
        selected_topic_id="topic_001",
        content="Hello world.",
    )
    store = DraftStore(tmp_path)
    store.save(draft)
    loaded = store.load("job1", 1)
    assert loaded.anti_ai_self_check is None
