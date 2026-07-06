from __future__ import annotations

from essay_writer.agent_tools.schemas import WorkProducer
from essay_writer.writing.facade import WritingToolFacade
from tests.agent_tools._tmp import LocalAgentTempDir


def _facade(tmp) -> WritingToolFacade:
    return WritingToolFacade.from_data_dir(tmp, enforce_attention_challenge=False)


def _submit(facade, packet_id, payload, *, producer=None):
    return facade.submit_writing_result(
        str(packet_id), payload,
        producer=producer or WorkProducer(type="main_agent"),
    )


def _brief_payload(**overrides) -> dict:
    payload = {
        "mode": "detailed",
        "purpose": "Explain the launch",
        "audience": "readers",
        "deliverables": [
            {
                "deliverable_id": "d1", "format": "blog",
                "objective": "Explain", "audience": "readers",
                "constraints": [], "selected_skill_ids": ["blog"],
            }
        ],
        "selected_skill_ids": [],
        "research_needed": False,
        "research_reasons": [],
        "assumptions": ["readers are technical"],
        "blocking_questions": [],
    }
    payload.update(overrides)
    return payload


def _commit_brief(facade, run_id, payload=None):
    prepared = facade.prepare_writing_brief(run_id)
    submitted = _submit(facade, prepared.data["work_packet_id"], payload or _brief_payload())
    return facade.commit_writing_brief(str(submitted.data["work_result_id"]))


def _commit_plan(facade, run_id, deliverable_id="d1"):
    prepared = facade.prepare_writing_plan(run_id, deliverable_id)
    submitted = _submit(facade, prepared.data["work_packet_id"], {
        "sections": ["intro"], "key_points": [], "research_fact_ids": []})
    return facade.commit_writing_plan(str(submitted.data["work_result_id"]))


def _commit_draft(facade, run_id, deliverable_id="d1", content="First blog draft."):
    prepared = facade.prepare_writing_draft(run_id, deliverable_id)
    submitted = _submit(facade, prepared.data["work_packet_id"], {
        "content": content, "assumptions": ["readers are technical"],
        "research_fact_ids": [], "self_check": []})
    return facade.commit_writing_draft(str(submitted.data["work_result_id"]))


def _setup_detailed_draft(facade, content="First blog draft.") -> str:
    started = facade.start_writing_run("Write a detailed blog", mode="detailed")
    run_id = str(started.data["writing_run_id"])
    _commit_brief(facade, run_id)
    _commit_plan(facade, run_id)
    _commit_draft(facade, run_id, content=content)
    return run_id


def _review_payload(*, passed, issues=None) -> dict:
    return {"passed": passed, "issues": issues or [], "notes": []}


def _issue(severity="major", category="style") -> dict:
    return {
        "issue_id": "i1", "severity": severity, "location": "para 1",
        "skill_id": "blog", "evidence": "weak opener", "correction": "tighten it",
        "category": category,
    }


def _run_review(facade, run_id, review_payload, deliverable_id="d1"):
    prepared = facade.prepare_writing_review(run_id, deliverable_id)
    packet_id = str(prepared.data["work_packet_id"])
    token = facade.dispatch_writing_reviewer(packet_id).data["subagent_token"]
    submitted = _submit(
        facade, packet_id, review_payload,
        producer=WorkProducer(type="subagent", subagent_token=str(token)),
    )
    return facade.commit_writing_review(str(submitted.data["work_result_id"]))


def _run_revision(facade, run_id, content, deliverable_id="d1"):
    prepared = facade.prepare_writing_revision(run_id, deliverable_id)
    submitted = _submit(facade, prepared.data["work_packet_id"], {
        "content": content, "assumptions": [], "research_fact_ids": [], "self_check": []})
    return facade.commit_writing_revision(str(submitted.data["work_result_id"]))


# -- clean-context delegation -----------------------------------------


def test_review_packet_requires_clean_context_delegation() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        prepared = facade.prepare_writing_review(run_id, "d1")
        packet = facade.work_store.load_packet(str(prepared.data["work_packet_id"]))
    assert prepared.ok
    assert packet.delegation_required is True


def test_review_rejected_without_subagent_token() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        prepared = facade.prepare_writing_review(run_id, "d1")
        rejected = _submit(
            facade, prepared.data["work_packet_id"], _review_payload(passed=True),
            producer=WorkProducer(type="main_agent"),
        )
    assert rejected.ok is False
    assert rejected.error is not None
    assert rejected.error.code == "subagent_dispatch_required"


def test_review_rejected_when_main_agent_carries_token() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        prepared = facade.prepare_writing_review(run_id, "d1")
        packet_id = str(prepared.data["work_packet_id"])
        token = facade.dispatch_writing_reviewer(packet_id).data["subagent_token"]
        rejected = _submit(
            facade, packet_id, _review_payload(passed=True),
            producer=WorkProducer(type="main_agent", subagent_token=str(token)),
        )
    assert rejected.ok is False
    assert rejected.error is not None
    assert rejected.error.code == "subagent_dispatch_required"


def test_prepare_review_refused_in_immediate_mode() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        started = facade.start_writing_run("Write an email", mode="immediate")
        run_id = str(started.data["writing_run_id"])
        _commit_brief(facade, run_id, _brief_payload(
            mode="immediate",
            deliverables=[{"deliverable_id": "d1", "format": "email",
                           "objective": "Email", "audience": "customers",
                           "constraints": [], "selected_skill_ids": ["email"]}],
        ))
        prepared = facade.prepare_writing_draft(run_id, "d1")
        _submit(facade, prepared.data["work_packet_id"], {
            "content": "Hi", "assumptions": [], "research_fact_ids": [],
            "self_check": ["read"]})
        # even with a draft, immediate deliverables carry no separate review
        result = facade.prepare_writing_review(run_id, "d1")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "review_not_required"


# -- review binding and outcomes --------------------------------------


def test_review_commit_binds_skills_and_draft_hash() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        draft = facade.stores.drafts.load_latest(run_id, "d1")
        committed = _run_review(facade, run_id, _review_payload(passed=True))
        assert committed.ok
        review = facade.stores.reviews.load_latest(run_id, "d1")
        skill_ids = {s["skill_id"] for s in committed.data["selected_skills"]}
    assert review.draft_sha256 == draft.content_sha256
    assert {"blog", "anti-ai-detection"} <= skill_ids


def test_passing_review_completes_deliverable() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        committed = _run_review(facade, run_id, _review_payload(passed=True))
    assert committed.data["progress"]["next_required_step"] == "finalize"


def test_failing_review_routes_to_revision() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        committed = _run_review(
            facade, run_id, _review_payload(passed=False, issues=[_issue()]))
    assert committed.data["progress"]["next_required_step"] == "revision"


def test_one_successful_revision_completes() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        _run_review(facade, run_id, _review_payload(passed=False, issues=[_issue()]))
        revised = _run_revision(facade, run_id, "Second, tighter blog draft.")
        assert revised.data["progress"]["next_required_step"] == "review"
        final = _run_review(facade, run_id, _review_payload(passed=True))
    assert final.data["progress"]["next_required_step"] == "finalize"


def test_stale_review_rejected_after_revision() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        # Prepare + dispatch a review bound to draft v1.
        prepared = facade.prepare_writing_review(run_id, "d1")
        packet_id = str(prepared.data["work_packet_id"])
        token = facade.dispatch_writing_reviewer(packet_id).data["subagent_token"]
        # A revision lands a new draft before the stale review is committed.
        _run_review(facade, run_id, _review_payload(passed=False, issues=[_issue()]))
        _run_revision(facade, run_id, "A newer draft that supersedes v1.")
        submitted = _submit(
            facade, packet_id, _review_payload(passed=True),
            producer=WorkProducer(type="subagent", subagent_token=str(token)),
        )
        committed = facade.commit_writing_review(str(submitted.data["work_result_id"]))
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "stale_review"


def test_two_round_cap_style_completes_with_warning() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        _run_review(facade, run_id, _review_payload(passed=False, issues=[_issue()]))
        _run_revision(facade, run_id, "Revision one.")
        _run_review(facade, run_id, _review_payload(passed=False, issues=[_issue()]))
        _run_revision(facade, run_id, "Revision two.")
        capped = _run_review(
            facade, run_id, _review_payload(passed=False, issues=[_issue()]))
        progress = capped.data["progress"]
    assert progress["next_required_step"] == "finalize"
    assert any("revision" in w.lower() for w in progress["warnings"])


def test_two_round_cap_blocker_blocks_and_finalize_refused() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        blocker = [_issue(severity="blocker", category="fact")]
        _run_review(facade, run_id, _review_payload(passed=False, issues=blocker))
        _run_revision(facade, run_id, "Revision one.")
        _run_review(facade, run_id, _review_payload(passed=False, issues=blocker))
        _run_revision(facade, run_id, "Revision two.")
        capped = _run_review(facade, run_id, _review_payload(passed=False, issues=blocker))
        assert capped.data["progress"]["status"] == "blocked"
        refused = facade.finalize_writing_run(run_id)
    assert refused.ok is False
    assert refused.error is not None
    assert refused.error.code == "run_blocked"


# -- finalization -----------------------------------------------------


def _setup_immediate_draft(facade, content="Subject: Hi\n\nWe launched.") -> str:
    started = facade.start_writing_run("Write an email", mode="immediate")
    run_id = str(started.data["writing_run_id"])
    _commit_brief(facade, run_id, _brief_payload(
        mode="immediate",
        deliverables=[{"deliverable_id": "d1", "format": "email",
                       "objective": "Email", "audience": "customers",
                       "constraints": [], "selected_skill_ids": ["email"]}],
    ))
    prepared = facade.prepare_writing_draft(run_id, "d1")
    submitted = _submit(facade, prepared.data["work_packet_id"], {
        "content": content, "assumptions": ["knows product"],
        "research_fact_ids": [], "self_check": ["read aloud"]})
    facade.commit_writing_draft(str(submitted.data["work_result_id"]))
    return run_id


def test_immediate_finalize_persists_output() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_immediate_draft(facade)
        finalized = facade.finalize_writing_run(run_id)
        assert finalized.ok
        stored_output = facade.stores.outputs.load(run_id)
        run = facade.stores.runs.load(run_id)
    assert finalized.data["deliverables"][0]["format"] == "email"
    assert "launched" in finalized.data["deliverables"][0]["content"]
    assert run.status == "complete"
    assert run.output_id == stored_output.output_id
    assert finalized.data["progress"]["status"] == "complete"


def test_finalize_refuses_incomplete_run() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        started = facade.start_writing_run("Write an email", mode="immediate")
        run_id = str(started.data["writing_run_id"])
        _commit_brief(facade, run_id, _brief_payload(
            mode="immediate",
            deliverables=[{"deliverable_id": "d1", "format": "email",
                           "objective": "Email", "audience": "customers",
                           "constraints": [], "selected_skill_ids": ["email"]}],
        ))
        # brief committed but no draft yet -> not finalizable
        refused = facade.finalize_writing_run(run_id)
    assert refused.ok is False
    assert refused.error is not None
    assert refused.error.code == "run_incomplete"


def test_finalize_is_idempotent() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _setup_detailed_draft(facade)
        _run_review(facade, run_id, _review_payload(passed=True))
        first = facade.finalize_writing_run(run_id)
        second = facade.finalize_writing_run(run_id)
    assert first.ok and second.ok
    assert first.data["output_id"] == second.data["output_id"]
    assert second.data["already_finalized"] is True
