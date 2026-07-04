from __future__ import annotations

import pytest

from essay_writer.writing.skills import (
    UnknownWritingSkillError,
    WritingSkillRegistry,
    compose_skill_prompt,
    resolve_skill_stack,
)


def test_registry_discovers_initial_format_skills_and_anti_ai_adapter() -> None:
    registry = WritingSkillRegistry.default()

    assert set(registry.ids()) >= {
        "general",
        "email",
        "text-message",
        "linkedin",
        "blog",
        "anti-ai-detection",
    }
    assert registry.get("email").sha256.startswith("sha256:")
    assert "required inputs" in registry.get("email").content.lower()


def test_default_stack_adds_format_and_anti_ai() -> None:
    selected = resolve_skill_stack(
        registry=WritingSkillRegistry.default(),
        format_id="email",
        model_selected_ids=["email"],
        include_ids=[],
        exclude_ids=[],
    )

    assert [item.skill_id for item in selected] == ["anti-ai-detection", "email"]


def test_explicit_exclusion_removes_anti_ai_default() -> None:
    selected = resolve_skill_stack(
        registry=WritingSkillRegistry.default(),
        format_id="email",
        model_selected_ids=["email"],
        include_ids=[],
        exclude_ids=["anti-ai-detection"],
    )

    assert [item.skill_id for item in selected] == ["email"]


def test_general_is_used_only_as_format_fallback() -> None:
    selected = resolve_skill_stack(
        registry=WritingSkillRegistry.default(),
        format_id="unknown-format",
        model_selected_ids=[],
        include_ids=[],
        exclude_ids=["anti-ai-detection"],
    )

    assert [item.skill_id for item in selected] == ["general"]


def test_unknown_explicit_skill_is_rejected_not_ignored() -> None:
    with pytest.raises(UnknownWritingSkillError, match="invented-skill"):
        resolve_skill_stack(
            registry=WritingSkillRegistry.default(),
            format_id="email",
            model_selected_ids=["email"],
            include_ids=["invented-skill"],
            exclude_ids=[],
        )


def test_prompt_composition_includes_exact_skill_hashes_and_precedence() -> None:
    registry = WritingSkillRegistry.default()
    selections = resolve_skill_stack(
        registry=registry,
        format_id="linkedin",
        model_selected_ids=["linkedin"],
        include_ids=[],
        exclude_ids=[],
    )

    prompt = compose_skill_prompt(registry, selections)

    assert "SKILL PRECEDENCE" in prompt
    assert registry.get("linkedin").sha256 in prompt
    assert registry.get("anti-ai-detection").content in prompt
