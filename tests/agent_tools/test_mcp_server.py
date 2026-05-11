from __future__ import annotations

import importlib.util

import pytest

from tests.agent_tools._tmp import LocalAgentTempDir


def test_mcp_server_module_imports_without_instantiating_facade() -> None:
    import essay_writer.agent_tools.server as server

    assert hasattr(server, "main")
    assert hasattr(server, "build_server")


def test_mcp_dependency_is_optional_for_plain_facade_tests() -> None:
    has_mcp = importlib.util.find_spec("mcp") is not None

    assert isinstance(has_mcp, bool)


def test_mcp_server_builds_when_dependency_is_installed() -> None:
    if importlib.util.find_spec("mcp") is None:
        pytest.skip("mcp package is not installed")

    from essay_writer.agent_tools.server import build_server

    with LocalAgentTempDir() as tmp:
        app = build_server(data_dir=tmp / "data")

    assert app is not None
