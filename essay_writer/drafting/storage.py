from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.drafting.schema import (
    AntiAIFinalDecision,
    AntiAISkillRuleAudit,
    AntiAISelfCheck,
    AntiAIUnmetRequirement,
    EssayDraft,
    SectionSourceMap,
    StyleGuidanceGrade,
)


class DraftStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, draft: EssayDraft) -> None:
        path = self._path(draft.job_id, draft.version)
        if path.exists():
            raise FileExistsError(f"draft version already exists: {path}")
        _write_json(path, asdict(draft))

    def next_version(self, job_id: str) -> int:
        versions = self._versions(job_id)
        if not versions:
            return 1
        return versions[-1] + 1

    def load_latest(self, job_id: str) -> EssayDraft:
        versions = self._versions(job_id)
        if not versions:
            raise KeyError(job_id)
        return self.load(job_id, versions[-1])

    def list_versions(self, job_id: str) -> list[EssayDraft]:
        return [self.load(job_id, version) for version in self._versions(job_id)]

    def load(self, job_id: str, version: int) -> EssayDraft:
        path = self._path(job_id, version)
        if not path.exists():
            raise KeyError(f"{job_id} draft v{version}")
        return _draft_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def find_by_id(self, job_id: str, draft_id: str) -> EssayDraft:
        for draft in self.list_versions(job_id):
            if draft.id == draft_id:
                return draft
        raise KeyError(f"{job_id} {draft_id}")

    def _path(self, job_id: str, version: int) -> Path:
        return self.root / job_id / f"draft_v{version:03d}.json"

    def _versions(self, job_id: str) -> list[int]:
        dir_ = self.root / job_id
        if not dir_.exists():
            return []
        versions = []
        for path in dir_.glob("draft_v*.json"):
            suffix = path.stem.removeprefix("draft_v")
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)


def _draft_from_payload(payload: dict) -> EssayDraft:
    payload = dict(payload)
    payload["section_source_map"] = [
        SectionSourceMap(**item) for item in payload.get("section_source_map", [])
    ]
    audit = payload.get("anti_ai_self_check")
    if isinstance(audit, dict):
        grades_raw = audit.get("style_guidance_grades", []) or []
        grades = [
            StyleGuidanceGrade(
                bullet=str(grade.get("bullet", "")),
                followed=bool(grade.get("followed", False)),
                where=str(grade.get("where", "")),
                why_not=str(grade.get("why_not", "")),
            )
            for grade in grades_raw
            if isinstance(grade, dict) and str(grade.get("bullet", "")).strip()
        ]
        # `rule_audit` is the current shape. Tolerate old persisted drafts that
        # still carry `block_audit`/`line_audit` by ignoring them (their top-level
        # hashes still load, and a stale audit is re-run through
        # prepare_anti_ai_audit anyway).
        rule_audit = [
            AntiAISkillRuleAudit(
                rule_id=str(row.get("rule_id", "")),
                rule_text_sha256=str(row.get("rule_text_sha256", "")),
                status=str(row.get("status", "")),
                finding=str(row.get("finding", "")),
                rule_application=str(row.get("rule_application", "")),
                draft_evidence=[
                    {
                        "kind": str(item.get("kind", "")),
                        "reference": str(item.get("reference", "")),
                        "explanation": str(item.get("explanation", "")),
                    }
                    for item in row.get("draft_evidence", []) or []
                    if isinstance(item, dict)
                ],
                whole_essay_evidence=dict(row.get("whole_essay_evidence", {}) or {}),
            )
            for row in audit.get("rule_audit", []) or []
            if isinstance(row, dict)
        ]
        unmet_requirements = [
            AntiAIUnmetRequirement(
                rule_id=str(row.get("rule_id", "")),
                section=str(row.get("section", "")),
                status=str(row.get("status", "")),
                reason=str(row.get("reason", "")),
                risk=str(row.get("risk", "")),
            )
            for row in audit.get("unmet_requirements", []) or []
            if isinstance(row, dict)
        ]
        final_decision_raw = audit.get("final_decision")
        final_decision = None
        if isinstance(final_decision_raw, dict):
            final_decision = AntiAIFinalDecision(
                hard_rules_pass=bool(final_decision_raw.get("hard_rules_pass", False)),
                soft_rules_pass=bool(final_decision_raw.get("soft_rules_pass", False)),
                safe_to_claim_detector_reduction=bool(
                    final_decision_raw.get("safe_to_claim_detector_reduction", False)
                ),
                reason=str(final_decision_raw.get("reason", "")),
            )
        payload["anti_ai_self_check"] = AntiAISelfCheck(
            skill_file=str(audit.get("skill_file", "")),
            skill_sha256=str(audit.get("skill_sha256", "")),
            skill_line_count=int(audit.get("skill_line_count", 0) or 0),
            draft_sha256=str(audit.get("draft_sha256", "")),
            rule_audit=rule_audit,
            paragraph_count=int(audit.get("paragraph_count", 0) or 0),
            paragraph_first_sentences=[
                str(s) for s in audit.get("paragraph_first_sentences", []) or []
            ],
            first_sentence_chain_summarizes_essay=bool(
                audit.get("first_sentence_chain_summarizes_essay", True)
            ),
            paragraphs_under_50_words=int(audit.get("paragraphs_under_50_words", 0) or 0),
            paragraphs_opening_with_topic_sentence=int(
                audit.get("paragraphs_opening_with_topic_sentence", 0) or 0
            ),
            filler_phrases_used=[str(s) for s in audit.get("filler_phrases_used", []) or []],
            significance_inflation_phrases=[
                str(s) for s in audit.get("significance_inflation_phrases", []) or []
            ],
            vague_attributions_used=[
                str(s) for s in audit.get("vague_attributions_used", []) or []
            ],
            concrete_source_handles=[
                str(s) for s in audit.get("concrete_source_handles", []) or []
            ],
            style_guidance_grades=grades,
            self_check_notes=[str(s) for s in audit.get("self_check_notes", []) or []],
            unmet_requirements=unmet_requirements,
            final_decision=final_decision,
        )
    else:
        payload["anti_ai_self_check"] = None
    return EssayDraft(**payload)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, indent=2))
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
