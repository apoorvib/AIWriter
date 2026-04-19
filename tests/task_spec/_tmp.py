from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4


class LocalTempDir:
    def __init__(self) -> None:
        self.path = Path("test-output") / f"task-spec-{uuid4().hex}"

    def __enter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=False)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
