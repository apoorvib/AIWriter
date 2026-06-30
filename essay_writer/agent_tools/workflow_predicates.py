from __future__ import annotations

from essay_writer.drafting.anti_ai_skill import anti_ai_skill_manifest, draft_sha256


def is_anti_ai_audit_fresh(draft: object) -> bool:
    """True iff the draft carries a committed anti-AI audit whose skill and
    draft hashes match the current skill file and the exact draft text.

    Mirrors the cheap hash checks in facade `_anti_ai_audit_freshness_error`.
    The deeper binding validation stays in that gate; the ledger uses this
    predicate as the canonical "is the audit fresh for this draft" signal.
    """
    audit = getattr(draft, "anti_ai_self_check", None)
    if audit is None:
        return False
    skill_hash = getattr(audit, "skill_sha256", "")
    draft_hash = getattr(audit, "draft_sha256", "")
    if not skill_hash or not draft_hash:
        return False
    manifest = anti_ai_skill_manifest()
    if skill_hash != str(manifest["sha256"]):
        return False
    if int(getattr(audit, "skill_line_count", 0) or 0) != int(manifest["line_count"]):
        return False
    if draft_hash != draft_sha256(str(getattr(draft, "content", ""))):
        return False
    return True


def writing_style_decision_made(job: object) -> bool:
    """True iff the job has attached writing-style content OR recorded a skip
    token (the two outcomes the writing-style gate accepts)."""
    return bool(getattr(job, "writing_style_content_id", None)) or bool(
        getattr(job, "writing_style_skip_token", None)
    )


def latest_validation_passing(validation_store: object, job: object) -> bool:
    """True iff the job's latest validation report passes and is bound to the
    job's latest committed draft (matches the export gate's check)."""
    job_id = getattr(job, "id", None)
    if not job_id:
        return False
    try:
        report = validation_store.load_latest(job_id)
    except (KeyError, FileNotFoundError):
        return False
    return bool(getattr(report, "passes", False)) and getattr(
        report, "draft_id", None
    ) == getattr(job, "draft_id", None)
