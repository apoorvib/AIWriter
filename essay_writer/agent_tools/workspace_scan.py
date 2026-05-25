"""Workspace scanning helpers.

The harness can surface files that the user has already dropped into
the conventional ``inputs/writing_style/`` directory so the orchestrator
discovers them without being told. Mechanism (D) uses this to make the
writing-style gate informative: if the directory has samples, the
error response lists them as candidates for ``ingest_writing_style_sample``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WRITING_STYLE_DIRNAME = "inputs/writing_style"
SUPPORTED_WRITING_STYLE_SUFFIXES = (".md", ".txt", ".pdf", ".docx", ".rtf")


@dataclass(frozen=True)
class DiscoveredSample:
    """A writing-style sample file discovered on disk."""

    path: str
    name: str
    suffix: str
    size_bytes: int


def _resolve_writing_style_dir(workspace_root: Path | None) -> Path:
    if workspace_root is None:
        workspace_root = Path.cwd()
    return Path(workspace_root) / WRITING_STYLE_DIRNAME


def scan_writing_style_directory(
    workspace_root: Path | str | None = None,
) -> list[DiscoveredSample]:
    """Return all writing-style sample files in the conventional directory.

    Returns an empty list when the directory does not exist. Hidden files
    (starting with a dot) and files with unsupported suffixes are skipped.
    Results are sorted by filename for stable output.
    """
    if isinstance(workspace_root, str):
        workspace_root = Path(workspace_root)
    target = _resolve_writing_style_dir(workspace_root)
    if not target.exists() or not target.is_dir():
        return []
    discovered: list[DiscoveredSample] = []
    for child in sorted(target.iterdir(), key=lambda p: p.name):
        if not child.is_file():
            continue
        if child.name.startswith("."):
            continue
        suffix = child.suffix.lower()
        if suffix not in SUPPORTED_WRITING_STYLE_SUFFIXES:
            continue
        try:
            size = child.stat().st_size
        except OSError:
            continue
        discovered.append(
            DiscoveredSample(
                path=str(child.resolve()),
                name=child.name,
                suffix=suffix,
                size_bytes=size,
            )
        )
    return discovered


__all__ = [
    "DiscoveredSample",
    "SUPPORTED_WRITING_STYLE_SUFFIXES",
    "WRITING_STYLE_DIRNAME",
    "scan_writing_style_directory",
]
