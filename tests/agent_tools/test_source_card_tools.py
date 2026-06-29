from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.agent_tools.schemas import DelegationHint, PromptBlock, WorkPacket, WorkProducer
from essay_writer.sources.schema import SourceCard, SourceIngestionConfig
from pdf_pipeline.models import DocumentExtractionResult, PageText
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.test_source_materialization import FakeExtractor


def test_prepare_submit_commit_source_card_persists_card_and_commit_link() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp, "Urban heat and cooling access evidence.")
        run = facade.start_agent_run(objective="Ingest one source.")
        agent_run_id = str(run.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        facade.ingest_source_file(
            str(tmp / "source.pdf"),
            source_id="src1",
            agent_run_id=agent_run_id,
        )

        prepared = facade.prepare_source_card("src1", agent_run_id=agent_run_id)
        packet_id = str(prepared.data["work_packet_id"])
        submitted = facade.submit_work_result(
            packet_id,
            payload=_valid_payload(),
            producer=WorkProducer(type="main_agent", role="orchestrator", name=None),
            agent_run_id=agent_run_id,
        )
        committed = facade.commit_source_card(
            work_result_id=str(submitted.data["work_result_id"]),
            agent_run_id=agent_run_id,
        )

        card = facade.stores.source_store.load_source_card("src1")
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)
        commits = facade.work_store.list_commits(scope="source:src1", stage="source_card")

    assert prepared.ok is True
    assert prepared.data["commit_tool"] == "commit_source_card"
    assert prepared.data["source_card_status"] == "pending"
    assert prepared.data["next_suggested_tools"] == ["submit_work_result"]
    assert prepared.data["delegation"]["recommended"] is True
    assert "source-card generation" in str(prepared.data["delegation"]["reason"])
    assert submitted.ok is True
    assert submitted.data["next_suggested_tools"] == ["commit_source_card"]
    assert committed.ok is True
    assert committed.data["source_card_status"] == "committed"
    assert committed.data["already_committed"] is False
    assert card.title == "Urban Heat Source"
    assert commits[0].artifact_refs["source_id"] == "src1"
    assert commits[0].artifact_refs["source_card_id"] == "src1"
    assert "src1" in recovered.data["artifact_refs"]["source_ids"]
    assert "src1" in recovered.data["artifact_refs"]["source_card_ids"]


def test_commit_source_card_retry_returns_already_committed() -> None:
    with LocalAgentTempDir() as tmp:
        facade, work_result_id = seeded_source_card_work_result(tmp)

        first = facade.commit_source_card(work_result_id=work_result_id)
        second = facade.commit_source_card(work_result_id=work_result_id)

    assert first.ok is True
    assert second.ok is True
    assert first.data["already_committed"] is False
    assert second.data["already_committed"] is True


def test_direct_source_card_commit_retry_returns_already_committed() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_prepared_source(tmp)

        first = facade.commit_source_card(source_id="src1", payload=_valid_payload())
        second = facade.commit_source_card(source_id="src1", payload=_valid_payload())
        commit_count = len(facade.work_store.list_commits(scope="source:src1", stage="source_card"))

    assert first.ok is True
    assert second.ok is True
    assert first.data["already_committed"] is False
    assert second.data["already_committed"] is True
    assert commit_count == 1


def test_direct_source_card_commit_validation_error_uses_commit_tool_name() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_prepared_source(tmp)

        result = facade.commit_source_card(
            source_id="src1",
            payload={**_valid_payload(), "warnings": [123]},
        )

    assert result.ok is False
    assert result.tool_name == "commit_source_card"
    assert result.error is not None
    assert result.error.code == "work_result_payload_invalid"


def test_submit_source_card_rejects_invalid_payload_before_persistence() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_prepared_source(tmp)
        prepared = facade.prepare_source_card("src1")
        packet_id = str(prepared.data["work_packet_id"])

        result = facade.submit_work_result(
            packet_id,
            payload={**_valid_payload(), "unexpected": "not allowed"},
            producer=WorkProducer(type="main_agent", role="orchestrator", name=None),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "work_result_payload_invalid"
    assert facade.work_store.list_results() == []


@pytest.mark.skipif(
    importlib.util.find_spec("jsonschema") is not None,
    reason=(
        "This test exercises the no-jsonschema fallback validator, which only "
        "runs when jsonschema is absent. With jsonschema installed the malformed "
        "schema raises SchemaError -> work_result_schema_invalid instead. "
        "Pre-existing environment assumption, unrelated to the enforcement work."
    ),
)
def test_submit_rejects_malformed_additional_properties_without_jsonschema() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        packet = facade.work_store.save_packet(
            WorkPacket(
                work_packet_id="workpkt_bad_schema",
                stage="source_card",
                scope="source:src1",
                instructions="Return JSON.",
                system_prompt="System.",
                prompt_blocks=[PromptBlock(text="{}", cacheable=False)],
                response_schema={
                    "type": "object",
                    "additionalProperties": "not-a-supported-fallback-shape",
                },
                context={},
                artifact_refs={"source_id": "src1"},
                commit_tool="commit_source_card",
                delegation=DelegationHint(),
            )
        )

        result = facade.submit_work_result(
            packet.work_packet_id,
            payload={"title": "Bad schema"},
            producer=WorkProducer(type="main_agent", role="orchestrator", name=None),
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "work_result_schema_validator_unavailable"
    assert "`.[agent-tools]`" in result.error.message
    assert facade.work_store.list_results() == []


def test_prepare_source_card_reuses_existing_card_without_new_packet() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_prepared_source(tmp)
        facade.stores.source_store.save_source_card(
            "src1",
            SourceCard(
                source_id="src1",
                title="Existing Source Card",
                source_type="pdf",
                page_count=1,
                extraction_method="pypdf",
                brief_summary="Already prepared.",
            ),
        )

        result = facade.prepare_source_card("src1", reuse_existing=True)

    assert result.ok is True
    assert result.data["source_card_status"] == "committed"
    assert "work_packet_id" not in result.data
    assert facade.work_store.list_packets(scope="source:src1") == []


def test_prepare_source_card_reuses_existing_card_and_updates_run_refs() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_prepared_source(tmp)
        run = facade.start_agent_run(objective="Use an existing card.")
        agent_run_id = str(run.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        facade.stores.source_store.save_source_card(
            "src1",
            SourceCard(
                source_id="src1",
                title="Existing Source Card",
                source_type="pdf",
                page_count=1,
                extraction_method="pypdf",
                brief_summary="Already prepared.",
            ),
        )

        result = facade.prepare_source_card(
            "src1",
            agent_run_id=agent_run_id,
            reuse_existing=True,
        )
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert result.ok is True
    assert result.data["source_card_status"] == "committed"
    assert facade.work_store.list_packets(scope="source:src1") == []
    assert "src1" in recovered.data["artifact_refs"]["source_ids"]
    assert "src1" in recovered.data["artifact_refs"]["source_card_ids"]
    assert recovered.data["next_suggested_tools"] == ["prepare_task_spec"]


def test_committing_two_source_cards_accumulates_run_recovery_refs() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp, "Urban heat and cooling access evidence.")
        run = facade.start_agent_run(objective="Use two sources.")
        agent_run_id = str(run.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        facade.ingest_source_file(tmp / "source.pdf", source_id="src1", agent_run_id=agent_run_id)
        second_path = tmp / "source2.pdf"
        second_path.write_bytes(b"%PDF-fake-2")
        facade.ingest_source_file(second_path, source_id="src2", agent_run_id=agent_run_id)

        first = _prepare_submit_commit(facade, source_id="src1", agent_run_id=agent_run_id)
        second = _prepare_submit_commit(
            facade,
            source_id="src2",
            agent_run_id=agent_run_id,
            payload={**_valid_payload(), "title": "Second Source"},
        )
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert first.ok is True
    assert second.ok is True
    assert recovered.data["artifact_refs"]["source_ids"] == ["src1", "src2"]
    assert recovered.data["artifact_refs"]["source_card_ids"] == ["src1", "src2"]


def test_prepare_source_card_missing_agent_run_does_not_create_packet() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_prepared_source(tmp)

        result = facade.prepare_source_card("src1", agent_run_id="missing-run")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "agent_run_not_found"
    assert facade.work_store.list_packets(scope="source:src1") == []


def seeded_source_card_work_result(tmp: Path) -> tuple[AgentToolFacade, str]:
    facade = _facade_with_prepared_source(tmp)
    prepared = facade.prepare_source_card("src1")
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload=_valid_payload(),
        producer=WorkProducer(type="main_agent", role="orchestrator", name=None),
    )
    return facade, str(submitted.data["work_result_id"])


def _prepare_submit_commit(
    facade: AgentToolFacade,
    *,
    source_id: str,
    agent_run_id: str,
    payload: dict[str, object] | None = None,
):
    prepared = facade.prepare_source_card(source_id, agent_run_id=agent_run_id)
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload=payload or _valid_payload(),
        producer=WorkProducer(type="main_agent", role="orchestrator", name=None),
        agent_run_id=agent_run_id,
    )
    return facade.commit_source_card(
        work_result_id=str(submitted.data["work_result_id"]),
        agent_run_id=agent_run_id,
    )


def _facade_with_prepared_source(tmp: Path) -> AgentToolFacade:
    facade = _facade_with_source(tmp, "Urban heat and cooling access evidence.")
    result = facade.ingest_source_file(str(tmp / "source.pdf"), source_id="src1")
    assert result.ok is True
    return facade


def _facade_with_source(tmp: Path, text: str) -> AgentToolFacade:
    source_path = tmp / "source.pdf"
    source_path.write_bytes(b"%PDF-fake")
    return AgentToolFacade.from_data_dir(
        tmp / "data",
        source_ingestion_config=SourceIngestionConfig(min_text_chars_per_page=5),
        document_reader=FakeExtractor(
            DocumentExtractionResult(
                source_path=str(source_path),
                page_count=1,
                pages=[PageText(1, text, len(text), "pypdf")],
            )
        ),
    )


def _valid_payload() -> dict[str, object]:
    return {
        "title": "Urban Heat Source",
        "brief_summary": "Evidence about urban heat and cooling access.",
        "key_topics": ["urban heat", "cooling"],
        "useful_for_topic_ideation": ["Supports essays about heat policy."],
        "notable_sections": ["Opening page defines the issue."],
        "limitations": [],
        "citation_metadata": {"file_name": "source.pdf"},
        "warnings": [],
    }
