from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade

from ._tmp import LocalAgentTempDir


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
    assert "prepare_source_card" not in result.data["currently_callable_tools"]
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
