from __future__ import annotations

import pytest

from essay_writer.agent_tools import work_store as work_store_module
from essay_writer.agent_tools.id_utils import content_hash
from essay_writer.agent_tools.schemas import (
    DelegationHint,
    PromptBlock,
    SourcePacketBundle,
    WorkPacket,
)
from essay_writer.agent_tools.work_store import AgentWorkStore

from ._tmp import LocalAgentTempDir
from .helpers import main_agent


def _packet() -> WorkPacket:
    return WorkPacket(
        work_packet_id="workpkt_job1_outline_001",
        stage="outline",
        scope="job:job1",
        instructions="Create an outline.",
        system_prompt="Outline system prompt",
        prompt_blocks=[PromptBlock(text="{}", cacheable=False)],
        response_schema={"type": "object"},
        context={"job_id": "job1"},
        artifact_refs={"job_id": "job1"},
        commit_tool="commit_outline",
        delegation=DelegationHint(),
    )


def test_work_store_saves_packet_result_and_commit_link() -> None:
    with LocalAgentTempDir() as tmp:
        store = AgentWorkStore(tmp / "agent_work")
        packet = _packet()

        store.save_packet(packet)
        loaded_packet = store.load_packet(packet.work_packet_id)
        first_result = store.submit_result(
            packet.work_packet_id,
            payload={"outline": ["Intro", "Body", "Conclusion"]},
            producer=main_agent(),
        )
        duplicate_result = store.submit_result(
            packet.work_packet_id,
            payload={"outline": ["Intro", "Body", "Conclusion"]},
            producer=main_agent(),
        )
        commit = store.save_commit(
            scope="job:job1",
            stage="outline",
            work_packet_id=packet.work_packet_id,
            work_result_id=first_result.work_result_id,
            artifact_refs={"outline_id": "thesis_outline_v001"},
        )
        rewritten_commit = store.save_commit(
            scope="job:job1",
            stage="outline",
            work_packet_id=packet.work_packet_id,
            work_result_id=first_result.work_result_id,
            artifact_refs={"outline_id": "thesis_outline_v002"},
        )

        loaded_commit = store.load_commit(commit.commit_id)

    assert loaded_packet.stage == "outline"
    assert duplicate_result.work_result_id == first_result.work_result_id
    assert loaded_commit.artifact_refs["outline_id"] == "thesis_outline_v001"
    assert rewritten_commit.commit_id != commit.commit_id


def test_submit_result_handles_short_hash_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    with LocalAgentTempDir() as tmp:
        store = AgentWorkStore(tmp / "agent_work")
        packet = store.save_packet(_packet())
        monkeypatch.setattr(work_store_module, "short_hash", lambda payload: "collision")

        first = store.submit_result(
            packet.work_packet_id,
            payload={"outline": ["A"]},
            producer=main_agent(),
        )
        second = store.submit_result(
            packet.work_packet_id,
            payload={"outline": ["B"]},
            producer=main_agent(),
        )

    assert first.work_result_id != second.work_result_id
    assert second.work_result_id.endswith(content_hash({"outline": ["B"]}).split(":", 1)[1])


def test_save_commit_rejects_same_id_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    with LocalAgentTempDir() as tmp:
        store = AgentWorkStore(tmp / "agent_work")
        packet = store.save_packet(_packet())
        result = store.submit_result(
            packet.work_packet_id,
            payload={"outline": ["A"]},
            producer=main_agent(),
        )
        monkeypatch.setattr(work_store_module, "short_hash", lambda payload: "collision")

        store.save_commit(
            scope="job:job1",
            stage="outline",
            work_packet_id=packet.work_packet_id,
            work_result_id=result.work_result_id,
            artifact_refs={"outline_id": "thesis_outline_v001"},
        )
        with pytest.raises(ValueError, match="commit id collision"):
            store.save_commit(
                scope="job:job1",
                stage="outline",
                work_packet_id=packet.work_packet_id,
                work_result_id=result.work_result_id,
                artifact_refs={"outline_id": "thesis_outline_v002"},
            )


def test_work_store_saves_source_packet_bundle() -> None:
    with LocalAgentTempDir() as tmp:
        store = AgentWorkStore(tmp / "agent_work")
        bundle = SourcePacketBundle(
            source_packet_bundle_id="spbundle_job1_research_001",
            scope="job:job1",
            packet_payloads=[
                {
                    "packet_id": "src1-c1",
                    "source_id": "src1",
                    "text": "Evidence text.",
                }
            ],
            warnings=[],
        )

        store.save_source_packet_bundle(bundle)
        loaded = store.load_source_packet_bundle(bundle.source_packet_bundle_id)

    assert loaded.packet_payloads[0]["packet_id"] == "src1-c1"
