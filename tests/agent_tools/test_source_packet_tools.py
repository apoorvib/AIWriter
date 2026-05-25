from __future__ import annotations

import json
from pathlib import Path

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.research_planning.schema import ResearchPlan
from essay_writer.sources.access_schema import SourceLocator
from essay_writer.sources.schema import SourceIngestionConfig
from pdf_pipeline.models import DocumentExtractionResult, PageText
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import ExplodingLLMClient
from tests.agent_tools.test_source_materialization import FakeExtractor


def test_search_source_returns_locator_payloads_without_full_text() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp)
        facade.ingest_source_file(tmp / "source.pdf", source_id="src1")

        result = facade.search_source("src1", "cooling access", limit=3)

    assert result.ok is True
    locators = result.data["locators"]
    assert isinstance(locators, list)
    assert locators
    assert len(locators) <= 3
    assert locators[0]["locator_type"] == "chunk"
    payload_text = json.dumps(locators)
    assert "Cooling access evidence appears in this source text" not in payload_text
    assert "text" not in locators[0]


def test_read_source_packet_resolves_one_locator_without_persisting_bundle() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp)
        facade.ingest_source_file(tmp / "source.pdf", source_id="src1")
        search = facade.search_source("src1", "cooling access", limit=1)

        result = facade.read_source_packet(search.data["locators"][0], max_chars=40)

    assert result.ok is True
    packet = result.data["source_packet"]
    assert packet["source_id"] == "src1"
    assert packet["locator"]["locator_type"] == "chunk"
    assert "Cooling access" in packet["text"]
    assert len(str(packet["text"])) <= 40
    assert any("truncated" in warning.lower() for warning in packet["warnings"])


def test_read_source_packet_rejects_invalid_max_chars() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp)
        facade.ingest_source_file(tmp / "source.pdf", source_id="src1")
        search = facade.search_source("src1", "cooling access", limit=1)

        zero = facade.read_source_packet(search.data["locators"][0], max_chars=0)
        string_value = facade.read_source_packet(
            search.data["locators"][0],
            max_chars="40",  # type: ignore[arg-type]
        )

    assert zero.ok is False
    assert zero.error is not None
    assert zero.error.code == "invalid_max_chars"
    assert string_value.ok is False
    assert string_value.error is not None
    assert string_value.error.code == "invalid_max_chars"


def test_read_source_packet_rejects_invalid_locator_payload() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.read_source_packet({"source_id": "src1", "locator_type": "bad"})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_locator_payload"


def test_resolve_source_requests_persists_source_packet_bundle() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp)
        facade.ingest_source_file(tmp / "source.pdf", source_id="src1")
        search = facade.search_source("src1", "cooling access", limit=1)

        result = facade.resolve_source_requests(
            job_id="job1",
            locators=[search.data["locators"][0]],
        )
        bundle_id = str(result.data["source_packet_bundle_id"])
        bundle = facade.work_store.load_source_packet_bundle(bundle_id)
        fetched = facade.get_source_packet_bundle(bundle_id)

    assert result.ok is True
    assert bundle.scope == "job:job1"
    assert bundle.packet_payloads
    assert bundle.packet_payloads[0]["source_id"] == "src1"
    assert fetched.ok is True
    assert fetched.data["source_packet_bundle"]["source_packet_bundle_id"] == bundle_id


def test_resolve_source_requests_returns_error_for_empty_packets_without_bundle() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp)
        facade.ingest_source_file(tmp / "source.pdf", source_id="src1")

        result = facade.resolve_source_requests(
            job_id="job1",
            locators=[
                {
                    "source_id": "src1",
                    "locator_type": "search",
                    "query": "termthatdoesnotexist",
                }
            ],
        )
        saved_bundles = list(facade.work_store.source_packet_bundles_dir.glob("*.json"))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "source_packets_empty"
    assert result.next_suggested_tools == ["search_source", "read_source_packet"]
    assert "source_packet_bundle_id" not in result.data
    assert saved_bundles == []


def test_resolve_source_requests_uses_research_plan_id() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp)
        facade.ingest_source_file(tmp / "source.pdf", source_id="src1")
        search = facade.search_source("src1", "cooling access", limit=1)
        facade.stores.research_plan_store.save(
            ResearchPlan(
                id="research_plan_v001",
                job_id="job1",
                selected_topic_id="topic1",
                version=1,
                research_question="How does cooling access matter?",
                source_requirements=[],
                uploaded_source_priorities=[],
                expected_evidence_categories=[],
                source_requests=[
                    SourceLocator(
                        source_id="src1",
                        locator_type="chunk",
                        chunk_id=str(search.data["locators"][0]["chunk_id"]),
                        query="cooling access",
                    )
                ],
            )
        )

        result = facade.resolve_source_requests(
            job_id="job1",
            research_plan_id="research_plan_v001",
        )

    assert result.ok is True
    assert result.data["source_packet_bundle_id"]
    assert result.data["artifact_refs"]["research_plan_id"] == "research_plan_v001"


def test_resolve_source_requests_with_agent_run_attaches_recovery_refs() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade_with_source(tmp)
        facade.ingest_source_file(tmp / "source.pdf", source_id="src1")
        search = facade.search_source("src1", "cooling access", limit=1)
        # job1 is not pre-created as a workflow job; start_agent_run cannot
        # inherit a phase. resolve_source_requests can be called ad-hoc with
        # explicit locators, so opt out of strict phase gating for this
        # test by starting the run in legacy mode.
        run = facade.start_agent_run(
            objective="Resolve source packets.",
            job_id="job1",
            phase_mode="legacy",
        )
        agent_run_id = str(run.data["agent_run_id"])

        result = facade.resolve_source_requests(
            job_id="job1",
            locators=[search.data["locators"][0]],
            agent_run_id=agent_run_id,
        )
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert result.ok is True
    assert recovered.data["artifact_refs"]["job_id"] == "job1"
    assert recovered.data["artifact_refs"]["source_packet_bundle_id"] == result.data["source_packet_bundle_id"]
    assert recovered.data["next_suggested_tools"] == ["prepare_research_notes"]


def test_resolve_source_requests_requires_locators_or_research_plan() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.resolve_source_requests(job_id="job1")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "source_requests_required"
    assert result.next_suggested_tools == ["search_source", "create_research_plan"]


def test_get_source_packet_bundle_missing_returns_structured_error() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.get_source_packet_bundle("missing-bundle")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "source_packet_bundle_not_found"


def _facade_with_source(tmp: Path) -> AgentToolFacade:
    source_path = tmp / "source.pdf"
    source_path.write_bytes(b"%PDF-fake")
    text = (
        "Cooling access evidence appears in this source text. "
        "Urban heat policy depends on neighborhood cooling centers and shade."
    )
    return AgentToolFacade.from_data_dir(
        tmp / "data",
        source_ingestion_config=SourceIngestionConfig(
            min_text_chars_per_page=5,
            chunk_target_chars=200,
            chunk_overlap_chars=0,
        ),
        document_reader=FakeExtractor(
            DocumentExtractionResult(
                source_path=str(source_path),
                page_count=1,
                pages=[PageText(1, text, len(text), "pypdf")],
            )
        ),
        llm_guard=ExplodingLLMClient(),
    )
