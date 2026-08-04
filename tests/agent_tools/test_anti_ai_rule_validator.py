from __future__ import annotations

import copy
import json
import re
from types import SimpleNamespace

from essay_writer.agent_tools.facade import _validate_anti_ai_rule_audit_binding
from essay_writer.drafting.anti_ai_skill import anti_ai_rule_manifest, draft_sha256

DRAFT = (
    "Cooling access should be treated as housing policy, not comfort.\n\n"
    "The city records heat deaths in the same buildings every summer."
)


def _paragraphs(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text) if p.strip()])


def _manifest() -> dict:
    return anti_ai_rule_manifest()


def _rule_row(rule_id: str, rule_text_sha256: str, draft: str) -> dict:
    quote = draft.strip().splitlines()[0][:80]
    return {
        "rule_id": rule_id,
        "rule_text_sha256": rule_text_sha256,
        "status": "passed",
        "finding": f"{rule_id}: guidance satisfied by the draft.",
        "rule_application": f"Rule {rule_id} applied across the whole draft.",
        "draft_evidence": [
            {
                "kind": "draft_quote",
                "reference": quote,
                "explanation": f"{rule_id} checked against this draft sentence.",
            }
        ],
        "whole_essay_evidence": {
            "scope": "whole_essay",
            "paragraph_count_reviewed": _paragraphs(draft),
            "method": f"reviewed all {_paragraphs(draft)} paragraphs for {rule_id}",
            "finding": f"whole-essay review for {rule_id}: draft acceptable",
        },
    }


def _payload(draft: str = DRAFT, *, passes: bool = True) -> dict:
    manifest = _manifest()
    rows = [
        _rule_row(str(r["rule_id"]), str(r["rule_text_sha256"]), draft)
        for r in manifest["rules"]
    ]
    sc = manifest["self_check"]
    rows.append(_rule_row("self_check", str(sc["rule_text_sha256"]), draft))
    return {
        "pass": passes,
        "anti_ai_self_check": {
            "skill_file": manifest["path"],
            "skill_sha256": manifest["sha256"],
            "skill_line_count": manifest["skill_line_count"],
            "draft_sha256": draft_sha256(draft),
            "rule_audit": rows,
            "paragraph_first_sentences": ["A.", "B."],
            "first_sentence_chain_summarizes_essay": False,
            "paragraphs_under_50_words": 1,
            "paragraphs_opening_with_topic_sentence": 1,
            "filler_phrases_used": [],
            "significance_inflation_phrases": [],
            "vague_attributions_used": [],
            "concrete_source_handles": ["heat-death records"],
            "style_guidance_grades": [],
            "self_check_notes": [],
            "unmet_requirements": [],
            "final_decision": {
                "hard_rules_pass": passes,
                "soft_rules_pass": passes,
                "safe_to_claim_detector_reduction": passes,
                "reason": "Test fixture per-rule audit decision.",
            },
        },
        "revision_targets": [],
    }


def _validate(payload: dict, draft: str = DRAFT):
    return _validate_anti_ai_rule_audit_binding(
        payload,
        source_draft=SimpleNamespace(content=draft),
        rule_manifest=_manifest(),
    )


def test_valid_payload_accepts():
    assert _validate(_payload()) is None


def test_payload_is_small():
    assert len(json.dumps(_payload())) < 30 * 1024


def test_missing_rule_row_rejected():
    payload = _payload()
    payload["anti_ai_self_check"]["rule_audit"].pop()  # drop self_check row
    result = _validate(payload)
    assert result is not None and result.error.code == "anti_ai_rule_audit_incomplete"


def test_extra_unknown_rule_rejected():
    payload = _payload()
    extra = copy.deepcopy(payload["anti_ai_self_check"]["rule_audit"][0])
    extra["rule_id"] = "R999"
    payload["anti_ai_self_check"]["rule_audit"].append(extra)
    result = _validate(payload)
    assert result is not None and result.error.code == "anti_ai_rule_audit_incomplete"


def test_bad_rule_hash_rejected():
    payload = _payload()
    payload["anti_ai_self_check"]["rule_audit"][0]["rule_text_sha256"] = "sha256:deadbeef"
    result = _validate(payload)
    assert result is not None and result.error.code == "anti_ai_rule_audit_hash_mismatch"


def test_skill_hash_mismatch_rejected():
    payload = _payload()
    payload["anti_ai_self_check"]["skill_sha256"] = "sha256:0000"
    result = _validate(payload)
    assert result is not None and result.error.code == "anti_ai_skill_hash_mismatch"


def test_draft_hash_mismatch_rejected():
    payload = _payload()
    payload["anti_ai_self_check"]["draft_sha256"] = "sha256:0000"
    result = _validate(payload)
    assert result is not None and result.error.code == "anti_ai_draft_hash_mismatch"


def test_weak_reasoning_rejected():
    payload = _payload()
    payload["anti_ai_self_check"]["rule_audit"][0]["rule_application"] = "ok"
    result = _validate(payload)
    assert result is not None and result.error.code == "anti_ai_rule_audit_weak_reasoning"


def test_failed_row_must_be_unmet_and_fail_pass():
    payload = _payload(passes=True)
    payload["anti_ai_self_check"]["rule_audit"][0]["status"] = "failed"
    # left out of unmet_requirements and pass still true -> inconsistent
    result = _validate(payload)
    assert result is not None and result.error.code == "anti_ai_rule_audit_inconsistent"


def test_failed_row_consistent_accepts():
    payload = _payload(passes=False)
    row = payload["anti_ai_self_check"]["rule_audit"][0]
    row["status"] = "failed"
    payload["anti_ai_self_check"]["unmet_requirements"] = [
        {
            "rule_id": row["rule_id"],
            "section": "Mechanical bans",
            "status": "failed",
            "reason": "draft used an em dash",
            "risk": "detector flag",
        }
    ]
    payload["anti_ai_self_check"]["final_decision"] = {
        "hard_rules_pass": False,
        "soft_rules_pass": False,
        "safe_to_claim_detector_reduction": False,
        "reason": "one hard rule failed",
    }
    assert _validate(payload) is None


def test_not_applicable_row_accepts():
    payload = _payload()
    row = payload["anti_ai_self_check"]["rule_audit"][0]
    row["status"] = "not_applicable"
    row["draft_evidence"] = [
        {
            "kind": "not_applicable",
            "reference": "n/a",
            "explanation": "this rule does not apply to this draft",
        }
    ]
    assert _validate(payload) is None
