from __future__ import annotations

from essay_writer.agent_tools.schemas import WorkProducer


class ExplodingLLMClient:
    def chat_json(self, *args, **kwargs):
        raise AssertionError("Agent Tool Mode must not call LLMClient.chat_json")


def main_agent() -> WorkProducer:
    return WorkProducer(type="main_agent", role="orchestrator", name=None)
