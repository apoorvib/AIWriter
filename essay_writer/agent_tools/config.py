from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentToolConfig:
    base_dir: Path | str
    work_dir: Path | str | None = None
    run_dir: Path | str | None = None

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

    @classmethod
    def from_base_dir(cls, base_dir: Path | str) -> "AgentToolConfig":
        return cls(base_dir=base_dir)
