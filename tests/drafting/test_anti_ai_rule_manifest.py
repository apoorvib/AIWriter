from __future__ import annotations

import pytest

from essay_writer.drafting.anti_ai_skill import (
    ANTI_AI_SKILL_PATH,
    AntiAISkillManifestError,
    _sha256_text,
    anti_ai_rule_manifest,
)

# The live anti-AI skill file is the canonical rule-numbered document.
SKILL_PATH = ANTI_AI_SKILL_PATH

EXPECTED_RULE_COUNT = 31  # tracks anti-ai-detection-SKILL.md; update if the file changes


def _manifest() -> dict:
    return anti_ai_rule_manifest()


def test_rule_ids_are_contiguous_r1_to_n():
    manifest = _manifest()
    rules = manifest["rules"]
    assert manifest["rule_count"] == len(rules) == EXPECTED_RULE_COUNT
    assert [r["rule_id"] for r in rules] == [f"R{n}" for n in range(1, len(rules) + 1)]


def test_self_check_unit_is_present():
    self_check = _manifest()["self_check"]
    assert self_check is not None
    assert self_check["rule_id"] == "self_check"
    assert str(self_check["section"]).lower().startswith("self-check")


def test_rule_spans_are_ordered_and_nonoverlapping():
    prev_end = 0
    for rule in _manifest()["rules"]:
        assert rule["start_line"] <= rule["end_line"]
        assert rule["start_line"] > prev_end, "rule spans must not overlap or go backwards"
        prev_end = rule["end_line"]


def test_rule_text_hash_reproduces():
    for rule in _manifest()["rules"]:
        assert rule["rule_text_sha256"] == _sha256_text(str(rule["text"]))


def test_last_rule_excludes_trailing_horizontal_rule():
    # Regression for the v2 edge: without `---` as a span boundary the final rule
    # before a section separator absorbed the `---` into its hashed text.
    last = _manifest()["rules"][-1]
    assert not str(last["text"]).rstrip().endswith("---")
    assert "\n---" not in str(last["text"])


def test_every_rule_row_has_required_shape():
    for rule in _manifest()["rules"]:
        assert set(rule) >= {
            "rule_id",
            "ordinal",
            "title",
            "start_line",
            "end_line",
            "text",
            "rule_text_sha256",
        }
        assert rule["title"], f"{rule['rule_id']} should have a parsed title"


def test_manifest_binds_to_exact_file_bytes():
    raw = SKILL_PATH.read_text(encoding="utf-8")
    manifest = _manifest()
    assert manifest["sha256"] == _sha256_text(raw)
    assert manifest["skill_line_count"] == len(raw.splitlines())


def test_projected_audit_surface_is_small():
    # ~32 rows vs ~138 blocks today: the whole point of the redesign.
    manifest = _manifest()
    rows = manifest["rule_count"] + (1 if manifest["self_check"] else 0)
    assert rows < 40


def test_noncanonical_file_raises(tmp_path):
    # A skill file without `**R#` markers must fail loud rather than return an
    # empty audit surface.
    markerless = tmp_path / "markerless-SKILL.md"
    markerless.write_text(
        "# Title\n\nSome prose with no rule markers at all.\n", encoding="utf-8"
    )
    with pytest.raises(AntiAISkillManifestError):
        anti_ai_rule_manifest(markerless)


def test_orphan_line_in_rule_section_raises(tmp_path):
    # A content line between a rule-section heading and its first `**R#` marker is
    # not covered by any rule span -> drift guard must raise.
    content = SKILL_PATH.read_text(encoding="utf-8")
    broken = content.replace(
        "## Vocabulary and phrasing\n",
        "## Vocabulary and phrasing\n\nStray uncovered prose line.\n",
        1,
    )
    broken_path = tmp_path / "broken-SKILL.md"
    broken_path.write_text(broken, encoding="utf-8")
    with pytest.raises(AntiAISkillManifestError):
        anti_ai_rule_manifest(broken_path)


def test_noncontiguous_ids_raise(tmp_path):
    content = SKILL_PATH.read_text(encoding="utf-8")
    # Drop R9's marker bold so the id sequence skips 9.
    broken = content.replace("**R9 — ", "R9 dropped marker ", 1)
    broken_path = tmp_path / "gap-SKILL.md"
    broken_path.write_text(broken, encoding="utf-8")
    with pytest.raises(AntiAISkillManifestError):
        anti_ai_rule_manifest(broken_path)
