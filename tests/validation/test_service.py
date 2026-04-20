from __future__ import annotations

import json

from llm.mock import MockLLMClient
from essay_writer.research.schema import ResearchNote
from essay_writer.sources.schema import SourceCard
from essay_writer.task_spec.schema import TaskSpecification
from essay_writer.validation.prompts import VALIDATION_SYSTEM_PROMPT
from essay_writer.validation.service import ValidationService


_MINIMAL_LLM_RESPONSE = {
    "unsupported_claims": [],
    "citation_issues": [],
    "rubric_scores": [],
    "assignment_fit": {"passes": True, "explanation": "Essay addresses the prompt."},
    "length_check": {"actual_words": 50, "target_words": None, "passes": True},
    "style_issues": [],
    "revision_suggestions": [],
    "overall_quality": 0.75,
}

_TASK_SPEC = TaskSpecification(id="task1", version=1, raw_text="Write an argumentative essay.")


def test_service_runs_deterministic_checks_and_includes_in_report():
    draft = "In conclusion, we should leverage the tapestry of evidence — it is pivotal."
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    report = ValidationService(client).validate(draft, draft_id="d1", task_spec=_TASK_SPEC, evidence_map=[])

    assert report.deterministic.em_dash_count == 1
    assert report.deterministic.bad_conclusion_opener is True
    assert any(h.word == "leverage" for h in report.deterministic.tier1_vocab_hits)
    assert any(h.word == "pivotal" for h in report.deterministic.tier1_vocab_hits)


def test_service_passes_deterministic_findings_to_llm():
    draft = "This is important \u2014 noted."
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    ValidationService(client).validate(draft, draft_id="d1", task_spec=_TASK_SPEC, evidence_map=[])

    user_msg = client.calls[0]["user"]
    context = json.loads(user_msg.split("\n\n", 1)[1].split("<essay_draft>")[0].strip())
    assert context["deterministic_issues"]["em_dash_count"] == 1


def test_service_passes_evidence_map_to_llm():
    notes = [
        ResearchNote(
            id="n1", source_id="src1", chunk_id="src1-c001",
            page_start=4, page_end=4,
            claim="Temperatures rose 2C.",
            quote=None,
            paraphrase="Global temperatures rose by 2 degrees Celsius.",
            relevance="Supports climate change argument.",
            supports_topic=True, evidence_type="statistic", confidence=0.9,
        ),
        ResearchNote(
            id="n2", source_id="src1", chunk_id="src1-c002",
            page_start=7, page_end=7,
            claim="Arctic ice declined 40%.",
            quote="Ice declined by 40%",
            paraphrase="Arctic sea ice coverage fell by approximately 40%.",
            relevance="Supports evidence of warming.",
            supports_topic=True, evidence_type="statistic", confidence=0.85,
        ),
    ]
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    ValidationService(client).validate("Some draft.", draft_id="d1", task_spec=_TASK_SPEC, evidence_map=notes)

    user_msg = client.calls[0]["user"]
    context = json.loads(user_msg.split("\n\n", 1)[1].split("<essay_draft>")[0].strip())
    assert len(context["evidence_map"]) == 2
    assert context["evidence_map"][0]["note_id"] == "n1"
    assert context["evidence_map"][0]["chunk_id"] == "src1-c001"
    assert context["evidence_map"][0]["page_start"] == 4
    assert context["evidence_map"][1]["quote"] == "Ice declined by 40%"


def test_service_passes_source_metadata_and_bibliography_candidates_to_llm():
    card = SourceCard(
        source_id="src1",
        title="Urban Heat",
        source_type="pdf",
        page_count=12,
        extraction_method="pypdf",
        brief_summary="Heat and housing.",
        citation_metadata={"author": "Jane Smith", "year": "2023", "file_name": "urban_heat.pdf"},
    )
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    report = ValidationService(client).validate(
        "Some draft.",
        draft_id="d1",
        task_spec=_TASK_SPEC,
        evidence_map=[],
        bibliography_candidates=["Smith, Jane. Urban Heat. 2023."],
        source_cards=[card],
    )

    user_msg = client.calls[0]["user"]
    context = json.loads(user_msg.split("\n\n", 1)[1].split("<essay_draft>")[0].strip())
    assert context["known_source_metadata"][0]["source_id"] == "src1"
    assert context["known_source_metadata"][0]["citation_metadata"]["author"] == "Jane Smith"
    assert context["bibliography_candidates"] == ["Smith, Jane. Urban Heat. 2023."]
    assert context["metadata_citation_warnings"] == []
    assert report.metadata_citation_warnings == []


def test_service_warns_when_bibliography_candidate_does_not_match_source_metadata():
    card = SourceCard(
        source_id="src1",
        title="Urban Heat",
        source_type="pdf",
        page_count=12,
        extraction_method="pypdf",
        brief_summary="Heat and housing.",
        citation_metadata={"author": "Jane Smith", "year": "2023"},
    )
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    report = ValidationService(client).validate(
        "Some draft.",
        draft_id="d1",
        task_spec=_TASK_SPEC,
        evidence_map=[],
        bibliography_candidates=["Doe, John. Unrelated Book. 2020."],
        source_cards=[card],
    )

    assert len(report.metadata_citation_warnings) == 1
    assert report.metadata_citation_warnings[0].source_id == "src1"
    assert report.passes is True


def test_service_passes_task_spec_fields_to_llm():
    task_spec = TaskSpecification(
        id="task1",
        version=1,
        raw_text="Write a 1000-word argumentative essay.",
        essay_type="argumentative",
        academic_level="undergraduate",
        target_length=1000,
        citation_style="MLA",
        rubric=["Argument clarity", "Source use"],
    )
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    ValidationService(client).validate("Some draft.", draft_id="d1", task_spec=task_spec, evidence_map=[])

    user_msg = client.calls[0]["user"]
    context = json.loads(user_msg.split("\n\n", 1)[1].split("<essay_draft>")[0].strip())
    assert context["task_spec"]["essay_type"] == "argumentative"
    assert context["task_spec"]["citation_style"] == "MLA"
    assert context["task_spec"]["target_length"] == 1000
    assert "Argument clarity" in context["task_spec"]["rubric"]


def test_service_includes_draft_text_in_llm_message():
    draft = "The oceans are warming at an unprecedented rate."
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    ValidationService(client).validate(draft, draft_id="d1", task_spec=_TASK_SPEC, evidence_map=[])

    user_msg = client.calls[0]["user"]
    assert draft in user_msg


def test_service_uses_correct_system_prompt():
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    ValidationService(client).validate("Some draft.", draft_id="d1", task_spec=_TASK_SPEC, evidence_map=[])

    assert client.calls[0]["system"] == VALIDATION_SYSTEM_PROMPT


def test_service_returns_structured_report_with_llm_judgment():
    llm_response = {
        "unsupported_claims": [{"claim": "GDP grew 10%.", "paragraph": 2}],
        "citation_issues": [{"description": "Missing citation for statistic.", "severity": "high"}],
        "rubric_scores": [{"criterion": "Argument clarity", "score": 0.8, "note": "Clear thesis."}],
        "assignment_fit": {"passes": True, "explanation": "Addresses the prompt well."},
        "length_check": {"actual_words": 800, "target_words": 1000, "passes": False},
        "style_issues": [{"issue_type": "argument_flat", "description": "Middle paragraphs restate thesis."}],
        "revision_suggestions": ["Expand evidence in paragraph 3."],
        "overall_quality": 0.7,
    }
    client = MockLLMClient(responses=[llm_response])

    report = ValidationService(client).validate("Some draft.", draft_id="d1", task_spec=_TASK_SPEC, evidence_map=[])

    assert report.draft_id == "d1"
    assert report.task_spec_id == "task1"
    assert len(report.llm_judgment.unsupported_claims) == 1
    assert report.llm_judgment.unsupported_claims[0].claim == "GDP grew 10%."
    assert report.llm_judgment.unsupported_claims[0].paragraph == 2
    assert report.llm_judgment.citation_issues[0].severity == "high"
    assert report.llm_judgment.rubric_scores[0].criterion == "Argument clarity"
    assert report.llm_judgment.rubric_scores[0].score == 0.8
    assert report.llm_judgment.assignment_fit.passes is True
    assert report.llm_judgment.length_check.passes is False
    assert report.llm_judgment.length_check.actual_words == 800
    assert report.llm_judgment.style_issues[0].issue_type == "argument_flat"
    assert report.llm_judgment.revision_suggestions == ["Expand evidence in paragraph 3."]
    assert report.llm_judgment.overall_quality == 0.7


def test_service_report_passes_when_no_issues():
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    report = ValidationService(client).validate(
        "The oceans are warming at an unprecedented rate.",
        draft_id="d1",
        task_spec=_TASK_SPEC,
        evidence_map=[],
    )

    assert report.passes is True


def test_service_report_fails_when_unsupported_claims():
    llm_response = {**_MINIMAL_LLM_RESPONSE, "unsupported_claims": [{"claim": "X.", "paragraph": 1}]}
    client = MockLLMClient(responses=[llm_response])

    report = ValidationService(client).validate("Some draft.", draft_id="d1", task_spec=_TASK_SPEC, evidence_map=[])

    assert report.passes is False


def test_service_prompt_version_stored_in_report():
    client = MockLLMClient(responses=[_MINIMAL_LLM_RESPONSE])

    report = ValidationService(client, prompt_version="validation-v2").validate(
        "Some draft.", draft_id="d1", task_spec=_TASK_SPEC, evidence_map=[]
    )

    assert report.prompt_version == "validation-v2"
