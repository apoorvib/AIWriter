"""Skip-token store used by mechanism (D).

A skip token records that the orchestrator explicitly opted out of an
otherwise-required stage (currently only writing-style calibration).
The downstream tool that would otherwise enforce the stage accepts
either the canonical artifact id (e.g. writing-style content id) or a
valid skip token.

Tokens are scoped to a job_id so a skip in one job does not bypass a
gate in another. Each token carries the orchestrator-supplied reason
so the decision is auditable.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field, asdict
from pathlib import Path

from essay_writer.agent_tools.id_utils import timestamp_id
from essay_writer.agent_tools.json_io import read_json, write_json_atomic
from essay_writer.agent_tools.schemas import utc_now_iso


SCOPE_WRITING_STYLE = "writing_style"


@dataclass(frozen=True)
class SkipToken:
    """A skip token issued by ``skip_<stage>(reason=...)`` tools."""

    token: str
    scope: str
    job_id: str
    reason: str
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SkipToken":
        return cls(
            token=str(data["token"]),
            scope=str(data["scope"]),
            job_id=str(data["job_id"]),
            reason=str(data["reason"]),
            created_at=str(data.get("created_at", utc_now_iso())),
        )


class SkipTokenStore:
    """File-backed store for skip tokens.

    Tokens live as one JSON file per token under ``<base_dir>``. Lookups
    are by ``(scope, job_id, token)`` so a token cannot be reused
    across jobs or stages.
    """

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def issue(self, *, scope: str, job_id: str, reason: str) -> SkipToken:
        if not reason or not reason.strip():
            raise ValueError("skip-token reason must be a non-empty string")
        raw_token = secrets.token_urlsafe(16)
        token_id = timestamp_id("skip", scope, job_id, raw_token[:8])
        record = SkipToken(
            token=token_id,
            scope=scope,
            job_id=job_id,
            reason=reason.strip(),
        )
        write_json_atomic(self.base_dir / f"{token_id}.json", asdict(record))
        return record

    def load(self, token: str) -> SkipToken:
        path = self.base_dir / f"{token}.json"
        return SkipToken.from_dict(read_json(path))

    def validate(self, *, token: str, scope: str, job_id: str) -> bool:
        """Return True iff ``token`` exists and matches ``scope`` + ``job_id``."""
        try:
            record = self.load(token)
        except (KeyError, FileNotFoundError):
            return False
        return record.scope == scope and record.job_id == job_id


__all__ = [
    "SCOPE_WRITING_STYLE",
    "SkipToken",
    "SkipTokenStore",
]
