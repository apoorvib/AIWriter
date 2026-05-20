from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from essay_writer.agent_tools.facade import AgentToolFacade


INSTALL_MESSAGE = 'Install Agent Tool Mode dependencies with: pip install -e ".[agent-tools]"'


def build_server(data_dir: str | Path | None = None) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(INSTALL_MESSAGE) from exc

    app = FastMCP("essaywriter-agent-tools")
    facade = AgentToolFacade.from_data_dir(data_dir or os.environ.get("ESSAY_DATA_DIR", "./data"))

    def result(value: object) -> dict[str, object]:
        return asdict(value)

    @app.tool()
    def get_harness_instructions() -> dict[str, object]:
        return result(facade.get_harness_instructions())

    @app.tool()
    def start_agent_run(objective: str, job_id: str | None = None) -> dict[str, object]:
        return result(facade.start_agent_run(objective=objective, job_id=job_id))

    @app.tool()
    def recover_agent_run(agent_run_id: str) -> dict[str, object]:
        return result(facade.recover_agent_run(agent_run_id=agent_run_id))

    @app.tool()
    def get_agent_run_state(agent_run_id: str) -> dict[str, object]:
        return result(facade.get_agent_run_state(agent_run_id=agent_run_id))

    @app.tool()
    def list_agent_runs(status: str | None = None, limit: int = 20) -> dict[str, object]:
        return result(facade.list_agent_runs(status=status, limit=limit))

    @app.tool()
    def checkpoint_agent_run(
        agent_run_id: str,
        current_phase: str,
        decision: str | None = None,
        blocked_on: str | None = None,
        next_suggested_tools: list[str] | None = None,
    ) -> dict[str, object]:
        return result(
            facade.checkpoint_agent_run(
                agent_run_id=agent_run_id,
                current_phase=current_phase,
                decision=decision,
                blocked_on=blocked_on,
                next_suggested_tools=next_suggested_tools,
            )
        )

    @app.tool()
    def ingest_source_file(
        document_path: str,
        source_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.ingest_source_file(
                document_path,
                source_id=source_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def prepare_source_card(
        source_id: str,
        agent_run_id: str | None = None,
        reuse_existing: bool = True,
    ) -> dict[str, object]:
        return result(
            facade.prepare_source_card(
                source_id,
                agent_run_id=agent_run_id,
                reuse_existing=reuse_existing,
            )
        )

    @app.tool()
    def submit_work_result(
        work_packet_id: str,
        payload: dict[str, object],
        producer: dict[str, object] | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        from essay_writer.agent_tools.schemas import WorkProducer

        producer_obj = WorkProducer.from_dict(producer or {"type": "main_agent", "role": "orchestrator"})
        return result(
            facade.submit_work_result(
                work_packet_id,
                payload=payload,
                producer=producer_obj,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def commit_source_card(
        work_result_id: str | None = None,
        payload: dict[str, object] | None = None,
        source_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.commit_source_card(
                work_result_id=work_result_id,
                payload=payload,
                source_id=source_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def prepare_task_spec(raw_text: str, agent_run_id: str | None = None) -> dict[str, object]:
        return result(facade.prepare_task_spec(raw_text, agent_run_id=agent_run_id))

    @app.tool()
    def commit_task_spec(
        work_result_id: str,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.commit_task_spec(
                work_result_id=work_result_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def create_job_from_artifacts(
        task_spec_id: str,
        source_ids: list[str],
        job_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.create_job_from_artifacts(
                task_spec_id,
                source_ids,
                job_id=job_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def prepare_topics(
        job_id: str,
        user_instruction: str | None = None,
        max_candidates: int = 8,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.prepare_topics(
                job_id,
                user_instruction=user_instruction,
                max_candidates=max_candidates,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def commit_topics(
        work_result_id: str | None = None,
        payload: dict[str, object] | None = None,
        job_id: str | None = None,
        user_instruction: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.commit_topics(
                work_result_id=work_result_id,
                payload=payload,
                job_id=job_id,
                user_instruction=user_instruction,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def select_topic(
        job_id: str,
        round_number: int,
        topic_id: str,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(facade.select_topic(job_id, round_number, topic_id, agent_run_id=agent_run_id))

    @app.tool()
    def reject_topic(
        job_id: str,
        round_number: int,
        topic_id: str,
        reason: str,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.reject_topic(
                job_id,
                round_number,
                topic_id,
                reason,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def create_research_plan(
        job_id: str,
        external_search_allowed: bool = False,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.create_research_plan(
                job_id,
                external_search_allowed=external_search_allowed,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def resolve_source_requests(
        job_id: str,
        locators: list[dict[str, object]] | None = None,
        research_plan_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.resolve_source_requests(
                job_id,
                locators=locators,
                research_plan_id=research_plan_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def prepare_research_notes(
        job_id: str,
        source_packet_bundle_id: str,
        max_notes: int = 80,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.prepare_research_notes(
                job_id,
                source_packet_bundle_id,
                max_notes=max_notes,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def commit_research_notes(work_result_id: str, agent_run_id: str | None = None) -> dict[str, object]:
        return result(facade.commit_research_notes(work_result_id, agent_run_id=agent_run_id))

    @app.tool()
    def prepare_outline(
        job_id: str,
        source_packet_bundle_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.prepare_outline(
                job_id,
                source_packet_bundle_id=source_packet_bundle_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def commit_outline(work_result_id: str, agent_run_id: str | None = None) -> dict[str, object]:
        return result(facade.commit_outline(work_result_id, agent_run_id=agent_run_id))

    @app.tool()
    def prepare_draft(
        job_id: str,
        source_packet_bundle_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.prepare_draft(
                job_id,
                source_packet_bundle_id=source_packet_bundle_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def commit_draft(work_result_id: str, agent_run_id: str | None = None) -> dict[str, object]:
        return result(facade.commit_draft(work_result_id, agent_run_id=agent_run_id))

    @app.tool()
    def prepare_style_revision(
        job_id: str,
        source_draft_id: str | None = None,
        source_packet_bundle_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.prepare_style_revision(
                job_id,
                source_draft_id=source_draft_id,
                source_packet_bundle_id=source_packet_bundle_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def commit_style_revision(
        work_result_id: str,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.commit_style_revision(work_result_id, agent_run_id=agent_run_id)
        )

    @app.tool()
    def prepare_revision(
        job_id: str,
        source_draft_id: str | None = None,
        validation_version: int | None = None,
        user_instruction: str | None = None,
        selected_lenses: list[str] | None = None,
        source_packet_bundle_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.prepare_revision(
                job_id,
                source_draft_id=source_draft_id,
                validation_version=validation_version,
                user_instruction=user_instruction,
                selected_lenses=selected_lenses,
                source_packet_bundle_id=source_packet_bundle_id,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def commit_revision(work_result_id: str, agent_run_id: str | None = None) -> dict[str, object]:
        return result(facade.commit_revision(work_result_id, agent_run_id=agent_run_id))

    @app.tool()
    def prepare_validation(
        job_id: str,
        draft_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(facade.prepare_validation(job_id, draft_id=draft_id, agent_run_id=agent_run_id))

    @app.tool()
    def commit_validation(work_result_id: str, agent_run_id: str | None = None) -> dict[str, object]:
        return result(facade.commit_validation(work_result_id, agent_run_id=agent_run_id))

    @app.tool()
    def save_user_edit(
        job_id: str,
        draft_id: str,
        content: str,
        parent_export_id: str | None = None,
        user_instruction: str | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.save_user_edit(
                job_id,
                draft_id,
                content,
                parent_export_id=parent_export_id,
                user_instruction=user_instruction,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def export_markdown(
        job_id: str,
        draft_id: str | None = None,
        validation_version: int | None = None,
        agent_run_id: str | None = None,
    ) -> dict[str, object]:
        return result(
            facade.export_markdown(
                job_id,
                draft_id=draft_id,
                validation_version=validation_version,
                agent_run_id=agent_run_id,
            )
        )

    @app.tool()
    def cleanup_agent_run(
        agent_run_id: str,
        scope: str = "workflow_logs",
        confirm: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        return result(
            facade.cleanup_agent_run(
                agent_run_id,
                scope=scope,
                confirm=confirm,
                force=force,
            )
        )

    @app.tool()
    def get_job_summary(job_id: str) -> dict[str, object]:
        return result(facade.get_job_summary(job_id))

    @app.tool()
    def list_sources() -> dict[str, object]:
        return result(facade.list_sources())

    @app.tool()
    def get_source_card(source_id: str) -> dict[str, object]:
        return result(facade.get_source_card(source_id))

    @app.tool()
    def list_work_packets(
        scope: str | None = None,
        status: str | None = None,
    ) -> dict[str, object]:
        return result(facade.list_work_packets(scope=scope, status=status))

    @app.tool()
    def get_work_packet(work_packet_id: str) -> dict[str, object]:
        return result(facade.get_work_packet(work_packet_id))

    @app.tool()
    def list_work_results(
        scope: str | None = None,
        status: str | None = None,
    ) -> dict[str, object]:
        return result(facade.list_work_results(scope=scope, status=status))

    @app.tool()
    def get_work_result(work_result_id: str) -> dict[str, object]:
        return result(facade.get_work_result(work_result_id))

    @app.tool()
    def search_source(source_id: str, query: str, limit: int = 5) -> dict[str, object]:
        return result(facade.search_source(source_id, query, limit=limit))

    @app.tool()
    def read_source_packet(
        locator_payload: dict[str, object],
        max_chars: int | None = None,
    ) -> dict[str, object]:
        return result(facade.read_source_packet(locator_payload, max_chars=max_chars))

    @app.tool()
    def get_source_packet_bundle(source_packet_bundle_id: str) -> dict[str, object]:
        return result(facade.get_source_packet_bundle(source_packet_bundle_id))

    @app.tool()
    def run_deterministic_checks(
        draft_text_or_id: str,
        job_id: str | None = None,
    ) -> dict[str, object]:
        return result(facade.run_deterministic_checks(draft_text_or_id, job_id=job_id))

    @app.tool()
    def list_drafts(job_id: str) -> dict[str, object]:
        return result(facade.list_drafts(job_id))

    @app.tool()
    def get_draft(
        job_id: str,
        draft_id: str | None = None,
        version: int | None = None,
    ) -> dict[str, object]:
        return result(facade.get_draft(job_id, draft_id=draft_id, version=version))

    @app.prompt()
    def essay_agent_tool_mode() -> str:
        instructions = facade.get_harness_instructions()
        return str(instructions.data.get("context_prompt", ""))

    return app


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
