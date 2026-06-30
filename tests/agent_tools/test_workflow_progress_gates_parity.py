from essay_writer.agent_tools.workflow_predicates import is_anti_ai_audit_fresh
from essay_writer.agent_tools.facade import _anti_ai_audit_freshness_error
from essay_writer.drafting.schema import EssayDraft


def _draft(audit=None):
    return EssayDraft(
        id="draft-1", job_id="job-1", version=1,
        selected_topic_id="topic-1", content="Para one.\n\nPara two.",
        anti_ai_self_check=audit,
    )


def test_gate_errors_exactly_when_predicate_false_for_missing_audit():
    draft = _draft(audit=None)
    predicate_fresh = is_anti_ai_audit_fresh(draft)
    gate_error = _anti_ai_audit_freshness_error("prepare_validation", draft=draft)
    # When the predicate says "not fresh", the gate must raise its structured error.
    assert predicate_fresh is False
    assert gate_error is not None
    assert gate_error.error.code in {"anti_ai_audit_required", "anti_ai_audit_stale"}
