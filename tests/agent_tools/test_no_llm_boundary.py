from __future__ import annotations

import ast
from pathlib import Path


AGENT_TOOLS_ROOT = Path("essay_writer") / "agent_tools"

FORBIDDEN_IMPORTS = {
    "backend.deps",
    "llm.factory",
    "llm.logging_client",
    "llm.adapters",
    "llm.adapters.claude",
    "llm.adapters.openai_",
    "llm.adapters.gemini",
}

FORBIDDEN_CALLS = {
    "SourceIngestionService.ingest",
    "TaskSpecParser.parse",
    "TopicIdeationService.generate",
    "FinalTopicResearchService.extract",
    "ThesisOutlineService.create_outline",
    "DraftService.generate",
    "DraftRevisionService.revise",
    "ValidationService.validate",
    "build_source_card",
    "chat_json",
}


def _agent_tool_paths() -> list[Path]:
    return sorted(AGENT_TOOLS_ROOT.rglob("*.py"))


def _forbidden_imports_in_source(source: str, *, filename: str = "<source>") -> list[str]:
    offenders: list[str] = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_import(alias.name):
                    offenders.append(f"{filename}:{alias.name}")
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                candidate = f"{module}.{alias.name}" if module else alias.name
                if _is_forbidden_import(module) or _is_forbidden_import(candidate):
                    offenders.append(f"{filename}:{candidate}")
    return offenders


def _is_forbidden_import(name: str) -> bool:
    return name in FORBIDDEN_IMPORTS or name.startswith("llm.adapters.")


def test_agent_tools_do_not_import_api_backed_wiring() -> None:
    offenders: list[str] = []
    for path in _agent_tool_paths():
        offenders.extend(
            _forbidden_imports_in_source(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
        )

    assert offenders == []


def test_agent_tools_do_not_call_llm_backed_service_methods() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in _agent_tool_paths())
    offenders = [name for name in sorted(FORBIDDEN_CALLS) if name in source]

    assert offenders == []


def test_boundary_tests_cover_current_agent_tool_modules() -> None:
    scanned_paths = {path.name for path in _agent_tool_paths()}

    assert {"facade.py", "stores.py", "run_store.py", "work_store.py"} <= scanned_paths


def test_import_boundary_detects_equivalent_from_import_forms() -> None:
    source = "\n".join(
        [
            "from backend import deps",
            "from llm import factory",
            "from llm import logging_client",
            "from llm import adapters",
            "from llm.adapters import claude",
        ]
    )

    offenders = _forbidden_imports_in_source(source)

    assert "<source>:backend.deps" in offenders
    assert "<source>:llm.factory" in offenders
    assert "<source>:llm.logging_client" in offenders
    assert "<source>:llm.adapters" in offenders
    assert "<source>:llm.adapters.claude" in offenders
