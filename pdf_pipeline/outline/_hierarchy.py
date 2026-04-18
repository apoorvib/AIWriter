"""Shared level-stack helpers for parent_id threading across resolvers."""
from __future__ import annotations


def parent_for(level: int, ancestors: list[tuple[int, str]]) -> str | None:
    """Nearest ancestor id whose level is strictly less than `level`, or None."""
    for anc_level, anc_id in reversed(ancestors):
        if anc_level < level:
            return anc_id
    return None


def push_ancestor(ancestors: list[tuple[int, str]], level: int, entry_id: str) -> None:
    """Drop ancestors at or deeper than `level`, then append the new entry."""
    while ancestors and ancestors[-1][0] >= level:
        ancestors.pop()
    ancestors.append((level, entry_id))
