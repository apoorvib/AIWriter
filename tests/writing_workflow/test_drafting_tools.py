from __future__ import annotations

from essay_writer.agent_tools.schemas import WorkProducer
from essay_writer.writing.facade import WritingToolFacade
from tests.agent_tools._tmp import LocalAgentTempDir


def _facade(tmp) -> WritingToolFacade:
    return WritingToolFacade.from_data_dir(tmp, enforce_attention_challenge=False)


def _submit(facade, packet_id, payload):
    return facade.submit_writing_result(
        str(packet_id), payload, producer=WorkProducer(type="main_agent")
    )


def _start(facade, *, mode="immediate", research_policy="auto", exclude=None):
    started = facade.start_writing_run(
        "Write a launch email", mode=mode, research_policy=research_policy,
        exclude_skill_ids=exclude or [],
    )
    return str(started.data["writing_run_id"])


def _brief_payload(**overrides) -> dict:
    payload = {
        "mode": "immediate",
        "purpose": "Announce the launch",
        "audience": "customers",
        "deliverables": [
            {
                "deliverable_id": "d1", "format": "email",
                "objective": "Announce", "audience": "customers",
                "constraints": [], "selected_skill_ids": ["email"],
            }
        ],
        "selected_skill_ids": [],
        "research_needed": False,
        "research_reasons": [],
        "assumptions": ["reader knows the product"],
        "blocking_questions": [],
    }
    payload.update(overrides)
    return payload


def _commit_brief(facade, run_id, payload=None):
    prepared = facade.prepare_writing_brief(run_id)
    submitted = _submit(facade, prepared.data["work_packet_id"], payload or _brief_payload())
    return facade.commit_writing_brief(str(submitted.data["work_result_id"]))


def _research_payload() -> dict:
    return {
        "sources": [{
            "source_id": "s1", "title": "Report", "url": "https://example.com/a",
            "publisher": "Ex", "published_at": "2026-01-01", "accessed_at": "2026-07-05",
        }],
        "facts": [{
            "fact_id": "f1", "claim": "Market grew", "source_ids": ["s1"],
            "confidence": "high", "short_quote": None,
        }],
        "conflicts": [], "warnings": [],
    }


def _commit_research(facade, run_id):
    prepared = facade.prepare_writing_research(run_id)
    submitted = _submit(facade, prepared.data["work_packet_id"], _research_payload())
    return facade.commit_writing_research(str(submitted.data["work_result_id"]))


def _plan_payload(**overrides) -> dict:
    payload = {"sections": ["intro", "body"], "key_points": ["kp"], "research_fact_ids": []}
    payload.update(overrides)
    return payload


def _commit_plan(facade, run_id, deliverable_id, payload=None):
    prepared = facade.prepare_writing_plan(run_id, deliverable_id)
    submitted = _submit(facade, prepared.data["work_packet_id"], payload or _plan_payload())
    return facade.commit_writing_plan(str(submitted.data["work_result_id"]))


def _draft_payload(**overrides) -> dict:
    payload = {
        "content": "Hello, we launched.",
        "assumptions": ["reader knows the product"],
        "research_fact_ids": [],
        "self_check": ["read aloud once"],
    }
    payload.update(overrides)
    return payload


def _commit_draft(facade, run_id, deliverable_id, payload=None):
    prepared = facade.prepare_writing_draft(run_id, deliverable_id)
    submitted = _submit(facade, prepared.data["work_packet_id"], payload or _draft_payload())
    return facade.commit_writing_draft(str(submitted.data["work_result_id"]))


# -- mode routing ------------------------------------------------------


def test_immediate_mode_skips_plan_and_goes_to_draft() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate")
        committed = _commit_brief(facade, run_id)
    assert committed.data["progress"]["next_required_step"] == "draft"


def test_detailed_mode_requires_plan_before_draft() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="detailed")
        committed = _commit_brief(facade, run_id, _brief_payload(mode="detailed"))
    assert committed.data["progress"]["next_required_step"] == "plan"


def test_prepare_plan_refused_in_immediate_mode() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate")
        _commit_brief(facade, run_id)
        result = facade.prepare_writing_plan(run_id, "d1")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "plan_not_required"


def test_prepare_draft_requires_plan_in_detailed_mode() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="detailed")
        _commit_brief(facade, run_id, _brief_payload(mode="detailed"))
        result = facade.prepare_writing_draft(run_id, "d1")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "plan_required"


# -- plan --------------------------------------------------------------


def test_commit_plan_advances_to_draft() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="detailed")
        _commit_brief(facade, run_id, _brief_payload(mode="detailed"))
        committed = _commit_plan(facade, run_id, "d1")
        assert committed.ok
        assert committed.data["progress"]["next_required_step"] == "draft"
        stored = facade.stores.plans.load_latest(run_id, "d1")
    assert stored.sections == ["intro", "body"]


def test_commit_plan_is_idempotent() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="detailed")
        _commit_brief(facade, run_id, _brief_payload(mode="detailed"))
        prepared = facade.prepare_writing_plan(run_id, "d1")
        submitted = _submit(facade, prepared.data["work_packet_id"], _plan_payload())
        first = facade.commit_writing_plan(str(submitted.data["work_result_id"]))
        second = facade.commit_writing_plan(str(submitted.data["work_result_id"]))
    assert first.ok and second.ok
    assert first.data["plan_id"] == second.data["plan_id"]
    assert second.data["already_committed"] is True


def test_commit_plan_rejects_unknown_research_fact() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="detailed", research_policy="required")
        _commit_brief(facade, run_id, _brief_payload(mode="detailed", research_needed=True))
        _commit_research(facade, run_id)
        prepared = facade.prepare_writing_plan(run_id, "d1")
        submitted = _submit(
            facade, prepared.data["work_packet_id"],
            _plan_payload(research_fact_ids=["ghost"]),
        )
        committed = facade.commit_writing_plan(str(submitted.data["work_result_id"]))
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "unknown_research_fact"


# -- draft -------------------------------------------------------------


def test_each_deliverable_gets_its_own_format_skill() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate")
        payload = _brief_payload(deliverables=[
            {"deliverable_id": "d1", "format": "email", "objective": "Email",
             "audience": "customers", "constraints": [], "selected_skill_ids": ["email"]},
            {"deliverable_id": "d2", "format": "blog", "objective": "Blog",
             "audience": "readers", "constraints": [], "selected_skill_ids": ["blog"]},
        ])
        _commit_brief(facade, run_id, payload)
        email_draft = _commit_draft(facade, run_id, "d1")
        blog_draft = _commit_draft(facade, run_id, "d2")
        email_ids = {s["skill_id"] for s in email_draft.data["selected_skills"]}
        blog_ids = {s["skill_id"] for s in blog_draft.data["selected_skills"]}
    assert "email" in email_ids and "blog" not in email_ids
    assert "blog" in blog_ids and "email" not in blog_ids
    assert "anti-ai-detection" in email_ids and "anti-ai-detection" in blog_ids


def test_anti_ai_skill_excluded_when_requested() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate", exclude=["anti-ai-detection"])
        _commit_brief(facade, run_id)
        draft = _commit_draft(facade, run_id, "d1")
        ids = {s["skill_id"] for s in draft.data["selected_skills"]}
    assert "anti-ai-detection" not in ids
    assert "email" in ids


def test_draft_accepts_known_research_fact_ids() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate", research_policy="required")
        _commit_brief(facade, run_id, _brief_payload(research_needed=True))
        _commit_research(facade, run_id)
        draft = _commit_draft(
            facade, run_id, "d1", _draft_payload(research_fact_ids=["f1"])
        )
        assert draft.ok
        stored = facade.stores.drafts.load_latest(run_id, "d1")
    assert draft.data["research_fact_ids"] == ["f1"]
    assert stored.research_fact_ids == ["f1"]


def test_draft_rejects_unknown_research_fact_ids() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate", research_policy="required")
        _commit_brief(facade, run_id, _brief_payload(research_needed=True))
        _commit_research(facade, run_id)
        prepared = facade.prepare_writing_draft(run_id, "d1")
        submitted = _submit(
            facade, prepared.data["work_packet_id"],
            _draft_payload(research_fact_ids=["ghost"]),
        )
        committed = facade.commit_writing_draft(str(submitted.data["work_result_id"]))
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "unknown_research_fact"


def test_immediate_draft_requires_self_check() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate")
        _commit_brief(facade, run_id)
        prepared = facade.prepare_writing_draft(run_id, "d1")
        submitted = _submit(
            facade, prepared.data["work_packet_id"], _draft_payload(self_check=[])
        )
        committed = facade.commit_writing_draft(str(submitted.data["work_result_id"]))
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "self_check_required"


def test_draft_records_assumptions_and_advances_to_finalize() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate")
        _commit_brief(facade, run_id)
        draft = _commit_draft(
            facade, run_id, "d1", _draft_payload(assumptions=["tone is warm"])
        )
        stored = facade.stores.drafts.load_latest(run_id, "d1")
    assert stored.assumptions == ["tone is warm"]
    # A single immediate deliverable with its draft done leaves only finalization.
    assert draft.data["progress"]["next_required_step"] == "finalize"


def test_commit_draft_is_idempotent() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate")
        _commit_brief(facade, run_id)
        prepared = facade.prepare_writing_draft(run_id, "d1")
        submitted = _submit(facade, prepared.data["work_packet_id"], _draft_payload())
        first = facade.commit_writing_draft(str(submitted.data["work_result_id"]))
        second = facade.commit_writing_draft(str(submitted.data["work_result_id"]))
    assert first.ok and second.ok
    assert first.data["draft_id"] == second.data["draft_id"]
    assert second.data["already_committed"] is True


def test_prepare_draft_rejects_unknown_deliverable() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, mode="immediate")
        _commit_brief(facade, run_id)
        result = facade.prepare_writing_draft(run_id, "nope")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "deliverable_not_found"
