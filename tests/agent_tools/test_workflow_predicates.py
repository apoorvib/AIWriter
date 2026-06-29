from dataclasses import replace

from essay_writer.agent_tools.workflow_predicates import (
    is_anti_ai_audit_fresh,
    latest_validation_passing,
    writing_style_decision_made,
)
from essay_writer.drafting.anti_ai_skill import anti_ai_skill_manifest, draft_sha256
from essay_writer.drafting.schema import AntiAISelfCheck, EssayDraft


def _draft(content="Body paragraph one.\n\nBody paragraph two.", audit=None):
    return EssayDraft(
        id="draft-1", job_id="job-1", version=1,
        selected_topic_id="topic-1", content=content, anti_ai_self_check=audit,
    )


def test_audit_missing_is_not_fresh():
    assert is_anti_ai_audit_fresh(_draft(audit=None)) is False


def test_audit_matching_hashes_is_fresh():
    manifest = anti_ai_skill_manifest()
    content = "Body paragraph one.\n\nBody paragraph two."
    audit = AntiAISelfCheck(
        skill_sha256=str(manifest["sha256"]),
        skill_line_count=int(manifest["line_count"]),
        draft_sha256=draft_sha256(content),
    )
    assert is_anti_ai_audit_fresh(_draft(content=content, audit=audit)) is True


def test_audit_stale_draft_hash_is_not_fresh():
    manifest = anti_ai_skill_manifest()
    audit = AntiAISelfCheck(
        skill_sha256=str(manifest["sha256"]),
        skill_line_count=int(manifest["line_count"]),
        draft_sha256="sha256:deadbeef",
    )
    assert is_anti_ai_audit_fresh(_draft(audit=audit)) is False


def test_writing_style_decision_made_variants():
    class J:
        writing_style_content_id = None
        writing_style_skip_token = None
    assert writing_style_decision_made(J()) is False
    J.writing_style_content_id = "wsc-1"
    assert writing_style_decision_made(J()) is True
    J.writing_style_content_id = None
    J.writing_style_skip_token = "tok-1"
    assert writing_style_decision_made(J()) is True


class _StubValStore:
    def __init__(self, report):
        self._report = report
    def load_latest(self, job_id):
        if self._report is None:
            raise KeyError(job_id)
        return self._report


class _Job:
    id = "job-1"
    draft_id = "draft-1"


def test_validation_passing_true_when_passes_and_matches_draft():
    report = type("R", (), {"passes": True, "draft_id": "draft-1"})()
    assert latest_validation_passing(_StubValStore(report), _Job()) is True


def test_validation_passing_false_when_no_report():
    assert latest_validation_passing(_StubValStore(None), _Job()) is False


def test_validation_passing_false_when_draft_mismatch():
    report = type("R", (), {"passes": True, "draft_id": "other"})()
    assert latest_validation_passing(_StubValStore(report), _Job()) is False
