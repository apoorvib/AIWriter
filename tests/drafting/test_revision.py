from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.drafting.revision import DraftRevisionService
from essay_writer.drafting.schema import EssayDraft, SectionSourceMap
from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.schema import OutlineSection, ThesisOutline
from essay_writer.research.schema import EvidenceMap, ResearchNote
from essay_writer.sources.access_schema import SourceLocator, SourceTextPacket
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.tone_alignment.schema import ToneAlignmentConflict, ToneAlignmentReport
from essay_writer.topic_ideation.schema import SelectedTopic
from essay_writer.validation.schema import (
    AssignmentFit,
    DeterministicCheckResult,
    LLMJudgmentResult,
    LengthCheck,
    UnsupportedClaim,
    ValidationDiagnostic,
    ValidationReport,
)
from essay_writer.writing_style.schema import PromptSampleText, StyleAnchorExcerpt, WritingStyleContent, WritingStylePayload


def test_revision_service_passes_source_packets_to_llm() -> None:
    client = MockLLMClient(
        responses=[
            {
                "content": "Revised draft.",
                "section_source_map": [
                    {
                        "section_id": "section_001",
                        "heading": "Body",
                        "note_ids": ["note_001"],
                        "source_ids": ["src1"],
                    }
                ],
                "bibliography_candidates": [],
                "known_weak_spots": [],
                "anti_ai_self_check": {
                    "paragraph_count": 1,
                    "paragraph_first_sentences": [],
                    "first_sentence_chain_summarizes_essay": False,
                    "paragraphs_under_50_words": 1,
                    "paragraphs_opening_with_topic_sentence": 0,
                    "filler_phrases_used": [],
                    "significance_inflation_phrases": [],
                    "vague_attributions_used": [],
                    "concrete_source_handles": [],
                    "style_guidance_grades": [],
                    "self_check_notes": [],
                },
            }
        ]
    )
    service = DraftRevisionService(client)

    service.revise(
        EssayJob(id="job1", task_spec_id="task1", selected_topic_id="topic_001"),
        _task_spec(),
        _topic(),
        _evidence_map(),
        outline=_outline(),
        previous_draft=_previous_draft(),
        validation=_validation(),
        source_packets=[_source_packet()],
        version=2,
    )
    blocks = client.calls[0]["user_blocks"]
    static_ctx = json.loads(blocks[0].text)
    mutable_ctx = _parse_mutable_revision_context(blocks[1].text)

    assert blocks[0].cacheable is True
    assert blocks[1].cacheable is False
    assert static_ctx["source_packets"][0]["packet_id"] == "src1-pdf-pages-0002-0002"
    assert static_ctx["source_packets"][0]["source_id"] == "src1"
    assert static_ctx["source_packets"][0]["pdf_page_start"] == 2
    assert static_ctx["source_packets"][0]["text"] == "Source excerpt used for revision."
    assert mutable_ctx["revision_task"]["diagnostics"][0]["issue_type"] == "unsupported_claim"
    assert mutable_ctx["revision_task"]["diagnostics"][0]["action"] == "strengthen_grounding"


def test_revision_service_includes_tone_alignment_and_writing_style_payload() -> None:
    client = MockLLMClient(
        responses=[
            {
                "content": "Revised draft.",
                "section_source_map": [],
                "bibliography_candidates": [],
                "known_weak_spots": [],
                "anti_ai_self_check": {
                    "paragraph_count": 1,
                    "paragraph_first_sentences": [],
                    "first_sentence_chain_summarizes_essay": False,
                    "paragraphs_under_50_words": 1,
                    "paragraphs_opening_with_topic_sentence": 0,
                    "filler_phrases_used": [],
                    "significance_inflation_phrases": [],
                    "vague_attributions_used": [],
                    "concrete_source_handles": [],
                    "style_guidance_grades": [],
                    "self_check_notes": [],
                },
            }
        ]
    )
    service = DraftRevisionService(client)

    service.revise(
        EssayJob(id="job1", task_spec_id="task1", selected_topic_id="topic_001"),
        _task_spec(),
        _topic(),
        _evidence_map(),
        outline=_outline(),
        previous_draft=_previous_draft(),
        validation=_validation(),
        tone_alignment=_tone_alignment(),
        writing_style_payload=_writing_style_payload(),
        version=2,
    )
    blocks = client.calls[0]["user_blocks"]
    mutable_text = blocks[1].text
    mutable_ctx = _parse_mutable_revision_context(mutable_text)
    style_block = mutable_text.split("\n\n<writing_style_samples>", 1)[1]

    assert mutable_ctx["revision_task"]["tone_alignment"]["requires_revision"] is True
    assert mutable_ctx["revision_task"]["tone_alignment"]["anti_ai_conflicts"][0]["resolution"] == "prefer_tone"
    assert mutable_ctx["revision_task"]["deterministic_style_issues"]["em_dash_count"] == 0
    assert "style exemplars only" in style_block.lower()
    assert "The samples favor long, accumulative sentences before a tighter claim." in style_block


def test_revision_static_block_matches_drafting_static_block_for_cache_reuse() -> None:
    """The Anthropic prompt cache hits only when the prefix bytes match
    exactly. The static (cacheable) user block produced by drafting and the
    one produced by revision must therefore be byte-identical when given the
    same task spec / topic / evidence / outline / source packets."""
    from essay_writer.drafting.service import build_static_drafting_context_json
    from essay_writer.drafting.revision import _build_revision_blocks

    task_spec = _task_spec()
    topic = _topic()
    evidence_map = _evidence_map()
    outline = _outline()
    packets = [_source_packet()]

    drafting_static = build_static_drafting_context_json(
        task_spec, topic, evidence_map, outline, packets
    )
    revision_blocks = _build_revision_blocks(
        task_spec=task_spec,
        selected_topic=topic,
        evidence_map=evidence_map,
        outline=outline,
        previous_draft=_previous_draft(),
        validation=_validation(),
        source_packets=packets,
        writing_style_payload=None,
        tone_alignment=None,
        user_instruction=None,
        change_summary=[],
    )

    assert revision_blocks[0].cacheable is True
    assert revision_blocks[0].text == drafting_static


def _parse_mutable_revision_context(mutable_text: str) -> dict:
    """The mutable block has the shape: '\n\n<instruction>\n\n<json>[...]\n\n<style>'.
    Find the JSON object embedded after the instruction prelude."""
    start = mutable_text.index("{")
    depth = 0
    for idx in range(start, len(mutable_text)):
        ch = mutable_text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(mutable_text[start : idx + 1])
    raise ValueError("Could not locate JSON context in mutable revision block")


def _task_spec() -> TaskSpecification:
    return TaskSpecification(id="task1", version=1, raw_text="Write an essay.", citation_style="MLA")


def _topic() -> SelectedTopic:
    return SelectedTopic(
        job_id="job1",
        round_id="round1",
        topic_id="topic_001",
        title="Topic",
        research_question="Question?",
        tentative_thesis_direction="Thesis.",
    )


def _evidence_map() -> EvidenceMap:
    return EvidenceMap(
        id="evidence_map_v001",
        job_id="job1",
        selected_topic_id="topic_001",
        research_question="Question?",
        thesis_direction="Thesis.",
        notes=[
            ResearchNote(
                id="note_001",
                source_id="src1",
                chunk_id="src1-packet",
                page_start=2,
                page_end=2,
                claim="Claim.",
                quote="Source excerpt used for revision.",
                paraphrase="Paraphrase.",
                relevance="Relevant.",
                supports_topic=True,
                evidence_type="support",
                confidence=0.9,
            )
        ],
        evidence_groups=[],
        gaps=[],
        conflicts=[],
    )


def _outline() -> ThesisOutline:
    return ThesisOutline(
        id="outline1",
        job_id="job1",
        selected_topic_id="topic_001",
        research_plan_id="plan1",
        evidence_map_id="evidence_map_v001",
        version=1,
        working_thesis="Thesis.",
        sections=[
            OutlineSection(
                id="section_001",
                heading="Body",
                purpose="support",
                key_points=["Claim."],
                note_ids=["note_001"],
            )
        ],
    )


def _previous_draft() -> EssayDraft:
    return EssayDraft(
        id="draft1",
        job_id="job1",
        version=1,
        selected_topic_id="topic_001",
        content="Old draft.",
        outline_id="outline1",
        section_source_map=[SectionSourceMap(section_id="section_001", heading="Body", note_ids=["note_001"])],
    )


def _validation() -> ValidationReport:
    return ValidationReport(
        draft_id="draft1",
        task_spec_id="task1",
        deterministic=DeterministicCheckResult(
            word_count=2,
            em_dash_count=0,
            tier1_vocab_hits=[],
            bad_conclusion_opener=False,
            consecutive_similar_sentence_runs=[],
            participial_phrase_count=0,
            participial_phrase_rate=0.0,
            contrastive_negation_count=0,
            signposting_hits=[],
        ),
        llm_judgment=LLMJudgmentResult(
            unsupported_claims=[UnsupportedClaim(claim="Unsupported.", paragraph=1)],
            citation_issues=[],
            rubric_scores=[],
            assignment_fit=AssignmentFit(passes=True, explanation="Fits."),
            length_check=LengthCheck(actual_words=2, target_words=None, passes=True),
            style_issues=[],
            diagnostics=[
                ValidationDiagnostic(
                    location="paragraph 1",
                    issue_type="unsupported_claim",
                    evidence="Unsupported.",
                    severity="high",
                    action="strengthen_grounding",
                )
            ],
            revision_suggestions=["Ground the claim."],
            overall_quality=0.5,
        ),
    )


def _source_packet() -> SourceTextPacket:
    return SourceTextPacket(
        packet_id="src1-pdf-pages-0002-0002",
        source_id="src1",
        locator=SourceLocator(source_id="src1", locator_type="pdf_pages", pdf_page_start=2, pdf_page_end=2),
        text="Source excerpt used for revision.",
        pdf_page_start=2,
        pdf_page_end=2,
        extraction_method="pypdf",
        text_quality="readable",
    )


def _tone_alignment() -> ToneAlignmentReport:
    return ToneAlignmentReport(
        draft_id="draft1",
        writing_style_content_id="style_001",
        overall_alignment=0.45,
        requires_revision=True,
        matched_habits=["Uses formal academic prose."],
        mismatched_habits=["Paragraphs break too quickly compared with the samples."],
        preserve_points=["Keep the current direct handling of the thesis."],
        revision_targets=["Let the body paragraphs develop longer before pivoting."],
        anti_ai_conflicts=[
            ToneAlignmentConflict(
                issue_type="paragraph_shape",
                anti_ai_signal="Long body paragraphs look too even.",
                tone_signal="The real samples sustain longer technical paragraphs.",
                resolution="prefer_tone",
                rationale="Longer paragraph development is authentic for this writer.",
            )
        ],
    )


def _writing_style_payload() -> WritingStylePayload:
    return WritingStylePayload(
        style_content=WritingStyleContent(
            id="style_001",
            version=1,
            sample_ids=["sample_001"],
            sample_fingerprint="fingerprint-001",
            guidance=["Uses formal academic prose with sustained paragraph development."],
            preferred_moves=["Defines the concept before widening to implications."],
            anchor_excerpts=[
                StyleAnchorExcerpt(
                    sample_id="sample_001",
                    excerpt_id="excerpt_001",
                    text="The samples favor long, accumulative sentences before a tighter claim.",
                    role="body_rhythm",
                    reason="Typical sentence movement.",
                )
            ],
        ),
        samples=[
            PromptSampleText(
                sample_id="sample_001",
                title="Sample One",
                cleaned_text="The samples favor long, accumulative sentences before a tighter claim.",
                cleaned_text_hash="hash-001",
            )
        ],
    )
