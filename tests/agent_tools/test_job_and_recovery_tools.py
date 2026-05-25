from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.agent_tools.schemas import DelegationHint, PromptBlock, WorkPacket
from essay_writer.sources.schema import (
    SourceCard,
    SourceChunk,
    SourceDocument,
    SourceMaterializationResult,
    SourcePage,
)
from essay_writer.task_spec.schema import TaskSpecification

from ._tmp import LocalAgentTempDir
from .helpers import main_agent


def test_get_harness_instructions_returns_mode_warning_and_tools() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.get_harness_instructions()

    assert result.ok is True
    assert result.mode == "agent_tool_no_api"
    assert "Do not call Pipeline Mode" in result.data["instructions"]
    assert "prepare_source_card" in result.data["available_tools"]
    assert "Do not call Pipeline Mode tools." in result.data["must_remember"]
    assert "start_agent_run" in result.data["currently_callable_tools"]
    assert "prepare_source_card" in result.data["currently_callable_tools"]
    assert "submit_work_result" in result.data["currently_callable_tools"]
    assert "commit_source_card" in result.data["currently_callable_tools"]
    assert "create_job_from_artifacts" in result.data["currently_callable_tools"]
    assert "get_job_summary" in result.data["currently_callable_tools"]
    assert "list_sources" in result.data["currently_callable_tools"]
    assert "get_source_card" in result.data["currently_callable_tools"]
    assert "list_work_packets" in result.data["currently_callable_tools"]
    assert "get_work_packet" in result.data["currently_callable_tools"]
    assert "list_work_results" in result.data["currently_callable_tools"]
    assert "get_work_result" in result.data["currently_callable_tools"]
    assert "prepare_source_card" in result.data["planned_workflow_tools"]


def test_start_and_recover_agent_run() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        started = facade.start_agent_run(
            objective="Create an essay from uploaded sources.",
            user_constraints=["Do not use app API credits."],
        )
        agent_run_id = str(started.data["agent_run_id"])
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert started.ok is True
    assert recovered.ok is True
    assert recovered.data["agent_run_id"] == agent_run_id
    assert "Do not call Pipeline Mode tools." in recovered.data["must_remember"]


def test_get_agent_run_state_returns_started_run_status_and_next_tools() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="Create an essay from uploaded sources.")

        state = facade.get_agent_run_state(agent_run_id=str(started.data["agent_run_id"]))

    assert state.ok is True
    assert state.data["status"] == "active"
    assert state.data["current_phase"] == "bootstrap"
    assert state.data["next_suggested_tools"] == ["ingest_source_file", "prepare_source_card"]


def test_checkpoint_agent_run_updates_recovery_state_and_next_tools() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="Create an essay from uploaded sources.")
        agent_run_id = str(started.data["agent_run_id"])

        checkpoint = facade.checkpoint_agent_run(
            agent_run_id=agent_run_id,
            current_phase="source_cards",
            decision="Sources are ready.",
            next_suggested_tools=["prepare_source_card", "submit_work_result"],
        )
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert checkpoint.ok is True
    assert checkpoint.data["current_phase"] == "source_cards"
    assert checkpoint.data["next_suggested_tools"] == [
        "prepare_source_card",
        "submit_work_result",
    ]
    assert recovered.data["current_phase"] == "source_cards"
    assert recovered.data["next_suggested_tools"] == [
        "prepare_source_card",
        "submit_work_result",
    ]


def test_list_agent_runs_returns_created_run() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(
            objective="Create an essay from uploaded sources.",
            job_id="job1",
        )

        listed = facade.list_agent_runs(job_id="job1")

    assert listed.ok is True
    assert listed.data["runs"][0]["agent_run_id"] == started.data["agent_run_id"]
    assert "Do not call Pipeline Mode tools." in listed.data["must_remember"]


def test_checkpoint_can_unblock_agent_run() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="Create an essay from uploaded sources.")
        agent_run_id = str(started.data["agent_run_id"])

        blocked = facade.checkpoint_agent_run(
            agent_run_id=agent_run_id,
            current_phase="source_cards",
            blocked_on="Need source files.",
            next_suggested_tools=[],
        )
        resumed = facade.checkpoint_agent_run(
            agent_run_id=agent_run_id,
            current_phase="source_cards",
            decision="Source files received.",
            next_suggested_tools=["prepare_source_card"],
        )
        state = facade.get_agent_run_state(agent_run_id=agent_run_id)

    assert blocked.ok is True
    assert resumed.ok is True
    assert state.data["status"] == "active"
    assert state.data["next_suggested_tools"] == ["prepare_source_card"]


def test_missing_agent_run_returns_tool_error() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.recover_agent_run(agent_run_id="missing-run")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "agent_run_not_found"


def test_facade_bootstrap_uses_stable_local_store_paths(monkeypatch) -> None:
    monkeypatch.setenv("ESSAY_LAZY_OCR_TIER", "invalid-tier")
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

    assert facade.stores.validation_store.root.name == "validations"


def test_create_job_from_artifacts_requires_committed_source_cards() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_materialized_source(facade, "src1")

        result = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "source_card_missing"
    assert result.next_suggested_tools == ["prepare_source_card"]


def test_create_job_from_artifacts_missing_task_spec_suggests_prepare_task_spec() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")

        result = facade.create_job_from_artifacts(
            task_spec_id="missing-task",
            source_ids=["src1"],
            job_id="job1",
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "task_spec_not_found"
    assert result.next_suggested_tools == ["prepare_task_spec"]


def test_create_job_from_artifacts_missing_source_text_suggests_ingest_source_file() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src-missing-text"])

        result = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src-missing-text"],
            job_id="job1",
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "source_text_artifacts_missing"
    assert result.next_suggested_tools == ["ingest_source_file"]


def test_create_job_from_artifacts_requires_source_ids_and_does_not_create_job() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", [])

        result = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=[],
            job_id="job1",
        )
        missing_job = facade.get_job_summary("job1")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "source_ids_required"
    assert result.next_suggested_tools == ["ingest_source_file", "prepare_source_card"]
    assert missing_job.ok is False
    assert missing_job.error is not None
    assert missing_job.error.code == "job_not_found"


def test_create_job_from_artifacts_creates_job_and_updates_recovery_refs() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")
        run = facade.start_agent_run(objective="Create an essay.")
        agent_run_id = str(run.data["agent_run_id"])

        # Writing-style gate (mechanism D): tests that are not exercising
        # voice calibration must explicitly skip it.
        skip = facade.skip_writing_style_calibration(
            job_id="job1",
            reason="unit test does not exercise voice calibration",
            agent_run_id=agent_run_id,
        )
        skip_token = str(skip.data["skip_token"])

        created = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
            writing_style_skip_token=skip_token,
        )
        summary = facade.get_job_summary("job1")
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert created.ok is True
    assert created.data["job_id"] == "job1"
    assert created.data["status"] == "sources_ready"
    assert created.data["current_stage"] == "topic_ideation"
    assert created.data["task_spec_id"] == "task1"
    assert created.data["source_ids"] == ["src1"]
    assert created.data["already_existing"] is False
    assert created.data["artifact_refs"]["job_id"] == "job1"
    assert created.data["next_suggested_tools"] == ["prepare_topics"]
    assert summary.ok is True
    assert summary.data["job"]["status"] == "sources_ready"
    assert summary.data["job"]["current_stage"] == "topic_ideation"
    assert summary.data["next_suggested_tools"] == ["prepare_topics"]
    assert recovered.data["artifact_refs"]["job_id"] == "job1"
    assert recovered.data["artifact_refs"]["task_spec_id"] == "task1"
    assert recovered.data["artifact_refs"]["source_ids"] == ["src1"]
    assert recovered.data["next_suggested_tools"] == ["prepare_topics"]


def test_create_job_from_artifacts_is_idempotent_and_rejects_conflicting_job_id() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_task_spec(facade, "task2", ["src1"])
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")

        first = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
        )
        retry = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
        )
        conflict = facade.create_job_from_artifacts(
            task_spec_id="task2",
            source_ids=["src1"],
            job_id="job1",
        )

    assert first.ok is True
    assert retry.ok is True
    assert retry.data["already_existing"] is True
    assert conflict.ok is False
    assert conflict.error is not None
    assert conflict.error.code == "job_id_conflict"


def test_create_job_from_artifacts_idempotent_retry_with_agent_run_keeps_recovery_refs() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")
        run = facade.start_agent_run(objective="Create an essay.")
        agent_run_id = str(run.data["agent_run_id"])

        # Writing-style gate skip (mechanism D).
        skip = facade.skip_writing_style_calibration(
            job_id="job1",
            reason="unit test does not exercise voice calibration",
            agent_run_id=agent_run_id,
        )
        skip_token = str(skip.data["skip_token"])

        first = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
            writing_style_skip_token=skip_token,
        )
        retry = facade.create_job_from_artifacts(
            task_spec_id="task1",
            source_ids=["src1"],
            job_id="job1",
            agent_run_id=agent_run_id,
        )
        recovered = facade.recover_agent_run(agent_run_id=agent_run_id)

    assert first.ok is True
    assert retry.ok is True
    assert retry.data["already_existing"] is True
    assert recovered.data["artifact_refs"]["job_id"] == "job1"
    assert recovered.data["artifact_refs"]["task_spec_id"] == "task1"
    assert recovered.data["artifact_refs"]["source_ids"] == ["src1"]
    assert recovered.data["committed_artifact_refs"]["job_id"] == "job1"
    assert recovered.data["committed_artifact_refs"]["task_spec_id"] == "task1"
    assert recovered.data["committed_artifact_refs"]["source_ids"] == ["src1"]
    assert recovered.data["next_suggested_tools"] == ["prepare_topics"]


def test_read_tools_return_compact_summaries_and_explicit_full_objects() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_materialized_source(facade, "src1")
        _seed_source_card(facade, "src1")
        packet = facade.work_store.save_packet(
            WorkPacket(
                work_packet_id="workpkt_job1_topic_001",
                stage="topic_ideation",
                scope="job:job1",
                instructions="Create topic candidates.",
                system_prompt="System prompt with details.",
                prompt_blocks=[PromptBlock(text="Long prompt text.", cacheable=False)],
                response_schema={"type": "object", "additionalProperties": True},
                context={"job_id": "job1"},
                artifact_refs={"job_id": "job1"},
                commit_tool="commit_topics",
                delegation=DelegationHint(recommended=False),
            )
        )
        result = facade.work_store.submit_result(
            packet.work_packet_id,
            payload={"large_payload": "full result text"},
            producer=main_agent(),
        )

        sources = facade.list_sources()
        card = facade.get_source_card("src1")
        packets = facade.list_work_packets(scope="job:job1")
        fetched_packet = facade.get_work_packet(packet.work_packet_id)
        results = facade.list_work_results(scope="job:job1")
        fetched_result = facade.get_work_result(result.work_result_id)

    assert sources.ok is True
    assert sources.data["sources"] == [
        {
            "source_id": "src1",
            "file_name": "source-src1.pdf",
            "type": "pdf",
            "page_count": 1,
            "char_count": 41,
            "full_text_available": True,
            "indexed": False,
            "source_card_status": "committed",
        }
    ]
    assert card.ok is True
    assert card.data["source_card"]["source_id"] == "src1"
    assert card.data["source_card"]["title"] == "Source src1"
    assert packets.ok is True
    assert packets.data["work_packets"][0]["work_packet_id"] == packet.work_packet_id
    assert "prompt_blocks" not in packets.data["work_packets"][0]
    assert "system_prompt" not in packets.data["work_packets"][0]
    assert fetched_packet.ok is True
    assert fetched_packet.data["work_packet"]["prompt_blocks"][0]["text"] == "Long prompt text."
    assert results.ok is True
    assert results.data["work_results"][0]["work_result_id"] == result.work_result_id
    assert "payload" not in results.data["work_results"][0]
    assert fetched_result.ok is True
    assert fetched_result.data["work_result"]["payload"] == {"large_payload": "full result text"}


def test_missing_read_artifacts_return_structured_errors() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        missing_job = facade.get_job_summary("missing-job")
        missing_card = facade.get_source_card("missing-source")
        missing_packet = facade.get_work_packet("missing-packet")
        missing_result = facade.get_work_result("missing-result")

    assert missing_job.ok is False
    assert missing_job.error is not None
    assert missing_job.error.code == "job_not_found"
    assert missing_card.ok is False
    assert missing_card.error is not None
    assert missing_card.error.code == "source_card_not_found"
    assert missing_card.next_suggested_tools == ["prepare_source_card"]
    assert missing_packet.ok is False
    assert missing_packet.error is not None
    assert missing_packet.error.code == "work_packet_not_found"
    assert missing_result.ok is False
    assert missing_result.error is not None
    assert missing_result.error.code == "work_result_not_found"


def _seed_task_spec(
    facade: AgentToolFacade,
    task_id: str,
    source_document_ids: list[str],
) -> None:
    facade.stores.task_store.save(
        TaskSpecification(
            id=task_id,
            version=1,
            raw_text="Write an essay.",
            source_document_ids=source_document_ids,
            assignment_title="Essay",
        )
    )


def _seed_materialized_source(facade: AgentToolFacade, source_id: str) -> None:
    text = "Cooling access appears in rental housing."
    facade.stores.source_store.save_materialized_source(
        SourceMaterializationResult(
            source=SourceDocument(
                id=source_id,
                original_path=f"{source_id}.pdf",
                file_name=f"source-{source_id}.pdf",
                source_type="pdf",
                page_count=1,
                char_count=len(text),
                extraction_method="pypdf",
                text_quality="readable",
                full_text_available=True,
                indexed=False,
            ),
            pages=[
                SourcePage(
                    source_id=source_id,
                    page_number=1,
                    text=text,
                    char_count=len(text),
                    extraction_method="pypdf",
                )
            ],
            chunks=[
                SourceChunk(
                    id=f"{source_id}-chunk-001",
                    source_id=source_id,
                    ordinal=1,
                    page_start=1,
                    page_end=1,
                    text=text,
                    char_count=len(text),
                )
            ],
            indexed=False,
            full_text_available=True,
        )
    )


def _seed_source_card(facade: AgentToolFacade, source_id: str) -> None:
    facade.stores.source_store.save_source_card(
        source_id,
        SourceCard(
            source_id=source_id,
            title=f"Source {source_id}",
            source_type="pdf",
            page_count=1,
            extraction_method="pypdf",
            brief_summary="Evidence about cooling access.",
            key_topics=["cooling"],
            useful_for_topic_ideation=["Housing policy angle."],
        ),
    )
