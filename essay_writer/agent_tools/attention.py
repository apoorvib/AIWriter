"""Shared proof-of-attention challenge helpers (Gap 3).

A model-reasoning work packet can carry a one-time token appended to its
``system_prompt``; the model is told to echo the token in its JSON output. A
missing token on submit means the supplied system prompt was never read, so
the result is rejected. Both the essay facade and the generic writing facade
apply and verify the challenge through these two functions.
"""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

from essay_writer.agent_tools.schemas import WorkPacket

ATTENTION_CHECK_MARKER = "ATTENTION CHECK"


def build_attention_challenge(packet: WorkPacket) -> WorkPacket:
    """Return ``packet`` with a proof-of-attention token appended to its
    ``system_prompt`` and recorded in ``system_prompt_challenge``. A packet
    that already carries a challenge is returned unchanged."""
    if packet.system_prompt_challenge:
        return packet
    token = f"ATTN-{uuid4().hex[:12]}"
    footer = (
        "\n\n---\n"
        "ATTENTION CHECK (required): To confirm you have read this entire "
        f"system prompt, you MUST include the exact token {token} somewhere "
        "in your JSON output. Append it to a free-text string field such as "
        "a notes or self_check_notes array, or any existing string field. "
        "Outputs that omit this token will be rejected with "
        "system_prompt_not_honored, because a missing token indicates the "
        "system prompt was not actually read."
    )
    return replace(
        packet,
        system_prompt=packet.system_prompt + footer,
        system_prompt_challenge=token,
    )


def attention_challenge_satisfied(payload: dict[str, object], challenge: str) -> bool:
    """True when ``challenge`` appears anywhere in the serialized payload."""
    return challenge in json.dumps(payload, ensure_ascii=False)
