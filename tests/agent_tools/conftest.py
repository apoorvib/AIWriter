"""Test configuration for the agent-tools suite.

Two production-default enforcements are flipped OFF by default for the
broad suite, because most tests call tools without threading every
production concern:

- Gap 3 (``enforce_attention_challenge``): every model-reasoning packet
  gets a proof-of-attention token in its system_prompt that the payload
  must echo. Hand-written test payloads do not carry it.
- Gap H1 (``require_agent_run``): stateful tools refuse calls that omit
  ``agent_run_id``. Many tests deliberately call tools without a run.
- Fix #1 (``require_anti_ai_audit``): prepare_validation refuses until an
  anti-AI audit is committed. Many tests drive draft -> validation
  directly without running the audit stage.

Tests that specifically exercise these construct the facade with the
flag set to ``True`` explicitly; ``setdefault`` below does not override an
explicit value, so those tests are unaffected.
"""
from __future__ import annotations

import pytest

from essay_writer.agent_tools import facade as _facade_mod


@pytest.fixture(autouse=True)
def _production_enforcements_off_by_default(monkeypatch):
    original = _facade_mod.AgentToolFacade.from_data_dir.__func__

    def patched(cls, data_dir, **kwargs):
        kwargs.setdefault("enforce_attention_challenge", False)
        kwargs.setdefault("require_agent_run", False)
        kwargs.setdefault("require_anti_ai_audit", False)
        return original(cls, data_dir, **kwargs)

    monkeypatch.setattr(
        _facade_mod.AgentToolFacade,
        "from_data_dir",
        classmethod(patched),
    )
    yield
