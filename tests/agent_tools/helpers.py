from __future__ import annotations

from essay_writer.agent_tools.schemas import WorkProducer


class ExplodingLLMClient:
    def chat_json(self, *args, **kwargs):
        raise AssertionError("Agent Tool Mode must not call LLMClient.chat_json")


def main_agent() -> WorkProducer:
    return WorkProducer(type="main_agent", role="orchestrator", name=None)


def dispatched_subagent(facade, work_packet_id: str, role: str) -> WorkProducer:
    """Convenience helper for tests: dispatch a subagent and return a
    ``WorkProducer`` carrying the issued token, ready to pass to
    ``submit_work_result``. Used to satisfy mechanism (B)'s delegation
    gate without each test having to wire the token plumbing inline.
    """
    dispatch = facade.dispatch_subagent(
        work_packet_id=work_packet_id,
        role=role,
    )
    if not dispatch.ok:
        raise AssertionError(
            f"dispatch_subagent failed: {dispatch.error}"
        )
    return WorkProducer(
        type="subagent",
        role=role,
        name=f"{role}-test",
        subagent_token=str(dispatch.data["subagent_token"]),
    )
