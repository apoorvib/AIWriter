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
FORBIDDEN_FUNCTION_IMPORTS = {
    "essay_writer.sources.summary.build_source_card",
}


def _agent_tool_paths() -> list[Path]:
    return sorted(AGENT_TOOLS_ROOT.rglob("*.py"))


def _forbidden_imports_in_source(source: str, *, filename: str = "<source>") -> list[str]:
    offenders: list[str] = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_import(alias.name) or alias.name in FORBIDDEN_FUNCTION_IMPORTS:
                    offenders.append(f"{filename}:{alias.name}")
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                candidate = f"{module}.{alias.name}" if module else alias.name
                if (
                    _is_forbidden_import(module)
                    or _is_forbidden_import(candidate)
                    or candidate in FORBIDDEN_FUNCTION_IMPORTS
                ):
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
    offenders: list[str] = []
    for path in _agent_tool_paths():
        source = path.read_text(encoding="utf-8")
        offenders.extend(_forbidden_calls_in_source(source, filename=str(path)))

    assert offenders == []


def test_forbidden_call_detection_allows_source_card_user_message_helper() -> None:
    source = "source_summary.build_source_card_user_message(source, excerpts, 1200)"

    assert _forbidden_calls_in_source(source) == []


def test_forbidden_call_detection_detects_build_source_card_call() -> None:
    source = "source_summary.build_source_card(source, chunks, llm_client=client)"

    assert "<source>:source_summary.build_source_card" in _forbidden_calls_in_source(source)


def test_forbidden_call_detection_detects_task_spec_parser_constructor_parse() -> None:
    source = "TaskSpecParser(llm_client=client).parse(raw_text)"

    assert "<source>:TaskSpecParser.parse" in _forbidden_calls_in_source(source)


def test_forbidden_call_detection_detects_task_spec_parser_variable_parse() -> None:
    source = "\n".join(
        [
            "parser = TaskSpecParser(llm_client=client)",
            "parser.parse(raw_text)",
        ]
    )

    assert "<source>:parser.parse" in _forbidden_calls_in_source(source)


def test_forbidden_call_detection_detects_direct_task_spec_parser_parse() -> None:
    source = "TaskSpecParser.parse(parser, raw_text)"

    assert "<source>:TaskSpecParser.parse" in _forbidden_calls_in_source(source)


def test_forbidden_call_detection_allows_unrelated_parse_call() -> None:
    source = "\n".join(
        [
            "parser = OtherParser()",
            "parser.parse(raw_text)",
        ]
    )

    assert _forbidden_calls_in_source(source) == []


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


def _forbidden_calls_in_source(source: str, *, filename: str = "<source>") -> list[str]:
    offenders: list[str] = []
    tree = ast.parse(source, filename=filename)
    task_spec_parser_vars = _task_spec_parser_variables(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_task_spec_parser_constructor_parse(node):
            offenders.append(f"{filename}:TaskSpecParser.parse")
            continue
        if _is_task_spec_parser_variable_parse(node, task_spec_parser_vars):
            call_name = _dotted_call_name(node.func)
            offenders.append(f"{filename}:{call_name}")
            continue
        dotted_name = _dotted_call_name(node.func)
        if dotted_name is None:
            continue
        if _is_forbidden_call(dotted_name):
            offenders.append(f"{filename}:{dotted_name}")
    return offenders


def _task_spec_parser_variables(tree: ast.AST) -> set[str]:
    variables: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_task_spec_parser_constructor(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    variables.add(target.id)
        if isinstance(node, ast.AnnAssign) and _is_task_spec_parser_constructor(node.value):
            if isinstance(node.target, ast.Name):
                variables.add(node.target.id)
    return variables


def _is_task_spec_parser_constructor_parse(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "parse"
        and isinstance(func.value, ast.Call)
        and _is_task_spec_parser_constructor(func.value)
    )


def _is_task_spec_parser_variable_parse(node: ast.Call, variables: set[str]) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "parse"
        and isinstance(func.value, ast.Name)
        and func.value.id in variables
    )


def _is_task_spec_parser_constructor(node: ast.AST | None) -> bool:
    if not isinstance(node, ast.Call):
        return False
    dotted_name = _dotted_call_name(node.func)
    return dotted_name == "TaskSpecParser" or dotted_name.endswith(".TaskSpecParser")


def _dotted_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_call_name(node.value)
        if parent is None:
            return node.attr
        return f"{parent}.{node.attr}"
    return None


def _is_forbidden_call(dotted_name: str) -> bool:
    if dotted_name in FORBIDDEN_CALLS:
        return True
    if dotted_name.endswith(".chat_json"):
        return True
    if dotted_name.endswith(".build_source_card"):
        return True
    return any(dotted_name.endswith(f".{name}") for name in FORBIDDEN_CALLS if "." in name)
