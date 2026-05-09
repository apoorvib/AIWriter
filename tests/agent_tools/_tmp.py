from __future__ import annotations

import shutil
import uuid
from pathlib import Path


class LocalAgentTempDir:
    def __init__(self) -> None:
        self.path = Path("test-output") / f"agent-tools-{uuid.uuid4().hex}"

    def __enter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=False)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
