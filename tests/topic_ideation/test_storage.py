from __future__ import annotations

from essay_writer.topic_ideation.schema import CandidateTopic, RejectedTopic, TopicIdeationRound
from essay_writer.topic_ideation.storage import TopicRoundStore
from tests.task_spec._tmp import LocalTempDir


def test_topic_round_store_lists_rounds_in_order() -> None:
    with LocalTempDir() as tmp_path:
        store = TopicRoundStore(tmp_path / "topic_store")
        store.save_round(_round(2, "second"))
        store.save_round(_round(1, "first"))

        rounds = store.list_rounds("job1")

    assert [round_.round_number for round_ in rounds] == [1, 2]
    assert [round_.candidates[0].title for round_ in rounds] == ["first", "second"]


def test_topic_round_store_saves_rejected_topics() -> None:
    with LocalTempDir() as tmp_path:
        store = TopicRoundStore(tmp_path / "topic_store")
        rejected = RejectedTopic(
            job_id="job1",
            round_id="job1-topic-round-001",
            topic_id="topic_001",
            title="Too broad",
            reason="I want a narrower topic.",
        )

        store.save_rejected_topic(rejected)
        loaded = store.list_rejected_topics("job1")

    assert loaded == [rejected]


def _round(round_number: int, title: str) -> TopicIdeationRound:
    return TopicIdeationRound(
        id=f"job1-topic-round-{round_number:03d}",
        job_id="job1",
        task_spec_id="task1",
        round_number=round_number,
        user_instruction=None,
        previous_topic_ids=[],
        candidates=[
            CandidateTopic(
                id=f"topic_{round_number:03d}",
                title=title,
                research_question="Question?",
                tentative_thesis_direction="Thesis.",
                rationale="Rationale.",
            )
        ],
    )
