"""Helpers for planning windowed style revision over long drafts.

Long drafts expose two LLM weaknesses during the anti-AI rewrite pass:
attention tapers across the output, and middle paragraphs get skimmed. The
windowed flow splits the draft into ~target_window_words slices on paragraph
boundaries so each window gets a focused, full-attention pass.
"""
from __future__ import annotations

from dataclasses import dataclass


DEFAULT_WINDOWED_REVISION_WORD_THRESHOLD = 1200
DEFAULT_TARGET_WINDOW_WORDS = 400


@dataclass(frozen=True)
class StyleRevisionWindow:
    index: int
    paragraph_start: int  # inclusive
    paragraph_end: int  # exclusive
    word_count: int

    def as_dict(self) -> dict[str, int]:
        return {
            "index": self.index,
            "paragraph_start": self.paragraph_start,
            "paragraph_end": self.paragraph_end,
            "word_count": self.word_count,
        }


def split_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def should_window_style_revision(
    text: str,
    *,
    threshold_words: int = DEFAULT_WINDOWED_REVISION_WORD_THRESHOLD,
) -> bool:
    return len(text.split()) > threshold_words


def plan_style_revision_windows(
    text: str,
    *,
    target_window_words: int = DEFAULT_TARGET_WINDOW_WORDS,
) -> list[StyleRevisionWindow]:
    """Split text into windows ~target_window_words large on paragraph boundaries.

    Never splits a paragraph. Always returns at least one window if there is
    any paragraph content.
    """
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []

    windows: list[StyleRevisionWindow] = []
    current_words = 0
    start_index = 0

    for i, paragraph in enumerate(paragraphs):
        paragraph_words = len(paragraph.split())
        # Close the current window before adding this paragraph if doing so
        # would push us past the target AND we already have content. Never
        # emit an empty window.
        if current_words + paragraph_words > target_window_words and current_words > 0:
            windows.append(
                StyleRevisionWindow(
                    index=len(windows),
                    paragraph_start=start_index,
                    paragraph_end=i,
                    word_count=current_words,
                )
            )
            start_index = i
            current_words = 0
        current_words += paragraph_words

    windows.append(
        StyleRevisionWindow(
            index=len(windows),
            paragraph_start=start_index,
            paragraph_end=len(paragraphs),
            word_count=current_words,
        )
    )
    return windows


def assemble_window_outputs(window_texts: list[str]) -> str:
    """Concatenate per-window revised text into a single draft body.

    Each window's content is treated as one or more paragraphs separated by
    blank lines. Windows are joined with a paragraph break so the assembled
    output matches the original paragraph-block convention.
    """
    cleaned = [text.strip() for text in window_texts if text and text.strip()]
    return "\n\n".join(cleaned)
