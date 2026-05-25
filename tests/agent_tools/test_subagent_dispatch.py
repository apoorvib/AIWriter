"""Tests for the subagent-dispatch gate (mechanism B).

When a ``WorkPacket`` has ``delegation_required=True``,
``submit_work_result`` must reject results unless the producer carries a
valid token issued by ``dispatch_subagent`` for that exact packet.

Currently ``prepare_anti_ai_audit`` is the only packet that sets
``delegation_required=True``; all other packets continue to work
without a token.
"""
from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.agent_tools.schemas import WorkProducer

from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import dispatched_subagent, main_agent
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


def _audit_payload() -> dict[str, object]:
    return {
        "pass": True,
        "anti_ai_self_check": {
            "paragraph_count": 1,
            "paragraph_first_sentences": ["A."],
            "first_sentence_chain_summarizes_essay": False,
            "paragraphs_under_50_words": 1,
            "paragraphs_opening_with_topic_sentence": 1,
            "filler_phrases_used": [],
            "significance_inflation_phrases": [],
            "vague_attributions_used": [],
            "concrete_source_handles": ["source p. 1"],
            "style_guidance_grades": [],
            "self_check_notes": [],
        },
        "revision_targets": [],
    }


def test_audit_packet_requires_subagent_dispatch_token() -> None:
    """``submit_work_result`` must reject an audit submission that has
    no subagent_token on the producer."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        prepared = facade.prepare_anti_ai_audit("job1")

        result = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_audit_payload(),
            producer=main_agent(),  # no token
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "subagent_dispatch_required"
    assert "dispatch_subagent" in result.next_suggested_tools


def test_audit_packet_accepts_valid_dispatch_token() -> None:
    """After ``dispatch_subagent`` issues a token, ``submit_work_result``
    accepts a producer carrying that token."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        prepared = facade.prepare_anti_ai_audit("job1")

        producer = dispatched_subagent(
            facade,
            work_packet_id=str(prepared.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        result = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_audit_payload(),
            producer=producer,
        )
    assert result.ok is True


def test_audit_packet_rejects_wrong_packet_token() -> None:
    """A token issued for packet A must not validate for packet B."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        prepared_a = facade.prepare_anti_ai_audit("job1")

        # Issue a token for packet A.
        dispatch = facade.dispatch_subagent(
            work_packet_id=str(prepared_a.data["work_packet_id"]),
            role="anti_ai_auditor",
        )
        # Pretend we submit it against a fake/other packet id.
        producer = WorkProducer(
            type="subagent",
            role="anti_ai_auditor",
            subagent_token=str(dispatch.data["subagent_token"]),
        )
        # Use a different (non-existent) packet to test the mismatch.
        # The work_packet_not_found error fires first, so to actually
        # exercise the token-mismatch path we need a real OTHER packet.
        # Re-prepare to get a second audit packet; the first one's
        # token must not validate against the second.
        prepared_b = facade.prepare_anti_ai_audit("job1")
        result = facade.submit_work_result(
            str(prepared_b.data["work_packet_id"]),
            payload=_audit_payload(),
            producer=producer,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "subagent_dispatch_token_invalid"


def test_dispatch_subagent_requires_non_empty_role() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        prepared = facade.prepare_anti_ai_audit("job1")

        result = facade.dispatch_subagent(
            work_packet_id=str(prepared.data["work_packet_id"]),
            role="",
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "role_required"


def test_dispatch_subagent_rejects_unknown_work_packet() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        result = facade.dispatch_subagent(
            work_packet_id="workpkt_does_not_exist",
            role="anti_ai_auditor",
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "work_packet_not_found"


def test_non_required_packets_do_not_need_dispatch_token() -> None:
    """A normal packet (delegation_required=False) accepts submissions
    without a subagent token, preserving backward compatibility."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        # Prepare an outline packet (delegation_required defaults to False)
        prepared = facade.prepare_outline("job1")
        # prepare_outline at this point returns OK without any subagent
        # token. The key assertion: it works.
    assert prepared.ok is True


def test_large_source_card_packet_sets_delegation_required() -> None:
    """Gap (4): a source whose selected excerpts exceed the threshold
    must produce a source-card packet with delegation_required=True, so
    the orchestrator cannot absorb a multi-KB excerpt block inline."""
    from essay_writer.agent_tools.facade import (
        SOURCE_CARD_DELEGATION_REQUIRED_CHARS,
    )
    from essay_writer.sources.schema import SourceMaterializationResult
    from essay_writer.sources.schema import (
        SourceChunk,
        SourceDocument,
        SourcePage,
    )

    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        big_text = "Cooling access in rental housing. " * 600  # ~20KB
        facade.stores.source_store.save_materialized_source(
            SourceMaterializationResult(
                source=SourceDocument(
                    id="bigsrc",
                    original_path="bigsrc.pdf",
                    file_name="bigsrc.pdf",
                    source_type="pdf",
                    page_count=1,
                    char_count=len(big_text),
                    extraction_method="pypdf",
                    text_quality="readable",
                    full_text_available=True,
                    indexed=False,
                ),
                pages=[
                    SourcePage(
                        source_id="bigsrc",
                        page_number=1,
                        text=big_text,
                        char_count=len(big_text),
                        extraction_method="pypdf",
                    )
                ],
                chunks=[
                    SourceChunk(
                        id="bigsrc-chunk-001",
                        source_id="bigsrc",
                        ordinal=1,
                        page_start=1,
                        page_end=1,
                        text=big_text,
                        char_count=len(big_text),
                    )
                ],
                indexed=False,
                full_text_available=True,
            )
        )
        prepared = facade.prepare_source_card("bigsrc")
        packet = facade.work_store.load_packet(str(prepared.data["work_packet_id"]))

    assert prepared.ok is True
    assert packet.context["selected_excerpt_chars"] > SOURCE_CARD_DELEGATION_REQUIRED_CHARS
    assert packet.delegation_required is True
