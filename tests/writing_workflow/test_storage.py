from __future__ import annotations

from dataclasses import replace

import pytest

from essay_writer.writing.schema import (
    DeliverableSpec, SkillSelection, WriteMode, WritingBrief, WritingDraft,
    WritingOutput, WritingRun,
)
from essay_writer.writing.storage import WritingStores
from tests.agent_tools._tmp import LocalAgentTempDir


def _skill(skill_id: str = "email") -> SkillSelection:
    return SkillSelection(skill_id, "1", "sha256:abc")


def _brief(run_id: str = "run1", version: int = 1) -> WritingBrief:
    return WritingBrief(
        brief_id=f"brief-{version}", writing_run_id=run_id, version=version,
        mode=WriteMode.IMMEDIATE, purpose="Send an update", audience="customers",
        deliverables=[DeliverableSpec("email", "email", "Send update")],
        selected_skills=[_skill()],
    )


def _draft(run_id: str, deliverable_id: str, version: int) -> WritingDraft:
    return WritingDraft(
        draft_id=f"draft-{deliverable_id}-{version}", writing_run_id=run_id,
        deliverable_id=deliverable_id, version=version,
        content=f"Draft {version} for {deliverable_id}",
        selected_skills=[_skill(deliverable_id)],
    )


def test_run_roundtrip_and_update() -> None:
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        created = stores.runs.create(WritingRun("run1", "Write an email"))
        updated = stores.runs.update(replace(created, brief_id="brief-1"))
        loaded = stores.runs.load("run1")
    assert loaded.brief_id == "brief-1"
    assert updated.updated_at >= created.updated_at


def test_run_create_rejects_duplicate_id() -> None:
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        stores.runs.create(WritingRun("run1", "Write an email"))
        with pytest.raises(FileExistsError):
            stores.runs.create(WritingRun("run1", "Write another email"))


def test_versioned_brief_store_does_not_overwrite() -> None:
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        stores.briefs.save(_brief(version=1))
        stores.briefs.save(_brief(version=2))
        assert stores.briefs.next_version("run1") == 3
        assert stores.briefs.load_latest("run1").version == 2
        with pytest.raises(FileExistsError):
            stores.briefs.save(_brief(version=2))


def test_draft_versions_are_isolated_by_deliverable() -> None:
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        stores.drafts.save(_draft("run1", "email", 1))
        stores.drafts.save(_draft("run1", "linkedin", 1))
        assert stores.drafts.next_version("run1", "email") == 2
        assert stores.drafts.load_latest("run1", "linkedin").deliverable_id == "linkedin"


def test_output_save_is_idempotent_for_identical_payload() -> None:
    output = WritingOutput(
        output_id="output-1", writing_run_id="run1",
        deliverables=[_draft("run1", "email", 1)], selected_skills=[_skill()],
    )
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        assert stores.outputs.save(output) == stores.outputs.save(output)


def test_output_rejects_same_id_with_different_payload() -> None:
    first = WritingOutput(
        output_id="output-1", writing_run_id="run1",
        deliverables=[_draft("run1", "email", 1)], selected_skills=[_skill()],
    )
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        stores.outputs.save(first)
        with pytest.raises(FileExistsError, match="different payload"):
            stores.outputs.save(replace(first, warnings=["different"]))
