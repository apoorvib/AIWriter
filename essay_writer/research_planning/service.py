from __future__ import annotations

from essay_writer.jobs.schema import EssayJob
from essay_writer.research_planning.schema import ResearchPlan, SourceReadingPriority
from essay_writer.sources.schema import SourceIndexManifest
from essay_writer.sources.access_schema import SourceAccessConfig, SourceLocator, SourceMap
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
        source_maps: list[SourceMap] | None = None,
        source_access_config: SourceAccessConfig | None = None,
        version: int = 1,
        external_search_allowed: bool = False,
        model: str | None = None,
    ) -> ResearchPlan:
        manifest_by_source = {manifest.source_id: manifest for manifest in index_manifests}
        source_map_by_id = {source_map.source_id: source_map for source_map in (source_maps or [])}
        access_config = source_access_config or SourceAccessConfig()
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

        source_requests = _validated_source_requests(
            selected_topic.source_requests,
            job_source_ids=set(job.source_ids),
            source_maps=source_map_by_id,
            config=access_config,
            warnings=warnings,
        )

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
            source_requests=source_requests,
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


def _validated_source_requests(
    requests: list[SourceLocator],
    *,
    job_source_ids: set[str],
    source_maps: dict[str, SourceMap],
    config: SourceAccessConfig,
    warnings: list[str],
) -> list[SourceLocator]:
    valid: list[SourceLocator] = []
    for request in requests:
        if request.source_id not in job_source_ids:
            warnings.append(f"Dropped source request for source not attached to job: {request.source_id}.")
            continue
        source_map = source_maps.get(request.source_id)
        if source_map is None:
            warnings.append(f"Dropped source request without source map: {request.source_id}.")
            continue
        if request.locator_type == "pdf_pages":
            if not _valid_pdf_request(request, source_map, config, warnings):
                continue
        elif request.locator_type == "section":
            section_ids = {unit.unit_id for unit in source_map.units if unit.unit_type == "section"}
            if request.section_id not in section_ids:
                warnings.append(f"Dropped unknown section request: {request.section_id}.")
                continue
        elif request.locator_type == "search":
            if not request.query:
                warnings.append("Dropped search source request without query.")
                continue
        elif request.locator_type == "chunk":
            if not request.chunk_id:
                warnings.append("Dropped chunk source request without chunk_id.")
                continue
        else:
            warnings.append(f"Dropped unsupported source request locator_type={request.locator_type}.")
            continue
        valid.append(request)
    return valid


def _valid_pdf_request(
    request: SourceLocator,
    source_map: SourceMap,
    config: SourceAccessConfig,
    warnings: list[str],
) -> bool:
    if source_map.source_type != "pdf":
        warnings.append(f"Dropped PDF page request for non-PDF source: {request.source_id}.")
        return False
    page_numbers = {
        unit.pdf_page_start
        for unit in source_map.units
        if unit.unit_type == "pdf_page" and unit.pdf_page_start is not None
    }
    start = request.pdf_page_start
    end = request.pdf_page_end or start
    if start is None and request.printed_page_label:
        start = _pdf_page_for_label(source_map, request.printed_page_label)
        end = start
    if start is None or end is None:
        warnings.append("Dropped PDF source request without physical pdf_page_start.")
        return False
    if start < 1 or end < start:
        warnings.append(f"Dropped invalid PDF page request: {start}-{end}.")
        return False
    page_count = end - start + 1
    if page_count > config.max_pdf_pages_per_request:
        warnings.append(
            f"Dropped oversized PDF page request {start}-{end}; max_pdf_pages_per_request="
            f"{config.max_pdf_pages_per_request}."
        )
        return False
    missing = [page for page in range(start, end + 1) if page not in page_numbers]
    if missing:
        warnings.append(f"Dropped PDF page request with missing stored pages: {missing}.")
        return False
    return True


def _pdf_page_for_label(source_map: SourceMap, label: str) -> int | None:
    target = label.strip().lower()
    for unit in source_map.units:
        if unit.printed_page_start and unit.printed_page_start.strip().lower() == target:
            return unit.pdf_page_start
    return None
