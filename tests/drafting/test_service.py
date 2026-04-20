from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.jobs.schema import EssayJob
from essay_writer.outlining.schema import OutlineSection, ThesisOutline
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.topic_ideation.schema import SelectedTopic
from essay_writer.research.schema import EvidenceGroup, EvidenceMap, ResearchNote
from essay_writer.drafting.prompts import DRAFTING_SYSTEM_PROMPT
from essay_writer.drafting.service import DraftService


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_JOB = EssayJob(id="job1", task_spec_id="task1")

_TASK_SPEC = TaskSpecification(
    id="task1",
    version=1,
    raw_text="Write a 1000-word argumentative essay on urban heat and housing policy.",
    essay_type="argumentative",
    academic_level="undergraduate",
    target_length=1000,
    length_unit="words",
    citation_style="MLA",
    rubric=["Argument clarity", "Source integration", "Counterargument"],
)

_TOPIC = SelectedTopic(
    job_id="job1",
    round_id="round_001",
    topic_id="topic_001",
    title="Urban Heat and Housing Justice",
    research_question="How does urban heat disproportionately affect low-income renters?",
    tentative_thesis_direction="Cities should treat heat adaptation as a housing justice issue.",
)

_NOTE = ResearchNote(
    id="note_001",
    source_id="src1",
    chunk_id="src1-chunk-0001",
    page_start=5,
    page_end=5,
    claim="Low-income renters face 2.3x more heat days than wealthier households.",
    quote="Renters in the bottom income quartile experience 2.3x more heat days.",
    paraphrase="Research shows renters with low incomes face far more heat exposure.",
    relevance="Directly supports the core thesis about heat inequality.",
    supports_topic=True,
    evidence_type="statistic",
    confidence=0.9,
)

_GROUP = EvidenceGroup(
    id="group_001",
    label="Heat Exposure Inequality",
    purpose="thesis_support",
    note_ids=["note_001"],
    synthesis="Studies confirm heat exposure correlates strongly with income level.",
)

_EVIDENCE_MAP = EvidenceMap(
    id="evidence_map_v001",
    job_id="job1",
    selected_topic_id="topic_001",
    research_question=_TOPIC.research_question,
    thesis_direction=_TOPIC.tentative_thesis_direction,
    notes=[_NOTE],
    evidence_groups=[_GROUP],
    gaps=["No data on cooling center access"],
    conflicts=[],
    source_ids=["src1"],
)

_MINIMAL_LLM_RESPONSE = {
    "content": "Urban heat has become a defining challenge of modern city life.",
    "section_source_map": [
        {
            "section_id": "s1",
            "heading": "Introduction",
            "note_ids": ["note_001"],
            "source_ids": ["src1"],
        }
    ],
    "bibliography_candidates": ["Smith, J. (2023). Urban Heat. Climate Press."],
    "known_weak_spots": [],
}


def _service(response: dict | None = None) -> tuple[DraftService, MockLLMClient]:
    client = MockLLMClient(responses=[response or _MINIMAL_LLM_RESPONSE])
    return DraftService(client), client


# ---------------------------------------------------------------------------
# Context / prompt content tests
# ---------------------------------------------------------------------------

def test_draft_service_passes_topic_fields_to_llm():
    service, client = _service()
    service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    ctx = _parse_context(client)
    assert ctx["selected_topic"]["topic_id"] == "topic_001"
    assert ctx["selected_topic"]["title"] == "Urban Heat and Housing Justice"
    assert ctx["selected_topic"]["research_question"] == _TOPIC.research_question
    assert ctx["selected_topic"]["thesis_direction"] == _TOPIC.tentative_thesis_direction


def test_draft_service_passes_task_spec_fields_to_llm():
    service, client = _service()
    service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    ctx = _parse_context(client)
    assert ctx["task_spec"]["essay_type"] == "argumentative"
    assert ctx["task_spec"]["citation_style"] == "MLA"
    assert ctx["task_spec"]["target_length"] == 1000
    assert "Argument clarity" in ctx["task_spec"]["rubric"]


def test_draft_service_passes_evidence_notes_to_llm():
    service, client = _service()
    service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    ctx = _parse_context(client)
    notes = ctx["evidence"]["notes"]
    assert len(notes) == 1
    assert notes[0]["id"] == "note_001"
    assert notes[0]["claim"] == _NOTE.claim
    assert notes[0]["paraphrase"] == _NOTE.paraphrase
    assert notes[0]["quote"] == _NOTE.quote
    assert notes[0]["source_id"] == "src1"
    assert notes[0]["page_start"] == 5


def test_draft_service_passes_evidence_groups_to_llm():
    service, client = _service()
    service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    ctx = _parse_context(client)
    groups = ctx["evidence"]["evidence_groups"]
    assert len(groups) == 1
    assert groups[0]["label"] == "Heat Exposure Inequality"
    assert groups[0]["purpose"] == "thesis_support"
    assert "note_001" in groups[0]["note_ids"]
    assert groups[0]["synthesis"] == _GROUP.synthesis


def test_draft_service_passes_gaps_to_llm():
    service, client = _service()
    service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    ctx = _parse_context(client)
    assert "No data on cooling center access" in ctx["evidence"]["gaps"]


def test_draft_service_passes_outline_to_llm_and_records_outline_id():
    service, client = _service()
    outline = ThesisOutline(
        id="thesis_outline_v001",
        job_id="job1",
        selected_topic_id="topic_001",
        research_plan_id="research_plan_v001",
        evidence_map_id="evidence_map_v001",
        version=1,
        working_thesis="Cities should treat heat adaptation as housing policy.",
        sections=[
            OutlineSection(
                id="section_001",
                heading="Introduction",
                purpose="introduce thesis",
                key_points=["Frame heat as housing policy."],
                note_ids=["note_001"],
                target_words=150,
            )
        ],
    )

    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP, outline=outline)
    ctx = _parse_context(client)

    assert ctx["outline"]["outline_id"] == "thesis_outline_v001"
    assert ctx["outline"]["working_thesis"].startswith("Cities")
    assert ctx["outline"]["sections"][0]["note_ids"] == ["note_001"]
    assert draft.outline_id == "thesis_outline_v001"


def test_draft_service_does_not_expose_index_paths():
    service, client = _service()
    service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    user_msg = client.calls[0]["user"]
    assert ".sqlite" not in user_msg
    assert ".json" not in user_msg


def test_draft_service_uses_correct_system_prompt():
    service, client = _service()
    service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert client.calls[0]["system"] == DRAFTING_SYSTEM_PROMPT


def test_draft_service_anti_ai_rules_in_system_prompt():
    assert "em dash" in DRAFTING_SYSTEM_PROMPT.lower() or "\u2014" in DRAFTING_SYSTEM_PROMPT
    assert "leverage" in DRAFTING_SYSTEM_PROMPT
    assert "delve" in DRAFTING_SYSTEM_PROMPT
    assert "In conclusion" in DRAFTING_SYSTEM_PROMPT or "in conclusion" in DRAFTING_SYSTEM_PROMPT.lower()


def test_draft_service_no_fabrication_rule_in_system_prompt():
    prompt_lower = DRAFTING_SYSTEM_PROMPT.lower()
    assert "fabricat" in prompt_lower or "do not invent" in prompt_lower


# ---------------------------------------------------------------------------
# Output / return value tests
# ---------------------------------------------------------------------------

def test_draft_service_returns_essay_draft_with_content():
    service, _ = _service()
    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert draft.content == "Urban heat has become a defining challenge of modern city life."


def test_draft_service_returns_section_source_map():
    service, _ = _service()
    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert len(draft.section_source_map) == 1
    assert draft.section_source_map[0].section_id == "s1"
    assert draft.section_source_map[0].heading == "Introduction"
    assert "note_001" in draft.section_source_map[0].note_ids
    assert "src1" in draft.section_source_map[0].source_ids


def test_draft_service_returns_bibliography_candidates():
    service, _ = _service()
    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert draft.bibliography_candidates == ["Smith, J. (2023). Urban Heat. Climate Press."]


def test_draft_service_records_known_weak_spots():
    response = {**_MINIMAL_LLM_RESPONSE, "known_weak_spots": ["Paragraph 3 lacks direct evidence."]}
    service, _ = _service(response)
    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert draft.known_weak_spots == ["Paragraph 3 lacks direct evidence."]


def test_draft_service_stores_job_id_and_topic_id():
    service, _ = _service()
    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert draft.job_id == "job1"
    assert draft.selected_topic_id == "topic_001"


def test_draft_service_sets_citation_style_from_task_spec():
    service, _ = _service()
    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert draft.citation_style == "MLA"


def test_draft_service_version_starts_at_one():
    service, _ = _service()
    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert draft.version == 1


def test_draft_service_prompt_version_stored():
    service = DraftService(MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE]), prompt_version="drafting-v2")
    draft = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert draft.prompt_version == "drafting-v2"


def test_draft_service_draft_id_is_unique():
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE, _MINIMAL_LLM_RESPONSE])
    service = DraftService(client)
    d1 = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    d2 = service.generate(_JOB, _TASK_SPEC, _TOPIC, _EVIDENCE_MAP)
    assert d1.id != d2.id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_context(client: MockLLMClient) -> dict:
    return json.loads(client.calls[0]["user"])
