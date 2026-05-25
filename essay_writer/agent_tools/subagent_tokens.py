"""Subagent dispatch tokens (mechanism B).

When a ``WorkPacket`` has ``delegation_required=True``, ``submit_work_result``
will reject results that are not accompanied by a valid subagent
dispatch token. The token is issued by ``dispatch_subagent(packet_id,
role)`` and recorded server-side. This makes "run the audit inline in
the main orchestrator" structurally impossible for packets that the
harness wants delegated.

The token only proves the orchestrator *said* it dispatched a subagent;
it does not prove the subagent actually ran. That is fine for the
threat model (forgetful self-orchestration) and out of scope for the
malicious-orchestrator threat model.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field, asdict
from pathlib import Path

from essay_writer.agent_tools.id_utils import timestamp_id
from essay_writer.agent_tools.json_io import read_json, write_json_atomic
from essay_writer.agent_tools.schemas import utc_now_iso


@dataclass(frozen=True)
class SubagentDispatchToken:
    """A token issued for a single delegated work packet."""

    token: str
    work_packet_id: str
    role: str
    created_at: str = field(default_factory=utc_now_iso)
    consumed: bool = False
    consumed_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SubagentDispatchToken":
        return cls(
            token=str(data["token"]),
            work_packet_id=str(data["work_packet_id"]),
            role=str(data["role"]),
            created_at=str(data.get("created_at", utc_now_iso())),
            consumed=bool(data.get("consumed", False)),
            consumed_at=(
                str(data["consumed_at"])
                if data.get("consumed_at") is not None
                else None
            ),
        )


class SubagentTokenStore:
    """File-backed store for subagent dispatch tokens.

    Tokens live as one JSON file per token under ``<base_dir>``. Lookups
    are by ``(token, work_packet_id)`` so a token cannot be reused
    across packets. A token may be consumed once.
    """

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def issue(
        self,
        *,
        work_packet_id: str,
        role: str,
    ) -> SubagentDispatchToken:
        if not role or not role.strip():
            raise ValueError("subagent dispatch role must be a non-empty string")
        raw_token = secrets.token_urlsafe(16)
        token_id = timestamp_id("subagent", work_packet_id, raw_token[:8])
        record = SubagentDispatchToken(
            token=token_id,
            work_packet_id=work_packet_id,
            role=role.strip(),
        )
        write_json_atomic(self.base_dir / f"{token_id}.json", asdict(record))
        return record

    def load(self, token: str) -> SubagentDispatchToken:
        path = self.base_dir / f"{token}.json"
        return SubagentDispatchToken.from_dict(read_json(path))

    def validate(
        self,
        *,
        token: str,
        work_packet_id: str,
    ) -> bool:
        """Return True iff ``token`` exists and matches ``work_packet_id``.

        Does NOT check consumed-state; allows multiple submit retries with
        the same token (idempotent submission).
        """
        try:
            record = self.load(token)
        except (KeyError, FileNotFoundError):
            return False
        return record.work_packet_id == work_packet_id

    def consume(
        self,
        *,
        token: str,
        work_packet_id: str,
    ) -> SubagentDispatchToken | None:
        """Mark the token as consumed. Returns the updated record, or
        ``None`` if the token does not match. Idempotent."""
        try:
            record = self.load(token)
        except (KeyError, FileNotFoundError):
            return None
        if record.work_packet_id != work_packet_id:
            return None
        if record.consumed:
            return record
        updated = SubagentDispatchToken(
            token=record.token,
            work_packet_id=record.work_packet_id,
            role=record.role,
            created_at=record.created_at,
            consumed=True,
            consumed_at=utc_now_iso(),
        )
        write_json_atomic(self.base_dir / f"{record.token}.json", asdict(updated))
        return updated


__all__ = [
    "SubagentDispatchToken",
    "SubagentTokenStore",
]
