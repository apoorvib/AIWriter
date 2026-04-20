from __future__ import annotations

from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.schema import OutlineSection, ThesisOutline
from essay_writer.research.schema import EvidenceMap, ResearchNote
from essay_writer.research_planning.schema import ResearchPlan
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.schema import SelectedTopic


class ThesisOutlineService:
    def __init__(self, *, prompt_version: str = "thesis-outline-v1") -> None:
        self._prompt_version = prompt_version

    def create_outline(
        self,
        *,
        job: EssayJob,
        task_spec: TaskSpecification,
        selected_topic: SelectedTopic,
        research_plan: ResearchPlan,
        evidence_map: EvidenceMap,
        version: int = 1,
        model: str | None = None,
    ) -> ThesisOutline:
        sections = _sections(task_spec, evidence_map)
        return ThesisOutline(
            id=f"thesis_outline_v{version:03d}",
            job_id=job.id,
            selected_topic_id=selected_topic.topic_id,
            research_plan_id=research_plan.id,
            evidence_map_id=evidence_map.id,
            version=version,
            working_thesis=_working_thesis(selected_topic, evidence_map),
            sections=sections,
            prompt_version=self._prompt_version,
        )


def _working_thesis(selected_topic: SelectedTopic, evidence_map: EvidenceMap) -> str:
    thesis = evidence_map.thesis_direction.strip() or selected_topic.tentative_thesis_direction.strip()
    if thesis and thesis[-1] not in ".!?":
        thesis += "."
    return thesis or f"{selected_topic.title} can support a focused source-grounded argument."


def _sections(task_spec: TaskSpecification, evidence_map: EvidenceMap) -> list[OutlineSection]:
    sections: list[OutlineSection] = [
        OutlineSection(
            id="section_001",
            heading="Introduction",
            purpose="introduce topic and thesis",
            key_points=[evidence_map.research_question, evidence_map.thesis_direction],
            target_words=_target_words(task_spec, 0.14),
        )
    ]

    for group in evidence_map.evidence_groups:
        sections.append(
            OutlineSection(
                id=f"section_{len(sections) + 1:03d}",
                heading=group.label,
                purpose=group.purpose,
                key_points=[group.synthesis],
                note_ids=group.note_ids,
                target_words=_target_words(task_spec, 0.22),
            )
        )

    grouped_note_ids = {
        note_id
        for group in evidence_map.evidence_groups
        for note_id in group.note_ids
    }
    remaining_notes = [note for note in evidence_map.notes if note.id not in grouped_note_ids]
    if remaining_notes:
        sections.append(
            OutlineSection(
                id=f"section_{len(sections) + 1:03d}",
                heading="Additional Evidence",
                purpose="thesis_support",
                key_points=[_note_point(note) for note in remaining_notes[:6]],
                note_ids=[note.id for note in remaining_notes],
                target_words=_target_words(task_spec, 0.22),
            )
        )

    if evidence_map.conflicts:
        sections.append(
            OutlineSection(
                id=f"section_{len(sections) + 1:03d}",
                heading="Counterargument and Limits",
                purpose="counterargument",
                key_points=evidence_map.conflicts,
                target_words=_target_words(task_spec, 0.14),
            )
        )

    sections.append(
        OutlineSection(
            id=f"section_{len(sections) + 1:03d}",
            heading="Conclusion",
            purpose="synthesize argument",
            key_points=evidence_map.gaps or ["Return to the thesis and source-grounded stakes."],
            target_words=_target_words(task_spec, 0.1),
        )
    )
    return sections


def _note_point(note: ResearchNote) -> str:
    return note.claim or note.paraphrase


def _target_words(task_spec: TaskSpecification, ratio: float) -> int | None:
    if task_spec.length_unit != "words" or task_spec.target_length is None:
        return None
    return max(80, int(task_spec.target_length * ratio))
