from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


ExportFormat = Literal["markdown"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class FinalEssayExport:
    id: str
    job_id: str
    draft_id: str
    validation_report_id: str
    export_format: ExportFormat
    content: str
    source_map: list[dict[str, object]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
