"""Hard-tier deterministic gates: commit_* rejects output containing patterns
that the anti-AI skill bans regardless of voice (em dashes, tier-1 vocab,
signposting, bad conclusion openers, triplet+contrastive combos, decorative
hyphen pauses).

The deterministic gates fire at commit time so the facade verifies the skill
was actually applied, instead of trusting that the harness honored the system
prompt evenly across the whole draft."""
from __future__ import annotations

from dataclasses import replace

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.drafting.schema import EssayDraft
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import main_agent
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


CLEAN_REWRITE = (
    "Cooling access in rental housing is uneven. The source documents large gaps "
    "between buildings with central air conditioning and buildings without. The "
    "writer treats this as a housing policy question, not a comfort question."
)


def _submit_style_revision(facade: AgentToolFacade, content: str) -> str:
    prepared = facade.prepare_style_revision("job1")
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload={
            "content": content,
            "style_changes": [],
            "preservation_notes": [],
            "known_risks": [],
        },
        producer=main_agent(),
    )
    return str(submitted.data["work_result_id"])


def test_commit_style_revision_accepts_clean_content() -> None:
    """Clean prose must still commit successfully under the new gates."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        result_id = _submit_style_revision(facade, CLEAN_REWRITE)

        committed = facade.commit_style_revision(work_result_id=result_id)

    assert committed.ok is True
    assert committed.data["already_committed"] is False


def test_commit_style_revision_rejects_em_dash() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        em_dash_text = (
            "Cooling access in rental housing is uneven—the source documents large "
            "gaps between buildings with central air conditioning and buildings without."
        )
        result_id = _submit_style_revision(facade, em_dash_text)

        committed = facade.commit_style_revision(work_result_id=result_id)

    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "anti_ai_hard_tier_violation"
    violations = committed.data.get("anti_ai_violations", [])
    rules = {v["rule"] for v in violations}
    assert "em_dash" in rules
    assert committed.next_suggested_tools == ["prepare_style_revision"]


def test_commit_style_revision_rejects_tier1_vocabulary() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        # "leverage" and "robust" are tier-1
        bad_vocab_text = (
            "The author seeks to leverage the source data to build a robust argument "
            "about housing policy and cooling access."
        )
        result_id = _submit_style_revision(facade, bad_vocab_text)

        committed = facade.commit_style_revision(work_result_id=result_id)

    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "anti_ai_hard_tier_violation"
    rules = {v["rule"] for v in committed.data["anti_ai_violations"]}
    assert "tier1_vocabulary" in rules


def test_commit_style_revision_rejects_bad_conclusion_opener() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        bad_conclusion = (
            "Cooling access in rental housing is uneven. The source documents wide "
            "differences between buildings with central air conditioning and those "
            "without.\n\n"
            "In conclusion, cooling access is a housing policy problem and city "
            "policy should treat it as one."
        )
        result_id = _submit_style_revision(facade, bad_conclusion)

        committed = facade.commit_style_revision(work_result_id=result_id)

    assert committed.ok is False
    rules = {v["rule"] for v in committed.data["anti_ai_violations"]}
    assert "bad_conclusion_opener" in rules


def test_commit_style_revision_windowed_rejection_names_offending_windows() -> None:
    """Windowed commits must surface which window(s) failed so the harness can
    re-prepare just the offending windows."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)

        # replace draft with long content to trigger windowing
        previous = facade.stores.draft_store.load_latest("job1")
        paragraph = (
            "Cooling access in rental housing is uneven. The source documents "
            "differences between buildings with and without central air conditioning."
        )
        long_content = "\n\n".join([paragraph] * 80)
        next_version = facade.stores.draft_store.next_version("job1")
        facade.stores.draft_store.save(
            replace(previous, id=f"draft_long_{next_version:03d}", version=next_version, content=long_content)
        )

        prepared = facade.prepare_style_revision("job1")
        parent_id = prepared.data["parent_packet_id"]
        windows = prepared.data["windowing"]["windows"]

        result_ids: list[str] = []
        for window_meta in windows:
            window_packet = facade.prepare_style_revision_window(parent_id, window_meta["index"])
            # window index 1 gets an em dash — should be rejected and named
            window_content = (
                f"Revised window {window_meta['index']}.—with an em dash."
                if window_meta["index"] == 1
                else f"Revised window {window_meta['index']}. Plain prose."
            )
            submitted = facade.submit_work_result(
                str(window_packet.data["work_packet_id"]),
                payload={
                    "content": window_content,
                    "style_changes": [],
                    "preservation_notes": [],
                    "known_risks": [],
                },
                producer=main_agent(),
            )
            result_ids.append(str(submitted.data["work_result_id"]))

        committed = facade.commit_style_revision(work_result_ids=result_ids)

    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "anti_ai_hard_tier_violation"
    offending = committed.data.get("offending_window_indices", [])
    assert 1 in offending
    assert 0 not in offending  # window 0 is clean
    assert committed.next_suggested_tools == ["prepare_style_revision_window"]


def test_commit_revision_rejects_em_dash_in_revised_draft() -> None:
    """The validation-driven revision path (commit_revision) must apply the same
    hard-tier gates as commit_style_revision."""
    from essay_writer.agent_tools.facade import AgentToolFacade
    from tests.agent_tools.test_outline_draft_validation_tools import (
        _seed_job_through_draft,
        _validation_report,
    )

    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        previous = facade.stores.draft_store.load_latest("job1")
        # write a validation report so prepare_revision can run
        validation = _validation_report(previous.id)
        facade.stores.validation_store.save("job1", validation)

        prepared = facade.prepare_revision("job1")
        em_dash_text = (
            "Cooling access in rental housing is uneven—the source documents large "
            "gaps. The argument needs more direct engagement with sources."
        )
        submitted = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload={
                "content": em_dash_text,
                "section_source_map": [
                    {
                        "section_id": "section_001",
                        "heading": "Introduction",
                        "note_ids": ["note_001"],
                        "source_ids": ["src1"],
                    }
                ],
                "bibliography_candidates": ["Uploaded Source."],
                "known_weak_spots": [],
                "anti_ai_self_check": {
                    "paragraph_count": 1,
                    "paragraph_first_sentences": [],
                    "first_sentence_chain_summarizes_essay": False,
                    "paragraphs_under_50_words": 1,
                    "paragraphs_opening_with_topic_sentence": 0,
                    "filler_phrases_used": [],
                    "significance_inflation_phrases": [],
                    "vague_attributions_used": [],
                    "concrete_source_handles": [],
                    "style_guidance_grades": [],
                    "self_check_notes": [],
                },
            },
            producer=main_agent(),
        )
        committed = facade.commit_revision(
            work_result_id=str(submitted.data["work_result_id"])
        )

    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "anti_ai_hard_tier_violation"
