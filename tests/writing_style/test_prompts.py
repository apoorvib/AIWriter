from essay_writer.writing_style.prompts import build_writing_style_prompt_block
from essay_writer.writing_style.schema import (
    PromptSampleText,
    StyleAnchorExcerpt,
    WritingStyleContent,
    WritingStylePayload,
)


def test_prompt_block_marks_samples_as_style_only() -> None:
    content = WritingStyleContent(
        id="style-test",
        version=1,
        sample_ids=["sample-1"],
        sample_fingerprint="abc123",
        guidance=["Use formal academic prose without inflated transitions."],
        anchor_excerpts=[
            StyleAnchorExcerpt(
                sample_id="sample-1",
                excerpt_id="ex-1",
                text="A field is simply a quantity assigned to all points in space.",
                role="opening_move",
                reason="Defines a term directly, then elaborates.",
            )
        ],
    )
    payload = WritingStylePayload(
        style_content=content,
        samples=[
            PromptSampleText(
                sample_id="sample-1",
                title="Fields",
                cleaned_text="A field is simply a quantity assigned to all points in space.",
                cleaned_text_hash="hash-1",
            )
        ],
    )
    block = build_writing_style_prompt_block(payload)
    assert "style exemplars only" in block
    assert "Do not treat these samples as evidence." in block
    assert "<sample id=\"sample-1\" title=\"Fields\">" in block
