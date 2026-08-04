from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable

from essay_writer.drafting.anti_ai_skill import (
    ANTI_AI_SKILL_DOCUMENT,
    ANTI_AI_SKILL_SHA256,
)
from essay_writer.writing.schema import SkillSelection


class UnknownWritingSkillError(ValueError):
    pass


@dataclass(frozen=True)
class WritingSkillDocument:
    skill_id: str
    version: str
    kind: str
    description: str
    formats: tuple[str, ...]
    triggers: tuple[str, ...]
    priority: int
    content: str
    sha256: str


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


class WritingSkillRegistry:
    def __init__(self, documents: Iterable[WritingSkillDocument]) -> None:
        self._documents: dict[str, WritingSkillDocument] = {}
        for document in documents:
            if document.skill_id in self._documents:
                raise ValueError(f"duplicate writing skill id: {document.skill_id}")
            self._documents[document.skill_id] = document

    @classmethod
    def default(cls) -> "WritingSkillRegistry":
        documents: list[WritingSkillDocument] = []
        root = resources.files("essay_writer.writing").joinpath("skills")
        for directory in sorted(root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir():
                continue
            manifest_path = directory.joinpath("skill.json")
            skill_path = directory.joinpath("SKILL.md")
            if not manifest_path.is_file() or not skill_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            content = skill_path.read_text(encoding="utf-8").strip()
            documents.append(
                WritingSkillDocument(
                    skill_id=str(manifest["id"]),
                    version=str(manifest["version"]),
                    kind=str(manifest["kind"]),
                    description=str(manifest["description"]),
                    formats=tuple(str(item) for item in manifest.get("formats", [])),
                    triggers=tuple(str(item) for item in manifest.get("triggers", [])),
                    priority=int(manifest.get("priority", 100)),
                    content=content,
                    sha256=_sha256(content),
                )
            )
        documents.append(
            WritingSkillDocument(
                skill_id="anti-ai-detection",
                version="1",
                kind="quality",
                description="Reduce generic machine-written prose patterns.",
                formats=(),
                triggers=("human", "anti-ai", "natural voice"),
                priority=50,
                content=ANTI_AI_SKILL_DOCUMENT,
                sha256=ANTI_AI_SKILL_SHA256,
            )
        )
        return cls(documents)

    def ids(self) -> list[str]:
        return sorted(self._documents)

    def get(self, skill_id: str) -> WritingSkillDocument:
        try:
            return self._documents[skill_id]
        except KeyError as exc:
            raise UnknownWritingSkillError(
                f"unknown writing skill {skill_id!r}; available: {', '.join(self.ids())}"
            ) from exc

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "id": item.skill_id,
                "version": item.version,
                "kind": item.kind,
                "description": item.description,
                "formats": list(item.formats),
                "triggers": list(item.triggers),
            }
            for item in sorted(self._documents.values(), key=lambda value: value.skill_id)
        ]


def resolve_skill_stack(
    *,
    registry: WritingSkillRegistry,
    format_id: str,
    model_selected_ids: list[str],
    include_ids: list[str],
    exclude_ids: list[str],
) -> list[SkillSelection]:
    for skill_id in [*model_selected_ids, *include_ids, *exclude_ids]:
        registry.get(skill_id)

    available_formats = {
        format_name: document.skill_id
        for document in (registry.get(skill_id) for skill_id in registry.ids())
        for format_name in document.formats
    }
    format_skill_id = available_formats.get(format_id, "general")
    selected_ids = set(model_selected_ids)
    selected_ids.add(format_skill_id)
    selected_ids.update(include_ids)
    if "anti-ai-detection" not in exclude_ids:
        selected_ids.add("anti-ai-detection")
    selected_ids.difference_update(exclude_ids)
    if format_skill_id != "general":
        selected_ids.discard("general")

    documents = sorted(
        (registry.get(skill_id) for skill_id in selected_ids),
        key=lambda item: (item.priority, item.skill_id),
    )
    return [
        SkillSelection(
            skill_id=document.skill_id,
            version=document.version,
            sha256=document.sha256,
            reason=(
                "explicitly requested"
                if document.skill_id in include_ids
                else "selected for requested format"
                if document.skill_id == format_skill_id
                else "default quality skill"
                if document.skill_id == "anti-ai-detection"
                else "selected by writing brief"
            ),
        )
        for document in documents
    ]


def compose_skill_prompt(
    registry: WritingSkillRegistry,
    selections: list[SkillSelection],
) -> str:
    sections = [
        "SKILL PRECEDENCE\n"
        "Safety and factual integrity > explicit user instructions > format constraints > "
        "authentic user voice > format hard rules > anti-AI hard rules > soft guidance. "
        "Format skills may override conflicting soft anti-AI guidance only."
    ]
    for selection in selections:
        document = registry.get(selection.skill_id)
        if document.version != selection.version or document.sha256 != selection.sha256:
            raise ValueError(f"stale writing skill selection: {selection.skill_id}")
        sections.append(
            f"SKILL {document.skill_id} v{document.version} {document.sha256}\n"
            f"{document.content}"
        )
    return "\n\n---\n\n".join(sections)


__all__ = [
    "UnknownWritingSkillError",
    "WritingSkillDocument",
    "WritingSkillRegistry",
    "compose_skill_prompt",
    "resolve_skill_stack",
]
