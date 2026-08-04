from __future__ import annotations

from dataclasses import replace

from essay_writer.agent_tools.schemas import WorkProducer
from essay_writer.writing.facade import WritingToolFacade
from essay_writer.writing.schema import (
    DeliverableSpec, ResearchPolicy, SkillSelection, WriteMode, WritingBrief,
)
from tests.agent_tools._tmp import LocalAgentTempDir


def _facade(tmp) -> WritingToolFacade:
    return WritingToolFacade.from_data_dir(tmp, enforce_attention_challenge=False)


def _start(facade, *, research_policy="auto"):
    started = facade.start_writing_run(
        "Write a detailed blog with current facts", mode="detailed",
        research_policy=research_policy,
    )
    return str(started.data["writing_run_id"])


def _seed_brief(facade, run_id, *, research_needed=True):
    brief = WritingBrief(
        brief_id=f"{run_id}-brief-v1", writing_run_id=run_id, version=1,
        mode=WriteMode.DETAILED, purpose="Announce", audience="readers",
        deliverables=[DeliverableSpec("d1", "blog", "Announce")],
        selected_skills=[SkillSelection("blog", "1", "sha256:a")],
        research_needed=research_needed,
    )
    facade.stores.briefs.save(brief)
    facade.stores.runs.update(
        replace(facade.stores.runs.load(run_id), brief_id=brief.brief_id)
    )
    return brief


def _research_payload(**overrides) -> dict:
    payload = {
        "sources": [
            {
                "source_id": "s1", "title": "Market Report", "url": "https://example.com/a",
                "publisher": "Example", "published_at": "2026-01-01",
                "accessed_at": "2026-07-05",
            }
        ],
        "facts": [
            {
                "fact_id": "f1", "claim": "The market grew 10% in 2026",
                "source_ids": ["s1"], "confidence": "high", "short_quote": None,
            }
        ],
        "conflicts": [],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def _run_research(facade, run_id, payload):
    prepared = facade.prepare_writing_research(run_id)
    submitted = facade.submit_writing_result(
        str(prepared.data["work_packet_id"]), payload,
        producer=WorkProducer(type="main_agent"),
    )
    return facade.commit_writing_research(str(submitted.data["work_result_id"]))


def test_prepare_research_refused_when_policy_off() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, research_policy="off")
        _seed_brief(facade, run_id)
        result = facade.prepare_writing_research(run_id)
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "research_disabled"


def test_prepare_research_ready_when_required_even_if_brief_says_no() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade, research_policy="required")
        _seed_brief(facade, run_id, research_needed=False)
        result = facade.prepare_writing_research(run_id)
    assert result.ok
    assert result.data["stage"] == "writing_research"
    assert "search" in result.data["instructions"].lower()


def test_commit_research_persists_and_advances_to_plan() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        committed = _run_research(facade, run_id, _research_payload())
        assert committed.ok
        assert facade.stores.runs.load(run_id).research_id
    # Detailed run with research done now needs a plan.
    assert committed.data["progress"]["next_required_step"] == "plan"


def test_commit_rejects_non_http_url() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        payload = _research_payload(sources=[{
            "source_id": "s1", "title": "Local", "url": "file:///etc/passwd",
            "publisher": None, "published_at": None, "accessed_at": "2026-07-05",
        }])
        committed = _run_research(facade, run_id, payload)
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "invalid_source_url"


def test_commit_rejects_fact_without_source() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        payload = _research_payload(facts=[{
            "fact_id": "f1", "claim": "Unsupported", "source_ids": [],
            "confidence": "low", "short_quote": None,
        }])
        committed = _run_research(facade, run_id, payload)
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "fact_without_source"


def test_commit_rejects_fact_with_unknown_source() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        payload = _research_payload(facts=[{
            "fact_id": "f1", "claim": "Claim", "source_ids": ["ghost"],
            "confidence": "low", "short_quote": None,
        }])
        committed = _run_research(facade, run_id, payload)
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "fact_source_unknown"


def test_commit_rejects_overlong_quote() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        long_quote = " ".join(f"word{i}" for i in range(26))
        payload = _research_payload(facts=[{
            "fact_id": "f1", "claim": "Claim", "source_ids": ["s1"],
            "confidence": "high", "short_quote": long_quote,
        }])
        committed = _run_research(facade, run_id, payload)
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "quote_too_long"


def test_commit_rejects_facts_without_disclosed_sources() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        payload = _research_payload(sources=[], facts=[{
            "fact_id": "f1", "claim": "Claim", "source_ids": ["s1"],
            "confidence": "high", "short_quote": None,
        }])
        committed = _run_research(facade, run_id, payload)
    assert committed.ok is False
    assert committed.error is not None
    assert committed.error.code == "research_sources_undisclosed"


def test_commit_dedupes_duplicate_sources_by_url() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        payload = _research_payload(sources=[
            {"source_id": "s1", "title": "A", "url": "https://example.com/a",
             "publisher": None, "published_at": "2026-01-01", "accessed_at": "2026-07-05"},
            {"source_id": "s2", "title": "A dup", "url": "https://example.com/a",
             "publisher": None, "published_at": "2026-01-01", "accessed_at": "2026-07-05"},
        ], facts=[
            {"fact_id": "f1", "claim": "Claim", "source_ids": ["s2"],
             "confidence": "high", "short_quote": None},
        ])
        committed = _run_research(facade, run_id, payload)
        assert committed.ok
        research = facade.stores.research.load_latest(run_id)
    # The duplicate URL collapses to one source; the fact remaps to it.
    assert len(research.sources) == 1
    assert research.facts[0].source_ids == ["s1"]


def test_commit_warns_on_source_without_date() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        payload = _research_payload(sources=[{
            "source_id": "s1", "title": "Undated", "url": "https://example.com/a",
            "publisher": None, "published_at": None, "accessed_at": "2026-07-05",
        }])
        committed = _run_research(facade, run_id, payload)
        assert committed.ok
        research = facade.stores.research.load_latest(run_id)
    assert any("date" in w.lower() for w in research.warnings)


def test_commit_research_is_idempotent() -> None:
    with LocalAgentTempDir() as tmp:
        facade = _facade(tmp)
        run_id = _start(facade)
        _seed_brief(facade, run_id)
        prepared = facade.prepare_writing_research(run_id)
        submitted = facade.submit_writing_result(
            str(prepared.data["work_packet_id"]), _research_payload(),
            producer=WorkProducer(type="main_agent"),
        )
        first = facade.commit_writing_research(str(submitted.data["work_result_id"]))
        second = facade.commit_writing_research(str(submitted.data["work_result_id"]))
    assert first.ok and second.ok
    assert first.data["research_id"] == second.data["research_id"]
