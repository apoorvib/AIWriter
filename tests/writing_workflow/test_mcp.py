from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from essay_writer.writing.facade import WritingToolFacade
from essay_writer.writing.mcp import WRITING_TOOL_NAMES, register_writing_tools
from tests.agent_tools._tmp import LocalAgentTempDir


class _FakeApp:
    """Minimal stand-in for FastMCP that records @app.tool() registrations."""

    def __init__(self) -> None:
        self.registered: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.registered[fn.__name__] = fn
            return fn

        return decorator


def _facade(tmp) -> WritingToolFacade:
    return WritingToolFacade.from_data_dir(tmp, enforce_attention_challenge=False)


def test_register_writing_tools_registers_every_declared_tool() -> None:
    with LocalAgentTempDir() as tmp:
        app = _FakeApp()
        register_writing_tools(app, _facade(tmp))
    assert set(app.registered) == set(WRITING_TOOL_NAMES)


def test_registered_tools_are_thin_wrappers_over_the_facade() -> None:
    with LocalAgentTempDir() as tmp:
        app = _FakeApp()
        register_writing_tools(app, _facade(tmp))
        started = app.registered["start_writing_run"]("Write a launch email")
        run_id = started["data"]["writing_run_id"]
        progress = app.registered["get_writing_progress"](run_id)
    assert started["ok"] is True
    assert started["data"]["progress"]["next_required_step"] == "brief"
    assert progress["data"]["progress"]["next_required_step"] == "brief"


def test_tool_names_use_writing_prefix_not_ambiguous_short_names() -> None:
    # Guards against collisions with the essay surface (e.g. start_run/start_agent_run).
    assert "start_writing_run" in WRITING_TOOL_NAMES
    assert "start_run" not in WRITING_TOOL_NAMES
    for name in WRITING_TOOL_NAMES:
        assert "writing" in name or name in {
            "dispatch_writing_reviewer", "answer_writing_questions"
        }


def test_writing_mcp_surface_imports_no_provider_llm_client() -> None:
    forbidden_roots = {"llm", "backend.deps"}
    for relative in ("essay_writer/writing/mcp.py", "essay_writer/writing/facade.py"):
        tree = ast.parse(Path(relative).read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                top = module.split(".", 1)[0]
                assert top != "llm", f"{relative} imports provider LLM module {module!r}"
                assert module != "backend.deps", f"{relative} imports {module!r}"


def test_build_server_exposes_writing_tools_alongside_essay_tools() -> None:
    if importlib.util.find_spec("mcp") is None:
        pytest.skip("mcp package is not installed")

    from essay_writer.agent_tools.server import build_server

    with LocalAgentTempDir() as tmp:
        app = build_server(data_dir=tmp / "data")
        names = {tool.name for tool in app._tool_manager.list_tools()}
    assert set(WRITING_TOOL_NAMES) <= names
    # The essay surface is still registered on the same server.
    assert "start_agent_run" in names
    assert "start_writing_run" in names
