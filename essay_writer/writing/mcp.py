"""Thin MCP surface for the generic writing workflow.

``register_writing_tools(app, facade)`` attaches every writing tool from the
Task 7-10 facade to a FastMCP ``app`` as a thin wrapper: each tool coerces its
arguments, calls the corresponding :class:`WritingToolFacade` method, and returns
``asdict(ToolResult)``. No provider LLM client is ever instantiated here; the
facade only prepares/commits work against persisted artifacts.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from essay_writer.writing.facade import WritingToolFacade


WRITING_TOOL_NAMES = (
    "start_writing_run",
    "recover_writing_run",
    "get_writing_progress",
    "list_writing_runs",
    "get_writing_output",
    "ingest_writing_context",
    "prepare_writing_brief",
    "submit_writing_result",
    "commit_writing_brief",
    "answer_writing_questions",
    "prepare_writing_research",
    "commit_writing_research",
    "prepare_writing_plan",
    "commit_writing_plan",
    "prepare_writing_draft",
    "commit_writing_draft",
    "prepare_writing_review",
    "dispatch_writing_reviewer",
    "commit_writing_review",
    "prepare_writing_revision",
    "commit_writing_revision",
    "finalize_writing_run",
)


def register_writing_tools(app: Any, facade: WritingToolFacade) -> None:
    """Register the generic ``/write`` tools on a FastMCP ``app``."""

    def result(value: object) -> dict[str, object]:
        return asdict(value)

    # -- run lifecycle -------------------------------------------------

    @app.tool()
    def start_writing_run(
        raw_request: str,
        mode: str | None = None,
        research_policy: str = "auto",
        include_skill_ids: list[str] | None = None,
        exclude_skill_ids: list[str] | None = None,
    ) -> dict[str, object]:
        """Open a new writing run and derive its completion ledger.

        ``mode`` ('immediate'|'detailed') and ``research_policy``
        ('auto'|'required'|'off') are explicit overrides that survive brief
        classification. Leave ``mode`` unset to let the brief decide.
        """
        return result(
            facade.start_writing_run(
                raw_request,
                mode=mode,
                research_policy=research_policy,
                include_skill_ids=include_skill_ids,
                exclude_skill_ids=exclude_skill_ids,
            )
        )

    @app.tool()
    def recover_writing_run(writing_run_id: str) -> dict[str, object]:
        """Rebuild a run's ledger from persisted artifacts and report the next action."""
        return result(facade.recover_writing_run(writing_run_id))

    @app.tool()
    def get_writing_progress(writing_run_id: str) -> dict[str, object]:
        """Read-only completion ledger: the next required step derived from artifacts."""
        return result(facade.get_writing_progress(writing_run_id))

    @app.tool()
    def list_writing_runs(status: str | None = None, limit: int = 20) -> dict[str, object]:
        return result(facade.list_writing_runs(status=status, limit=limit))

    @app.tool()
    def get_writing_output(writing_run_id: str) -> dict[str, object]:
        """Return the finalized output for a completed run, if one exists."""
        return result(facade.get_writing_output(writing_run_id))

    @app.tool()
    def ingest_writing_context(
        writing_run_id: str,
        label: str,
        text: str | None = None,
        document_path: str | None = None,
    ) -> dict[str, object]:
        """Attach untrusted reference content (inline ``text`` or a ``document_path``)."""
        return result(
            facade.ingest_writing_context(
                writing_run_id,
                text=text,
                document_path=document_path,
                label=label,
            )
        )

    # -- brief ---------------------------------------------------------

    @app.tool()
    def prepare_writing_brief(writing_run_id: str) -> dict[str, object]:
        return result(facade.prepare_writing_brief(writing_run_id))

    @app.tool()
    def submit_writing_result(
        work_packet_id: str,
        payload: dict[str, object],
        producer: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Submit a prepared work packet's structured result for later commit.

        For a ``delegation_required`` packet (detailed review) the producer must be
        ``{"type": "subagent", "subagent_token": "<token from dispatch_writing_reviewer>"}``.
        """
        return result(
            facade.submit_writing_result(work_packet_id, payload, producer=producer)
        )

    @app.tool()
    def commit_writing_brief(work_result_id: str) -> dict[str, object]:
        return result(facade.commit_writing_brief(work_result_id))

    @app.tool()
    def answer_writing_questions(writing_run_id: str, answers: str) -> dict[str, object]:
        """Record a human answer to the brief's blocking questions and unblock the run."""
        return result(facade.answer_writing_questions(writing_run_id, answers))

    # -- research ------------------------------------------------------

    @app.tool()
    def prepare_writing_research(writing_run_id: str) -> dict[str, object]:
        return result(facade.prepare_writing_research(writing_run_id))

    @app.tool()
    def commit_writing_research(work_result_id: str) -> dict[str, object]:
        return result(facade.commit_writing_research(work_result_id))

    # -- plan and draft ------------------------------------------------

    @app.tool()
    def prepare_writing_plan(writing_run_id: str, deliverable_id: str) -> dict[str, object]:
        return result(facade.prepare_writing_plan(writing_run_id, deliverable_id))

    @app.tool()
    def commit_writing_plan(work_result_id: str) -> dict[str, object]:
        return result(facade.commit_writing_plan(work_result_id))

    @app.tool()
    def prepare_writing_draft(writing_run_id: str, deliverable_id: str) -> dict[str, object]:
        return result(facade.prepare_writing_draft(writing_run_id, deliverable_id))

    @app.tool()
    def commit_writing_draft(work_result_id: str) -> dict[str, object]:
        return result(facade.commit_writing_draft(work_result_id))

    # -- review, revision, finalize ------------------------------------

    @app.tool()
    def prepare_writing_review(writing_run_id: str, deliverable_id: str) -> dict[str, object]:
        """Prepare a clean-context review packet bound to the current draft.

        The packet is ``delegation_required``: dispatch a reviewer with
        ``dispatch_writing_reviewer`` and submit from that subagent.
        """
        return result(facade.prepare_writing_review(writing_run_id, deliverable_id))

    @app.tool()
    def dispatch_writing_reviewer(
        work_packet_id: str,
        role: str = "writing-reviewer",
        model_tier: str | None = None,
    ) -> dict[str, object]:
        """Issue a subagent dispatch token for a delegation-required review packet."""
        return result(
            facade.dispatch_writing_reviewer(
                work_packet_id, role=role, model_tier=model_tier
            )
        )

    @app.tool()
    def commit_writing_review(work_result_id: str) -> dict[str, object]:
        return result(facade.commit_writing_review(work_result_id))

    @app.tool()
    def prepare_writing_revision(writing_run_id: str, deliverable_id: str) -> dict[str, object]:
        return result(facade.prepare_writing_revision(writing_run_id, deliverable_id))

    @app.tool()
    def commit_writing_revision(work_result_id: str) -> dict[str, object]:
        return result(facade.commit_writing_revision(work_result_id))

    @app.tool()
    def finalize_writing_run(writing_run_id: str) -> dict[str, object]:
        """Deterministically assemble and persist the run's output once every
        deliverable is complete. Refuses incomplete or blocked runs."""
        return result(facade.finalize_writing_run(writing_run_id))


__all__ = ["WRITING_TOOL_NAMES", "register_writing_tools"]
