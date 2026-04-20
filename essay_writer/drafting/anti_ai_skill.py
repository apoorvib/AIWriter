from __future__ import annotations

from pathlib import Path


def load_anti_ai_skill_document() -> str:
    path = Path(__file__).resolve().parents[2] / "anti-ai-detection-SKILL.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(f"Anti-AI skill document is missing: {path}") from exc


ANTI_AI_SKILL_DOCUMENT = load_anti_ai_skill_document()
