"""Tests for the proof-of-attention challenge (Gap 3).

When the facade is built with ``enforce_attention_challenge=True`` (the
production default), every model-reasoning packet has a token appended
to its ``system_prompt`` and recorded as ``system_prompt_challenge``.
``submit_work_result`` rejects any payload that does not echo the token,
catching the case where the orchestrator never read the supplied
system prompt.

These tests construct the facade with enforcement ON explicitly, which
overrides the conftest default-off.
"""
from __future__ import annotations

from essay_writer.agent_tools.facade import AgentToolFacade

from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import main_agent
from tests.agent_tools.test_job_and_recovery_tools import (
    _seed_materialized_source,
    _seed_task_spec,
)


def _enforced_facade(tmp) -> AgentToolFacade:
    return AgentToolFacade.from_data_dir(
        tmp / "data",
        enforce_attention_challenge=True,
    )


def _task_spec_payload() -> dict[str, object]:
    # A minimal-but-valid task-spec payload. Field set mirrors what the
    # task-spec schema requires elsewhere in the suite.
    return {
        "assignment_title": "Test",
        "course_context": None,
        "essay_type": "explanatory",
        "academic_level": None,
        "target_length": 1000,
        "length_unit": "words",
        "citation_style": None,
        "prompt_options": [],
        "selected_prompt": "Explain something.",
        "required_sources": [],
        "allowed_sources": [],
        "forbidden_sources": [],
        "topic_scope": None,
        "required_materials": [],
        "required_claims_or_questions": [],
        "required_structure": [],
        "formatting_requirements": [],
        "rubric": [],
        "grading_criteria": [],
        "submission_requirements": [],
        "professor_constraints": [],
        "missing_information": [],
        "ambiguities": [],
        "risk_flags": [],
        "adversarial_flags": [],
        "ignored_ai_directives": [],
        "extracted_checklist": [],
        "blocking_questions": [],
        "nonblocking_warnings": [],
        "confidence_by_field": {},
    }


def test_packet_carries_challenge_when_enforced() -> None:
    """A prepared packet's system_prompt ends with the ATTENTION CHECK
    footer and the packet records the token."""
    with LocalAgentTempDir() as tmp:
        facade = _enforced_facade(tmp)
        prepared = facade.prepare_task_spec(raw_text="Explain something.")
        packet = facade.work_store.load_packet(str(prepared.data["work_packet_id"]))
    assert packet.system_prompt_challenge is not None
    assert packet.system_prompt_challenge in packet.system_prompt
    assert "ATTENTION CHECK" in packet.system_prompt
    # The returned system_prompt (what the LLM sees) includes the token.
    assert packet.system_prompt_challenge in str(prepared.data["system_prompt"])


def test_submit_without_token_is_rejected() -> None:
    """A schema-valid payload that omits the attention token is rejected
    with system_prompt_not_honored."""
    with LocalAgentTempDir() as tmp:
        facade = _enforced_facade(tmp)
        prepared = facade.prepare_task_spec(raw_text="Explain something.")
        result = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_task_spec_payload(),  # no token anywhere
            producer=main_agent(),
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "system_prompt_not_honored"


def test_submit_with_token_is_accepted() -> None:
    """Echoing the token in a free-text field satisfies the gate."""
    with LocalAgentTempDir() as tmp:
        facade = _enforced_facade(tmp)
        prepared = facade.prepare_task_spec(raw_text="Explain something.")
        packet = facade.work_store.load_packet(str(prepared.data["work_packet_id"]))
        token = packet.system_prompt_challenge

        payload = _task_spec_payload()
        # Echo the token in a free-text field (mirrors what a compliant
        # orchestrator does after reading the ATTENTION CHECK line).
        payload["nonblocking_warnings"] = [f"attention:{token}"]

        result = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=payload,
            producer=main_agent(),
        )
    assert result.ok is True


def test_enforcement_off_does_not_inject_or_require_token() -> None:
    """With enforcement off (the test-suite default), packets carry no
    challenge and submissions are not gated on it."""
    with LocalAgentTempDir() as tmp:
        # Note: conftest forces enforce_attention_challenge=False here.
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        prepared = facade.prepare_task_spec(raw_text="Explain something.")
        packet = facade.work_store.load_packet(str(prepared.data["work_packet_id"]))
        assert packet.system_prompt_challenge is None
        result = facade.submit_work_result(
            str(prepared.data["work_packet_id"]),
            payload=_task_spec_payload(),
            producer=main_agent(),
        )
    assert result.ok is True


def test_challenge_applies_across_stages() -> None:
    """The challenge is applied to a non-task-spec packet too (source
    card), proving the chokepoint covers all prepare_* stages."""
    with LocalAgentTempDir() as tmp:
        facade = _enforced_facade(tmp)
        _seed_task_spec(facade, "task1", ["src1"])
        _seed_materialized_source(facade, "src1")
        # Do NOT seed a source card; prepare_source_card reuses an
        # existing card and returns no packet when one is present.
        prepared = facade.prepare_source_card("src1", reuse_existing=False)
        packet = facade.work_store.load_packet(str(prepared.data["work_packet_id"]))
    assert packet.system_prompt_challenge is not None
    assert "ATTENTION CHECK" in packet.system_prompt
