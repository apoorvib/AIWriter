from __future__ import annotations

import pytest

from essay_writer.writing.progress import build_writing_progress
from essay_writer.writing.schema import (
    DeliverableSpec, ResearchPolicy, ReviewIssue, SkillSelection, WriteMode,
    WritingBrief, WritingDraft, WritingOutput, WritingPlan, WritingResearch,
    WritingReview, WritingRun,
)
from essay_writer.writing.storage import WritingStores

RUN_ID = "wrun-1"


def _skill(skill_id: str = "email") -> SkillSelection:
    return SkillSelection(skill_id, "1", "sha256:a")


def _stores(tmp_path):
    return WritingStores.from_data_dir(tmp_path)


def _run(stores, **kwargs) -> WritingRun:
    return stores.runs.create(WritingRun(RUN_ID, "Write something", **kwargs))


def _commit_brief(stores, *, mode, deliverables, research_needed=False,
                  blocking_questions=None, version=1) -> WritingBrief:
    return stores.briefs.save(WritingBrief(
        brief_id=f"{RUN_ID}-brief-{version}", writing_run_id=RUN_ID, version=version,
        mode=mode, purpose="Announce the launch", audience="customers",
        deliverables=deliverables, selected_skills=[_skill()],
        research_needed=research_needed, blocking_questions=blocking_questions or [],
    ))


def _commit_research(stores, version=1) -> WritingResearch:
    return stores.research.save(WritingResearch(
        research_id=f"{RUN_ID}-research-{version}", writing_run_id=RUN_ID,
        version=version, sources=[], facts=[],
    ))


def _commit_plan(stores, deliverable_id, version=1) -> WritingPlan:
    return stores.plans.save(WritingPlan(
        plan_id=f"{RUN_ID}-{deliverable_id}-plan-{version}", writing_run_id=RUN_ID,
        deliverable_id=deliverable_id, version=version, sections=["intro", "body"],
    ))


def _commit_draft(stores, deliverable_id, content, version=1, origin="draft") -> WritingDraft:
    return stores.drafts.save(WritingDraft(
        draft_id=f"{RUN_ID}-{deliverable_id}-draft-{version}", writing_run_id=RUN_ID,
        deliverable_id=deliverable_id, version=version, content=content,
        selected_skills=[_skill(deliverable_id)], origin=origin,
    ))


def _commit_review(stores, deliverable_id, draft, *, passed, issues=None, version=1) -> WritingReview:
    return stores.reviews.save(WritingReview(
        review_id=f"{RUN_ID}-{deliverable_id}-review-{version}", writing_run_id=RUN_ID,
        deliverable_id=deliverable_id, version=version, draft_id=draft.draft_id,
        draft_sha256=draft.content_sha256, selected_skills=[_skill(deliverable_id)],
        passed=passed, issues=issues or [],
    ))


def _blocker(deliverable_id: str) -> ReviewIssue:
    return ReviewIssue(
        issue_id=f"{deliverable_id}-i1", severity="blocker", location="para 2",
        skill_id="email", evidence="unsupported claim", correction="cite a source",
        category="factual",
    )


# -- fixtures used by the table-driven next_required_step test --

@pytest.fixture
def new(tmp_path):
    stores = _stores(tmp_path)
    run = _run(stores)
    return run, stores


@pytest.fixture
def immediate_ready(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.IMMEDIATE,
                  deliverables=[DeliverableSpec("d1", "email", "Announce")])
    return stores.runs.load(RUN_ID), stores


@pytest.fixture
def detailed_researched(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.DETAILED, research_needed=True,
                  deliverables=[DeliverableSpec("d1", "blog", "Announce")])
    _commit_research(stores)
    return stores.runs.load(RUN_ID), stores


@pytest.fixture
def detailed_drafted(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.DETAILED,
                  deliverables=[DeliverableSpec("d1", "blog", "Announce")])
    _commit_plan(stores, "d1")
    _commit_draft(stores, "d1", "Blog draft body")
    return stores.runs.load(RUN_ID), stores


@pytest.fixture
def complete_artifacts(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.DETAILED,
                  deliverables=[DeliverableSpec("d1", "blog", "Announce")])
    _commit_plan(stores, "d1")
    draft = _commit_draft(stores, "d1", "Blog draft body")
    _commit_review(stores, "d1", draft, passed=True)
    return stores.runs.load(RUN_ID), stores


@pytest.mark.parametrize(("fixture_name", "expected"), [
    ("new", "brief"),
    ("immediate_ready", "draft"),
    ("detailed_researched", "plan"),
    ("detailed_drafted", "review"),
    ("complete_artifacts", "finalize"),
])
def test_next_required_step(request, fixture_name, expected):
    run, stores = request.getfixturevalue(fixture_name)
    assert build_writing_progress(run, stores)["next_required_step"] == expected


def test_new_run_is_active_and_not_done(new):
    run, stores = new
    ledger = build_writing_progress(run, stores)
    assert ledger["status"] == "active"
    assert ledger["all_required_done"] is False
    assert ledger["requires_human"] is False
    assert ledger["next_action"]["tool"] == "prepare_writing_brief"


def test_blocking_brief_needs_human_input(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.IMMEDIATE,
                  deliverables=[DeliverableSpec("d1", "email", "Announce")],
                  blocking_questions=["Who is the recipient?"])
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["status"] == "needs_input"
    assert ledger["requires_human"] is True
    assert ledger["next_required_step"] is None
    assert ledger["next_action"]["tool"] == "answer_writing_questions"


def test_immediate_run_requires_research_before_draft(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.IMMEDIATE, research_needed=True,
                  deliverables=[DeliverableSpec("d1", "email", "Announce")])
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["next_required_step"] == "research"


def test_required_research_policy_forces_research(tmp_path):
    stores = _stores(tmp_path)
    _run(stores, research_policy=ResearchPolicy.REQUIRED)
    _commit_brief(stores, mode=WriteMode.IMMEDIATE, research_needed=False,
                  deliverables=[DeliverableSpec("d1", "email", "Announce")])
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["next_required_step"] == "research"


def test_research_off_policy_skips_research(tmp_path):
    stores = _stores(tmp_path)
    _run(stores, research_policy=ResearchPolicy.OFF)
    _commit_brief(stores, mode=WriteMode.IMMEDIATE, research_needed=True,
                  deliverables=[DeliverableSpec("d1", "email", "Announce")])
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["next_required_step"] == "draft"


def test_failing_review_requires_revision(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.DETAILED,
                  deliverables=[DeliverableSpec("d1", "blog", "Announce")])
    _commit_plan(stores, "d1")
    draft = _commit_draft(stores, "d1", "Blog draft body")
    _commit_review(stores, "d1", draft, passed=False, issues=[_blocker("d1")])
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["next_required_step"] == "revision"
    assert ledger["next_deliverable_id"] == "d1"


def test_stale_review_reruns_review(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.DETAILED,
                  deliverables=[DeliverableSpec("d1", "blog", "Announce")])
    _commit_plan(stores, "d1")
    draft = _commit_draft(stores, "d1", "Blog draft body")
    _commit_review(stores, "d1", draft, passed=True)
    # A newer draft supersedes the reviewed one; the old passing review is stale.
    _commit_draft(stores, "d1", "Blog draft revised", version=2, origin="revision")
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["next_required_step"] == "review"


def test_two_failed_revision_rounds_block_the_run(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.DETAILED,
                  deliverables=[DeliverableSpec("d1", "blog", "Announce")])
    _commit_plan(stores, "d1")
    _commit_draft(stores, "d1", "Blog draft v1")
    _commit_draft(stores, "d1", "Blog draft v2", version=2, origin="revision")
    draft = _commit_draft(stores, "d1", "Blog draft v3", version=3, origin="revision")
    _commit_review(stores, "d1", draft, passed=False, issues=[_blocker("d1")], version=3)
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["status"] == "blocked"
    assert ledger["requires_human"] is True
    assert ledger["next_required_step"] is None


def test_style_only_issues_after_cap_finalize_with_warning(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.DETAILED,
                  deliverables=[DeliverableSpec("d1", "blog", "Announce")])
    _commit_plan(stores, "d1")
    _commit_draft(stores, "d1", "Blog draft v1")
    _commit_draft(stores, "d1", "Blog draft v2", version=2, origin="revision")
    draft = _commit_draft(stores, "d1", "Blog draft v3", version=3, origin="revision")
    minor = ReviewIssue("d1-i1", "minor", "para 1", "blog", "wordy", "trim", "style")
    _commit_review(stores, "d1", draft, passed=False, issues=[minor], version=3)
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["next_required_step"] == "finalize"
    assert any("style" in w.lower() for w in ledger["warnings"])


def test_multiple_deliverables_advance_independently(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.IMMEDIATE, deliverables=[
        DeliverableSpec("d1", "email", "Email"),
        DeliverableSpec("d2", "linkedin", "Post"),
    ])
    _commit_draft(stores, "d1", "Email body")
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    # d1 already drafted; the ledger points at the still-undrafted d2.
    assert ledger["next_required_step"] == "draft"
    assert ledger["next_deliverable_id"] == "d2"


def test_output_present_marks_run_complete(tmp_path):
    stores = _stores(tmp_path)
    _run(stores)
    _commit_brief(stores, mode=WriteMode.IMMEDIATE,
                  deliverables=[DeliverableSpec("d1", "email", "Announce")])
    draft = _commit_draft(stores, "d1", "Email body")
    stores.outputs.save(WritingOutput(
        output_id=f"{RUN_ID}-output", writing_run_id=RUN_ID,
        deliverables=[draft], selected_skills=[_skill()],
    ))
    ledger = build_writing_progress(stores.runs.load(RUN_ID), stores)
    assert ledger["status"] == "complete"
    assert ledger["all_required_done"] is True
    assert ledger["next_required_step"] is None
