"""Agent Tool Mode writing-style ingestion and prepare/commit tests."""
from __future__ import annotations

from pathlib import Path

from essay_writer.agent_tools.facade import AgentToolFacade
from essay_writer.agent_tools.schemas import WorkProducer
from essay_writer.agent_tools.stores import AgentStoreBundle
from pdf_pipeline.models import DocumentExtractionResult, PageText
from tests.agent_tools._tmp import LocalAgentTempDir
from tests.agent_tools.helpers import ExplodingLLMClient


def _valid_writing_style_payload() -> dict:
    return {
        "guidance": [
            "Prefer long compound sentences with conjunctions.",
            "Reach for specific concrete nouns; avoid abstractions.",
            "Use parenthetical asides rather than em dashes.",
            "Hedge sparingly; commit to a position.",
        ],
        "preferred_moves": ["paragraph that opens with a question"],
        "avoid_moves": ["wrapping every paragraph with a thesis restatement"],
        "lexical_habits": ["uses 'so' as a sentence opener"],
        "structural_habits": ["short paragraphs after long ones"],
        "anchor_excerpts": [
            {
                "sample_id": "sample-1",
                "excerpt_id": "ex01",
                "text": "Long passage that captures my normal academic voice on the page.",
                "role": "tone",
                "reason": "shows preference for plain copulas",
            }
        ],
        "warnings": [],
    }


class FakeExtractor:
    def __init__(self, result: DocumentExtractionResult) -> None:
        self.result = result
        self.calls: list[Path] = []

    def extract(self, document_path: str | Path) -> DocumentExtractionResult:
        self.calls.append(Path(document_path))
        return self.result


def _touch_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-pretend-for-fake-extractor")
    return path


def _extraction(sample_path: Path, text: str) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        source_path=str(sample_path),
        page_count=1,
        pages=[
            PageText(
                page_number=1,
                text=text,
                char_count=len(text),
                extraction_method="pypdf",
            )
        ],
    )


def test_agent_store_bundle_exposes_writing_style_stores() -> None:
    with LocalAgentTempDir() as tmp:
        bundle = AgentStoreBundle.from_data_dir(tmp)

        assert bundle.writing_style_sample_store is not None
        assert bundle.writing_style_content_store is not None
        assert Path(bundle.writing_style_sample_store.root) == tmp / "writing_style" / "samples"
        assert Path(bundle.writing_style_content_store.root) == tmp / "writing_style" / "content"


def test_ingest_writing_style_sample_persists_sample_without_llm() -> None:
    with LocalAgentTempDir() as tmp:
        sample_path = _touch_pdf(tmp / "my-essay.pdf")
        facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            document_reader=FakeExtractor(
                _extraction(
                    sample_path,
                    "Long passage that captures my normal academic voice on the page.",
                )
            ),
            llm_guard=ExplodingLLMClient(),
        )

        result = facade.ingest_writing_style_sample(str(sample_path))
        sample_id = result.data["sample_id"]
        sample_dir = tmp / "data" / "writing_style" / "samples" / sample_id
        sample_json_exists = (sample_dir / "sample.json").exists()
        cleaned_text_exists = (sample_dir / "cleaned_text.txt").exists()

    assert result.ok is True
    assert result.tool_name == "ingest_writing_style_sample"
    assert isinstance(sample_id, str) and sample_id.startswith("sample-")
    assert sample_json_exists
    assert cleaned_text_exists
    assert result.data["word_count"] > 0
    assert result.next_suggested_tools == ["prepare_writing_style_content"]


def test_ingest_writing_style_sample_rejects_missing_file() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.ingest_writing_style_sample(str(tmp / "does-not-exist.pdf"))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "writing_style_sample_not_found"


def test_ingest_writing_style_sample_rejects_unsupported_suffix() -> None:
    with LocalAgentTempDir() as tmp:
        bad_path = tmp / "sample.xyz"
        bad_path.write_text("anything", encoding="utf-8")
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.ingest_writing_style_sample(str(bad_path))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unsupported_writing_style_sample_type"


def _ingest_one_sample(facade: AgentToolFacade, tmp: Path, *, text: str, name: str = "my-essay") -> str:
    sample_path = _touch_pdf(tmp / f"{name}.pdf")
    facade.source_materializer._document_reader = FakeExtractor(_extraction(sample_path, text))
    return str(facade.ingest_writing_style_sample(str(sample_path)).data["sample_id"])


def test_prepare_writing_style_content_returns_work_packet_with_skill_prompt() -> None:
    with LocalAgentTempDir() as tmp:
        sample_path = _touch_pdf(tmp / "my-essay.pdf")
        facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            document_reader=FakeExtractor(
                _extraction(
                    sample_path,
                    "Long passage that captures my normal academic voice on the page.",
                )
            ),
            llm_guard=ExplodingLLMClient(),
        )
        ingest = facade.ingest_writing_style_sample(str(sample_path))
        sample_id = ingest.data["sample_id"]

        result = facade.prepare_writing_style_content([sample_id])

    assert result.ok is True
    assert result.tool_name == "prepare_writing_style_content"
    assert result.data["commit_tool"] == "commit_writing_style_content"
    assert result.data["work_packet_id"].startswith("workpkt_")
    assert "writing-style" in result.data["system_prompt"].lower() or "style" in result.data["system_prompt"].lower()
    schema = result.data["response_schema"]
    assert schema["type"] == "object"
    assert "guidance" in schema["properties"]
    assert "anchor_excerpts" in schema["properties"]
    assert result.next_suggested_tools == ["submit_work_result"]


def test_prepare_writing_style_content_rejects_missing_sample() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.prepare_writing_style_content(["sample-does-not-exist"])

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "writing_style_sample_not_found"


def test_prepare_writing_style_content_rejects_empty_sample_list() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")

        result = facade.prepare_writing_style_content([])

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "writing_style_sample_ids_empty"


def _seed_writing_style_packet(facade: AgentToolFacade, tmp: Path) -> tuple[str, str]:
    sample_path = _touch_pdf(tmp / "my-essay.pdf")
    facade.source_materializer._document_reader = FakeExtractor(
        _extraction(sample_path, "Long passage that captures my normal academic voice on the page.")
    )
    ingest = facade.ingest_writing_style_sample(str(sample_path))
    sample_id = ingest.data["sample_id"]
    prepared = facade.prepare_writing_style_content([sample_id])
    return sample_id, str(prepared.data["work_packet_id"])


def test_commit_writing_style_content_persists_content_and_returns_id() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(
            tmp / "data",
            llm_guard=ExplodingLLMClient(),
        )
        sample_id, packet_id = _seed_writing_style_packet(facade, tmp)
        payload = _valid_writing_style_payload()
        payload["anchor_excerpts"][0]["sample_id"] = sample_id

        submitted = facade.submit_work_result(
            packet_id,
            payload=payload,
            producer=WorkProducer(type="main_agent", role="orchestrator", name=None),
        )
        result = facade.commit_writing_style_content(
            work_result_id=str(submitted.data["work_result_id"]),
        )

    assert result.ok is True
    assert result.tool_name == "commit_writing_style_content"
    assert result.data["already_committed"] is False
    content_id = result.data["content_id"]
    assert isinstance(content_id, str) and content_id.startswith("style-")
    assert result.next_suggested_tools == ["attach_writing_style_to_job"]


def test_commit_writing_style_content_retry_returns_already_committed() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(
            tmp / "data", llm_guard=ExplodingLLMClient()
        )
        sample_id, packet_id = _seed_writing_style_packet(facade, tmp)
        payload = _valid_writing_style_payload()
        payload["anchor_excerpts"][0]["sample_id"] = sample_id

        submitted = facade.submit_work_result(
            packet_id,
            payload=payload,
            producer=WorkProducer(type="main_agent", role="orchestrator", name=None),
        )
        result_id = str(submitted.data["work_result_id"])
        first = facade.commit_writing_style_content(work_result_id=result_id)
        second = facade.commit_writing_style_content(work_result_id=result_id)

    assert first.ok is True
    assert second.ok is True
    assert first.data["already_committed"] is False
    assert second.data["already_committed"] is True
    assert first.data["content_id"] == second.data["content_id"]


def _seed_committed_writing_style_content(facade: AgentToolFacade, tmp: Path) -> tuple[list[str], str]:
    sample_id, packet_id = _seed_writing_style_packet(facade, tmp)
    payload = _valid_writing_style_payload()
    payload["anchor_excerpts"][0]["sample_id"] = sample_id
    submitted = facade.submit_work_result(
        packet_id,
        payload=payload,
        producer=WorkProducer(type="main_agent", role="orchestrator", name=None),
    )
    committed = facade.commit_writing_style_content(
        work_result_id=str(submitted.data["work_result_id"]),
    )
    return [sample_id], str(committed.data["content_id"])


def _seed_minimal_job(facade: AgentToolFacade) -> str:
    """Create a minimal EssayJob by going through the workflow path used by tests."""
    from essay_writer.task_spec.schema import TaskSpecification
    spec = TaskSpecification(
        id="task-1",
        version=1,
        raw_text="test assignment",
        essay_type="research",
        target_length=500,
        length_unit="words",
        academic_level="undergraduate",
        citation_style="APA",
    )
    facade.stores.task_store.save(spec)
    job = facade.stores.workflow.create_job(task_spec_id="task-1", source_ids=[])
    return job.id


def test_attach_writing_style_to_job_records_reference_on_job() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(
            tmp / "data", llm_guard=ExplodingLLMClient()
        )
        sample_ids, content_id = _seed_committed_writing_style_content(facade, tmp)
        job_id = _seed_minimal_job(facade)

        result = facade.attach_writing_style_to_job(job_id=job_id, content_id=content_id)
        job_after = facade.stores.workflow.load_job(job_id)

    assert result.ok is True
    assert result.tool_name == "attach_writing_style_to_job"
    assert result.data["job_id"] == job_id
    assert result.data["writing_style_content_id"] == content_id
    assert result.data["writing_style_sample_ids"] == sample_ids
    assert job_after.writing_style_content_id == content_id
    assert job_after.writing_style_sample_ids == sample_ids


def test_attach_writing_style_to_job_rejects_unknown_content_id() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(
            tmp / "data", llm_guard=ExplodingLLMClient()
        )
        job_id = _seed_minimal_job(facade)

        result = facade.attach_writing_style_to_job(
            job_id=job_id, content_id="style-does-not-exist"
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "writing_style_content_not_found"


def test_currently_callable_tools_lists_writing_style_surface() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        instructions = facade.get_harness_instructions()
        callable_tools = set(instructions.data["currently_callable_tools"])

    assert "ingest_writing_style_sample" in callable_tools
    assert "prepare_writing_style_content" in callable_tools
    assert "commit_writing_style_content" in callable_tools
    assert "attach_writing_style_to_job" in callable_tools


def test_prepare_draft_includes_writing_style_block_when_attached_to_job() -> None:
    from tests.agent_tools.test_outline_draft_validation_tools import (
        _seed_job_through_outline,
    )

    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_outline(facade)

        # baseline: no writing-style attached
        baseline = facade.prepare_draft("job1")
        baseline_blocks = baseline.data["prompt_blocks"]

        # attach writing-style content
        sample_ids, content_id = _seed_committed_writing_style_content(facade, tmp)
        facade.attach_writing_style_to_job(job_id="job1", content_id=content_id)

        prepared = facade.prepare_draft("job1")
        prepared_blocks = prepared.data["prompt_blocks"]
        prepared_text = "\n".join(block["text"] for block in prepared_blocks)

    assert baseline.ok is True
    assert prepared.ok is True
    assert len(baseline_blocks) == 1  # only cacheable static block
    assert len(prepared_blocks) == 2  # static + non-cacheable writing-style suffix
    assert prepared_blocks[0]["cacheable"] is True
    assert prepared_blocks[1]["cacheable"] is False
    assert "<writing_style_samples>" in prepared_text
    assert "style_guidance" in prepared_text


def test_prepare_style_revision_includes_writing_style_block_when_attached_to_job() -> None:
    from tests.agent_tools.test_outline_draft_validation_tools import (
        _seed_job_through_draft,
    )

    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(tmp / "data")
        _seed_job_through_draft(facade)
        sample_ids, content_id = _seed_committed_writing_style_content(facade, tmp)
        facade.attach_writing_style_to_job(job_id="job1", content_id=content_id)

        prepared = facade.prepare_style_revision("job1")
        prepared_blocks = prepared.data["prompt_blocks"]
        prepared_text = "\n".join(block["text"] for block in prepared_blocks)

    assert prepared.ok is True
    assert any(block["cacheable"] is False for block in prepared_blocks)
    assert "<writing_style_samples>" in prepared_text


def test_attach_writing_style_to_job_rejects_unknown_job() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(
            tmp / "data", llm_guard=ExplodingLLMClient()
        )
        _sample_ids, content_id = _seed_committed_writing_style_content(facade, tmp)

        result = facade.attach_writing_style_to_job(
            job_id="job-does-not-exist", content_id=content_id
        )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "job_not_found"


def test_commit_writing_style_content_rejects_wrong_packet_stage() -> None:
    with LocalAgentTempDir() as tmp:
        facade = AgentToolFacade.from_data_dir(
            tmp / "data", llm_guard=ExplodingLLMClient()
        )
        # use a source_card work_result_id — wrong stage
        sample_path = _touch_pdf(tmp / "my-essay.pdf")
        facade.source_materializer._document_reader = FakeExtractor(
            _extraction(sample_path, "Long passage that captures my normal academic voice.")
        )
        ingest = facade.ingest_writing_style_sample(str(sample_path))
        sample_id = ingest.data["sample_id"]
        prepared = facade.prepare_writing_style_content([sample_id])
        packet_id = str(prepared.data["work_packet_id"])

        result = facade.commit_writing_style_content(work_result_id="nonexistent")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "work_result_not_found"


def test_ingest_writing_style_sample_reuses_existing_sample_when_file_unchanged() -> None:
    with LocalAgentTempDir() as tmp:
        sample_path = _touch_pdf(tmp / "my-essay.pdf")
        text = "Long passage that captures my normal academic voice on the page."
        first_reader = FakeExtractor(_extraction(sample_path, text))
        facade = AgentToolFacade.from_data_dir(
            tmp / "data", document_reader=first_reader
        )
        first = facade.ingest_writing_style_sample(str(sample_path))

        second_reader = FakeExtractor(_extraction(sample_path, text))
        second_facade = AgentToolFacade.from_data_dir(
            tmp / "data", document_reader=second_reader
        )
        second = second_facade.ingest_writing_style_sample(str(sample_path))

    assert first.ok is True
    assert second.ok is True
    assert first.data["sample_id"] == second.data["sample_id"]

