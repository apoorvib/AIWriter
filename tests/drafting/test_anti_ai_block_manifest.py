from __future__ import annotations

from essay_writer.drafting.anti_ai_skill import (
    anti_ai_block_manifest,
    anti_ai_skill_manifest,
)


def test_block_manifest_indices_are_contiguous_1_to_n():
    manifest = anti_ai_block_manifest()
    blocks = manifest["blocks"]
    assert manifest["block_count"] == len(blocks)
    assert [b["block_index"] for b in blocks] == list(range(1, len(blocks) + 1))


def test_block_manifest_line_spans_are_ordered_and_nonoverlapping():
    blocks = anti_ai_block_manifest()["blocks"]
    prev_end = 0
    for b in blocks:
        assert b["start_line"] <= b["end_line"]
        assert b["start_line"] > prev_end, "blocks must not overlap or go backwards"
        prev_end = b["end_line"]


def test_block_manifest_hash_reproduces_from_text():
    from essay_writer.drafting.anti_ai_skill import _sha256_text

    for b in anti_ai_block_manifest()["blocks"]:
        assert b["block_text_sha256"] == _sha256_text(str(b["text"]))


def test_block_manifest_shares_skill_hash_and_line_count():
    block_manifest = anti_ai_block_manifest()
    line_manifest = anti_ai_skill_manifest()
    assert block_manifest["sha256"] == line_manifest["sha256"]
    assert block_manifest["skill_line_count"] == line_manifest["line_count"]


def test_block_manifest_is_much_smaller_than_line_manifest():
    # The whole point of the redesign: block coverage must be far cheaper than
    # per-line coverage so the audit payload is submittable inline.
    block_manifest = anti_ai_block_manifest()
    line_manifest = anti_ai_skill_manifest()
    assert block_manifest["block_count"] < line_manifest["line_count"] // 2


def test_block_manifest_marks_headings_structural_and_prose_not():
    blocks = anti_ai_block_manifest()["blocks"]
    heading_blocks = [b for b in blocks if str(b["text"]).lstrip().startswith("# ")]
    assert heading_blocks, "expected at least one top-level heading block"
    assert all(b["is_structural"] for b in heading_blocks)
    # A block containing a bolded rule sentence is guidance, not structural.
    rule_blocks = [b for b in blocks if "**Rule:" in str(b["text"])]
    assert rule_blocks, "expected at least one **Rule:** block"
    assert all(not b["is_structural"] for b in rule_blocks)
