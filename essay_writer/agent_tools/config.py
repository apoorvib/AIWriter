from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# Stale-harness check thresholds (mechanism C). Tunable here so tests can
# override locally if needed.
STALE_HARNESS_AFTER_PHASE_ADVANCES = 6
STALE_HARNESS_AFTER_SECONDS = 1800  # 30 minutes


@dataclass(frozen=True)
class AgentToolConfig:
    base_dir: Path | str
    work_dir: Path | str | None = None
    run_dir: Path | str | None = None
    skip_token_dir: Path | str | None = None
    subagent_token_dir: Path | str | None = None

    def __post_init__(self) -> None:
        base_dir = Path(self.base_dir)
        object.__setattr__(self, "base_dir", base_dir)
        object.__setattr__(
            self,
            "work_dir",
            Path(self.work_dir) if self.work_dir is not None else base_dir / "agent_work",
        )
        object.__setattr__(
            self,
            "run_dir",
            Path(self.run_dir) if self.run_dir is not None else base_dir / "agent_runs",
        )
        object.__setattr__(
            self,
            "skip_token_dir",
            Path(self.skip_token_dir)
            if self.skip_token_dir is not None
            else base_dir / "agent_skip_tokens",
        )
        object.__setattr__(
            self,
            "subagent_token_dir",
            Path(self.subagent_token_dir)
            if self.subagent_token_dir is not None
            else base_dir / "agent_subagent_tokens",
        )

    @classmethod
    def from_base_dir(cls, base_dir: Path | str) -> "AgentToolConfig":
        return cls(base_dir=base_dir)
