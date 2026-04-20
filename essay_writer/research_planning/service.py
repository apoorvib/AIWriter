from __future__ import annotations

from essay_writer.jobs.schema import EssayJob
from essay_writer.research_planning.schema import ResearchPlan, SourceReadingPriority
from essay_writer.sources.schema import SourceIndexManifest
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.schema import SelectedTopic


class ResearchPlanningService:
    def __init__(self, *, prompt_version: str = "research-planning-v1") -> None:
        self._prompt_version = prompt_version

    def create_plan(
        self,
        *,
        job: EssayJob,
        task_spec: TaskSpecification,
        selected_topic: SelectedTopic,
        index_manifests: list[SourceIndexManifest],
        version: int = 1,
        external_search_allowed: bool = False,
        model: str | None = None,
    ) -> ResearchPlan:
        manifest_by_source = {manifest.source_id: manifest for manifest in index_manifests}
        warnings: list[str] = []
        priorities: list[SourceReadingPriority] = []
        for lead in selected_topic.source_leads:
            manifest = manifest_by_source.get(lead.source_id)
            if manifest is None:
                warnings.append(f"No index manifest available for source_id={lead.source_id}.")
                continue
            priorities.append(
                SourceReadingPriority(
                    source_id=lead.source_id,
                    priority="high" if lead.chunk_ids else "medium",
                    rationale=_priority_rationale(lead.source_id, len(lead.chunk_ids), manifest.total_chunks),
                    chunk_ids=lead.chunk_ids,
                    suggested_source_search_queries=lead.suggested_source_search_queries,
                )
            )

        if not priorities:
            warnings.append("No uploaded source priorities were available for the selected topic.")

        external_queries: list[str] = []
        if external_search_allowed:
            external_queries = _external_search_queries(selected_topic)

        return ResearchPlan(
            id=f"research_plan_v{version:03d}",
            job_id=job.id,
            selected_topic_id=selected_topic.topic_id,
            version=version,
            research_question=selected_topic.research_question,
            source_requirements=_source_requirements(task_spec),
            uploaded_source_priorities=priorities,
            expected_evidence_categories=_expected_evidence_categories(task_spec),
            external_search_allowed=external_search_allowed,
            external_search_queries=external_queries,
            warnings=warnings,
            prompt_version=self._prompt_version,
        )


def _priority_rationale(source_id: str, explicit_chunk_count: int, total_chunks: int) -> str:
    if explicit_chunk_count:
        return (
            f"Topic ideation selected {explicit_chunk_count} specific chunks from {source_id}; "
            "read those first, then search nearby indexed material if needed."
        )
    return (
        f"Topic ideation selected {source_id}; search its {total_chunks} indexed chunks for direct support."
    )


def _source_requirements(task_spec: TaskSpecification) -> list[str]:
    requirements = [item for item in task_spec.required_sources if item]
    checklist_source_items = [
        item.text
        for item in task_spec.extracted_checklist
        if item.required and item.category == "source"
    ]
    result = [*requirements, *checklist_source_items]
    if not result:
        result.append("Use the uploaded sources as the evidence base for this MVP workflow.")
    return list(dict.fromkeys(result))


def _expected_evidence_categories(task_spec: TaskSpecification) -> list[str]:
    categories = ["background", "thesis_support", "example"]
    text = " ".join([*task_spec.required_structure, *task_spec.rubric, *task_spec.grading_criteria]).lower()
    if "counter" in text or "opposing" in text:
        categories.append("counterargument")
    if "statistic" in text or "data" in text:
        categories.append("statistic")
    return categories


def _external_search_queries(selected_topic: SelectedTopic) -> list[str]:
    return [
        selected_topic.research_question,
        f"{selected_topic.title} evidence",
    ]
