from __future__ import annotations

import pytest

from essay_writer.agent_tools.schemas import WorkProducer
from essay_writer.writing.facade import WritingToolFacade
from essay_writer.writing.schema import WriteMode
from tests.agent_tools._tmp import LocalAgentTempDir


def _facade(tmp, *, enforce=False) -> WritingToolFacade:
    return WritingToolFacade.from_data_dir(tmp, enforce_attention_challenge=enforce)


def _brief_payload(**overrides) -> dict:
    payload = {
        "mode": "immediate",
        "purpose": "Announce the launch",
        "audience": "customers",
        "deliverables": [
            {
                "deliverable_id": "d1",
                "format": "email",
                "objective": "Announce the launch",
                "audience": "customers",
                "constraints": [],
                "selected_skill_ids": ["email"],
            }
        ],
        "selected_skill_ids": ["email"],
        "research_needed": False,
        "research_reasons": [],
        "assumptions": [],
        "blocking_questions": [],
    }
    payload.update(overrides)
    return payload


def _run_brief(facade, run_id, payload):
    prepared = facade.prepare_writing_brief(run_id)
    submitted = facade.submit_writing_result(
        str(prepared.data["work_packet_id"]), payload, producer=WorkProducer(type="main_agent")
    )
    return facade.commit_writing_brief(str(submitted.data["work_result_id"]))


def test_start_writing_run_persists_and_reports_brief_next() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        started = facade.start_writing_run("Write a launch email")
        assert started.ok
        run_id = str(started.data["writing_run_id"])
        assert started.data["progress"]["next_required_step"] == "brief"
        # Recovery reconstructs the same ledger from persisted state.
        recovered = facade.recover_writing_run(run_id)
    assert recovered.ok
    assert recovered.data["progress"]["next_required_step"] == "brief"


def test_start_writing_run_rejects_unknown_skill() -> None:
    with LocalAgentTempDir() as tmp:
        result = _facade(tmp).start_writing_run(
            "Write an email", include_skill_ids=["invented-skill"]
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unknown_writing_skill"


def test_explicit_mode_and_research_overrides_survive_classification() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        started = facade.start_writing_run(
            "Write a detailed post", mode="detailed", research_policy="required"
        )
        run_id = str(started.data["writing_run_id"])
        # The model classifies it as immediate with no research; overrides win.
        committed = _run_brief(
            facade, run_id, _brief_payload(mode="immediate", research_needed=False)
        )
    assert committed.ok
    assert committed.data["mode"] == WriteMode.DETAILED.value
    assert committed.data["research_needed"] is True


def test_commit_brief_resolves_and_defaults_anti_ai_skill() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = str(facade.start_writing_run("Write a launch email").data["writing_run_id"])
        committed = _run_brief(facade, run_id, _brief_payload())
    assert committed.ok
    ids = {item["skill_id"] for item in committed.data["selected_skills"]}
    assert {"email", "anti-ai-detection"} <= ids
    assert committed.data["progress"]["next_required_step"] == "draft"


def test_commit_brief_rejects_invented_skill_id() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = str(facade.start_writing_run("Write a launch email").data["writing_run_id"])
        payload = _brief_payload(selected_skill_ids=["email", "made-up-skill"])
        prepared = facade.prepare_writing_brief(run_id)
        submitted = facade.submit_writing_result(
            str(prepared.data["work_packet_id"]), payload,
            producer=WorkProducer(type="main_agent"),
        )
        committed = facade.commit_writing_brief(str(submitted.data["work_result_id"]))
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "unknown_writing_skill"


def test_blocking_questions_persist_needs_input_without_advancing() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = str(facade.start_writing_run("Write an email").data["writing_run_id"])
        payload = _brief_payload(blocking_questions=["Who is the recipient?"])
        committed = _run_brief(facade, run_id, payload)
        assert committed.ok
        assert committed.data["progress"]["status"] == "needs_input"
        assert committed.data["progress"]["requires_human"] is True
        # Answering unblocks and points back at the brief step.
        answered = facade.answer_writing_questions(run_id, "The recipient is Maya.")
    assert answered.ok
    assert answered.data["progress"]["next_required_step"] == "brief"
    assert answered.data["progress"]["requires_human"] is False


def test_submit_rejects_payload_missing_required_fields() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = str(facade.start_writing_run("Write an email").data["writing_run_id"])
        prepared = facade.prepare_writing_brief(run_id)
        bad = _brief_payload()
        del bad["purpose"]
        result = facade.submit_writing_result(
            str(prepared.data["work_packet_id"]), bad,
            producer=WorkProducer(type="main_agent"),
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "work_result_payload_invalid"


def test_attention_challenge_enforced_on_writing_packets() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp, enforce=True)
        run_id = str(facade.start_writing_run("Write an email").data["writing_run_id"])
        prepared = facade.prepare_writing_brief(run_id)
        packet = facade.work_store.load_packet(str(prepared.data["work_packet_id"]))
        assert packet.system_prompt_challenge is not None
        # Missing token is rejected.
        rejected = facade.submit_writing_result(
            packet.work_packet_id, _brief_payload(),
            producer=WorkProducer(type="main_agent"),
        )
        assert rejected.ok is False
        assert rejected.error is not None
        assert rejected.error.code == "system_prompt_not_honored"
        # Echoing the token satisfies the gate.
        payload = _brief_payload(notes=[f"attention:{packet.system_prompt_challenge}"])
        accepted = facade.submit_writing_result(
            packet.work_packet_id, payload, producer=WorkProducer(type="main_agent")
        )
    assert accepted.ok


def test_run_not_found_is_reported() -> None:
    with LocalAgentTempDir() as tmp:
        result = _facade(tmp).get_writing_progress("nope")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "writing_run_not_found"
