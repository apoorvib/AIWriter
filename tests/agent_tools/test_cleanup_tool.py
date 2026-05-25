from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from essay_writer.agent_tools.facade import (
    AgentToolFacade,
    CLEANUP_SCOPES,
    _safe_delete_path,
)
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import main_agent
from tests.agent_tools.test_outline_draft_validation_tools import (
    _seed_job_through_draft,
)


def _seed_job_through_export(facade: AgentToolFacade) -> tuple[str, str]:
    """Drive the workflow to draft + validation + export so the data dir
    has the full set of stage artifacts. Returns (agent_run_id, job_id).

    The shared `_seed_job_through_draft` helper does not thread agent_run_id
    through every stage, so we manually attach `job_id` to the agent run after
    the job exists — exactly what `create_job_from_artifacts(agent_run_id=...)`
    does in production when properly threaded."""
    started = facade.start_agent_run(objective="cleanup test")
    agent_run_id = str(started.data["agent_run_id"])
    facade.get_harness_instructions(agent_run_id=agent_run_id)

    _seed_job_through_draft(facade)
    # _seed_job_through_draft drives the workflow without threading
    # agent_run_id, so the underlying job ends up in a late stage while
    # the run sits at "bootstrap". Fast-forward both the job link and the
    # phase so subsequent tools that DO pass agent_run_id satisfy the gate.
    facade.run_store.update_run(
        replace(
            facade.run_store.load_run(agent_run_id),
            job_id="job1",
            current_phase="drafting",
        )
    )

    prepared = facade.prepare_validation("job1", agent_run_id=agent_run_id)
    submitted = facade.submit_work_result(
        str(prepared.data["work_packet_id"]),
        payload={
            "unsupported_claims": [],
            "citation_issues": [],
            "rubric_scores": [],
            "assignment_fit": {"passes": True, "explanation": "Fits."},
            "length_check": {"actual_words": 12, "target_words": None, "passes": True},
            "style_issues": [],
            "diagnostics": [],
            "revision_suggestions": [],
            "overall_quality": 0.9,
        },
        producer=main_agent(),
        agent_run_id=agent_run_id,
    )
    facade.commit_validation(
        work_result_id=str(submitted.data["work_result_id"]),
        agent_run_id=agent_run_id,
    )
    facade.export_markdown(job_id="job1", agent_run_id=agent_run_id)
    return agent_run_id, "job1"


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for entry in path.rglob("*") if entry.is_file())


def test_cleanup_dry_run_reports_counts_without_deleting() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        agent_run_id, job_id = _seed_job_through_export(facade)
        data_dir = tmp / "data"
        events_before = _count_files(data_dir / "agent_runs" / "events")
        packets_before = _count_files(data_dir / "agent_work" / "packets")
        drafts_before = _count_files(data_dir / "drafts" / job_id)
        exports_before = _count_files(data_dir / "exports" / job_id)

        result = facade.cleanup_agent_run(agent_run_id)

        events_after = _count_files(data_dir / "agent_runs" / "events")
        packets_after = _count_files(data_dir / "agent_work" / "packets")

        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["confirm"] is False
        assert result.data["scope"] == "workflow_logs"
        assert result.data["agent_run_id"] == agent_run_id
        assert result.data["job_id"] == job_id
        # No files actually removed.
        assert events_after == events_before
        assert packets_after == packets_before
        assert drafts_before > 0
        assert exports_before > 0
        # Preview includes per-category counts and a total.
        would = result.data["would_delete"]
        assert would["agent_run_events"]["count"] > 0
        assert would["work_packets"]["count"] > 0
        assert would["work_results"]["count"] > 0
        assert would["work_commits"]["count"] > 0
        assert (
            result.data["totals"]["deletable_count"]
            >= would["agent_run_events"]["count"]
        )
        # Preserved categories list drafts + exports under workflow_logs scope.
        preserved = result.data["preserved"]
        assert preserved["job_dir_drafts"]["count"] == drafts_before
        assert preserved["job_dir_exports"]["count"] == exports_before


def test_cleanup_workflow_logs_confirm_deletes_logs_and_preserves_outputs() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        agent_run_id, job_id = _seed_job_through_export(facade)
        data_dir = tmp / "data"
        drafts_before = _count_files(data_dir / "drafts" / job_id)
        exports_before = _count_files(data_dir / "exports" / job_id)
        validations_before = _count_files(data_dir / "validations" / job_id)
        outline_before = _count_files(data_dir / "outlines" / job_id)
        sources_before = _count_files(data_dir / "sources")
        run_file = data_dir / "agent_runs" / "runs" / f"{agent_run_id}.json"
        assert run_file.exists()

        result = facade.cleanup_agent_run(agent_run_id, confirm=True)

        assert result.ok is True
        assert result.data["dry_run"] is False
        assert result.data["confirm"] is True
        # Logs removed.
        assert _count_files(data_dir / "agent_runs" / "events") == 0
        assert _count_files(data_dir / "agent_runs" / "checkpoints") == 0
        assert _count_files(data_dir / "agent_work" / "packets") == 0
        assert _count_files(data_dir / "agent_work" / "results") == 0
        assert _count_files(data_dir / "agent_work" / "commits") == 0
        assert _count_files(data_dir / "agent_work" / "source_packet_bundles") == 0
        # Run summary preserved.
        assert run_file.exists()
        # User-meaningful outputs preserved.
        assert _count_files(data_dir / "drafts" / job_id) == drafts_before
        assert _count_files(data_dir / "exports" / job_id) == exports_before
        assert _count_files(data_dir / "validations" / job_id) == validations_before
        assert _count_files(data_dir / "outlines" / job_id) == outline_before
        assert _count_files(data_dir / "sources") == sources_before
        assert result.data["totals"]["deleted_count"] > 0


def test_cleanup_intermediate_artifacts_drops_research_outline_validation_and_older_drafts() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        agent_run_id, job_id = _seed_job_through_export(facade)
        data_dir = tmp / "data"
        # Add a second draft version to verify older versions are dropped.
        prev = facade.stores.draft_store.load_latest(job_id)
        facade.save_user_edit(
            job_id=job_id,
            draft_id=prev.id,
            content="A second draft version added by the user.",
        )
        draft_files_before = _count_files(data_dir / "drafts" / job_id)
        assert draft_files_before >= 2
        exports_before = _count_files(data_dir / "exports" / job_id)
        sources_before = _count_files(data_dir / "sources")

        result = facade.cleanup_agent_run(
            agent_run_id, scope="intermediate_artifacts", confirm=True
        )

        assert result.ok is True
        # Per-job intermediate dirs gone.
        assert not (data_dir / "research_plans" / job_id).exists()
        assert not (data_dir / "topics" / job_id).exists()
        assert not (data_dir / "research" / job_id).exists()
        assert not (data_dir / "outlines" / job_id).exists()
        assert not (data_dir / "validations" / job_id).exists()
        # Exactly one draft file remains (the latest).
        assert _count_files(data_dir / "drafts" / job_id) == 1
        # Exports + sources untouched.
        assert _count_files(data_dir / "exports" / job_id) == exports_before
        assert _count_files(data_dir / "sources") == sources_before
        # Job record + agent-run record preserved at this scope.
        assert (data_dir / "jobs" / "jobs" / f"{job_id}.json").exists()
        assert (data_dir / "agent_runs" / "runs" / f"{agent_run_id}.json").exists()


def test_cleanup_all_except_export_preserves_exports_and_inputs_only() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        agent_run_id, job_id = _seed_job_through_export(facade)
        data_dir = tmp / "data"
        exports_before = _count_files(data_dir / "exports" / job_id)
        sources_before = _count_files(data_dir / "sources")
        task_specs_before = _count_files(data_dir / "task_specs")

        result = facade.cleanup_agent_run(
            agent_run_id, scope="all_except_export", confirm=True
        )

        assert result.ok is True
        # Drafts, validations, outline, research, topics, plan, job record, agent-run record all gone.
        assert _count_files(data_dir / "drafts" / job_id) == 0
        assert not (data_dir / "outlines" / job_id).exists()
        assert not (data_dir / "research" / job_id).exists()
        assert not (data_dir / "validations" / job_id).exists()
        assert not (data_dir / "topics" / job_id).exists()
        assert not (data_dir / "research_plans" / job_id).exists()
        assert not (data_dir / "jobs" / "jobs" / f"{job_id}.json").exists()
        assert not (data_dir / "agent_runs" / "runs" / f"{agent_run_id}.json").exists()
        # Exports + uploaded sources + task specs survive.
        assert _count_files(data_dir / "exports" / job_id) == exports_before
        assert _count_files(data_dir / "sources") == sources_before
        assert _count_files(data_dir / "task_specs") == task_specs_before


def test_cleanup_unknown_agent_run_returns_clear_error() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        result = facade.cleanup_agent_run("does-not-exist")
        assert result.ok is False
        # _missing_run_result uses the agent_run_missing convention.
        assert "agent_run" in result.error.code or "missing" in result.error.code.lower()


def test_cleanup_rejects_invalid_scope() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="bad scope")
        agent_run_id = str(started.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)
        result = facade.cleanup_agent_run(agent_run_id, scope="nuke_everything")
        assert result.ok is False
        assert result.error.code == "cleanup_scope_invalid"
        assert all(scope in str(result.error.message) for scope in CLEANUP_SCOPES)


def test_cleanup_blocks_when_run_is_active_with_pending_packets() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        agent_run_id, _ = _seed_job_through_export(facade)
        # After export_markdown the run is in the "export" phase; the
        # phase gate blocks prepare_validation from there. Step the run
        # back into validation so we can simulate an active+pending state.
        facade.run_store.update_run(
            replace(
                facade.run_store.load_run(agent_run_id),
                current_phase="validation",
            )
        )
        # Open a new prepare_* packet to leave the run active+pending.
        facade.prepare_validation("job1", agent_run_id=agent_run_id)
        run = facade.run_store.load_run(agent_run_id)
        assert run.pending_work_packet_ids
        assert run.status == "active"

        blocked = facade.cleanup_agent_run(agent_run_id, confirm=True)
        forced = facade.cleanup_agent_run(agent_run_id, confirm=True, force=True)

        assert blocked.ok is False
        assert blocked.error.code == "cleanup_blocked_active_run"
        assert forced.ok is True
        assert forced.data["totals"]["deleted_count"] > 0


def test_cleanup_dry_run_works_on_active_run_without_force() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        agent_run_id, _ = _seed_job_through_export(facade)
        facade.prepare_validation("job1", agent_run_id=agent_run_id)
        # Dry-run must work even while pending packets exist.
        result = facade.cleanup_agent_run(agent_run_id, confirm=False)
        assert result.ok is True
        assert result.data["dry_run"] is True


def test_cleanup_handles_run_with_no_job_id() -> None:
    """A run that was started but never tied to a job should still be cleanable
    at workflow_logs scope. Intermediate/all_except_export should warn about
    the missing job_id but still succeed."""
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        started = facade.start_agent_run(objective="orphan run")
        agent_run_id = str(started.data["agent_run_id"])
        facade.get_harness_instructions(agent_run_id=agent_run_id)

        dry = facade.cleanup_agent_run(agent_run_id)
        confirmed = facade.cleanup_agent_run(
            agent_run_id, scope="intermediate_artifacts", confirm=True
        )

        assert dry.ok is True
        assert dry.data["job_id"] is None
        assert confirmed.ok is True
        # Warning explains why job-scoped deletion is empty.
        assert any("no job_id" in w for w in confirmed.data["warnings"])


def test_safe_delete_path_refuses_path_outside_allowed_root(tmp_path: Path) -> None:
    """Defense-in-depth: the deletion helper must reject any path that
    resolves outside the configured data dir, even if a caller constructed
    one that points elsewhere."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("do not delete", encoding="utf-8")

    try:
        _safe_delete_path(outside / "secret.txt", allowed_root=allowed.resolve())
    except ValueError as exc:
        assert "outside allowed_root" in str(exc)
    else:
        raise AssertionError("expected ValueError for path outside allowed_root")
    assert (outside / "secret.txt").exists()


def test_safe_delete_path_returns_zero_for_missing_path(tmp_path: Path) -> None:
    allowed = tmp_path / "data"
    allowed.mkdir()
    count, byte_total = _safe_delete_path(
        allowed / "absent.json", allowed_root=allowed.resolve()
    )
    assert count == 0
    assert byte_total == 0
