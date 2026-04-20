from __future__ import annotations

from essay_writer.drafting.schema import EssayDraft
from essay_writer.exporting.schema import FinalEssayExport
from essay_writer.jobs.schema import EssayJob
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.validation.schema import ValidationReport


class FinalExportService:
    def create_markdown_export(
        self,
        *,
        job: EssayJob,
        task_spec: TaskSpecification,
        draft: EssayDraft,
        validation: ValidationReport,
    ) -> FinalEssayExport:
        validation_report_id = job.validation_report_id or f"{validation.draft_id}:latest"
        title = task_spec.assignment_title or "Final Essay"
        content = _markdown_content(title, draft, validation)
        return FinalEssayExport(
            id=f"final_export_{draft.version:03d}",
            job_id=job.id,
            draft_id=draft.id,
            validation_report_id=validation_report_id,
            export_format="markdown",
            content=content,
            source_map=[
                {
                    "section_id": section.section_id,
                    "heading": section.heading,
                    "note_ids": section.note_ids,
                    "source_ids": section.source_ids,
                }
                for section in draft.section_source_map
            ],
        )


def _markdown_content(title: str, draft: EssayDraft, validation: ValidationReport) -> str:
    lines = [
        f"# {title}",
        "",
        draft.content.strip(),
        "",
        "## Source Map",
    ]
    if draft.section_source_map:
        for section in draft.section_source_map:
            note_text = ", ".join(section.note_ids) if section.note_ids else "none"
            source_text = ", ".join(section.source_ids) if section.source_ids else "none"
            lines.append(f"- {section.heading or section.section_id}: notes {note_text}; sources {source_text}")
    else:
        lines.append("- No section-level source map was provided.")
    lines.extend(
        [
            "",
            "## Validation",
            f"- Passes: {validation.passes}",
            f"- Overall quality: {validation.llm_judgment.overall_quality:.2f}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
