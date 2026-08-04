"""Parity tests for the extracted work-payload validator.

The validator used to live in ``agent_tools/facade.py``; it now lives in
``agent_tools/schema_validation.py`` and is re-imported by the facade under its
historical private name. These tests exercise the shared function directly and
confirm the facade still routes through the same implementation.
"""
from __future__ import annotations

from essay_writer.agent_tools import facade as facade_module
from essay_writer.agent_tools.schema_validation import (
    error_result,
    error_result_with_next,
    validate_work_payload,
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "mode": {"type": "string", "enum": ["a", "b"]},
    },
    "required": ["name", "count"],
    "additionalProperties": False,
}


def test_facade_reuses_the_extracted_validator() -> None:
    # The facade alias is the extracted function itself, not a copy.
    assert facade_module._validate_work_payload is validate_work_payload
    assert facade_module._error_result is error_result
    assert facade_module._error_result_with_next is error_result_with_next


def test_valid_payload_returns_none() -> None:
    payload = {"name": "x", "count": 2, "tags": ["a"], "mode": "a"}
    assert validate_work_payload(payload, _SCHEMA, tool_name="t") is None


def test_missing_required_field_is_rejected() -> None:
    result = validate_work_payload({"name": "x"}, _SCHEMA, tool_name="t")
    assert result is not None and result.ok is False
    assert result.error is not None
    assert result.error.code == "work_result_payload_invalid"


def test_wrong_type_is_rejected() -> None:
    result = validate_work_payload(
        {"name": "x", "count": "two"}, _SCHEMA, tool_name="t"
    )
    assert result is not None and result.ok is False


def test_additional_property_is_rejected() -> None:
    result = validate_work_payload(
        {"name": "x", "count": 1, "extra": True}, _SCHEMA, tool_name="t"
    )
    assert result is not None and result.ok is False


def test_enum_violation_is_rejected() -> None:
    result = validate_work_payload(
        {"name": "x", "count": 1, "mode": "z"}, _SCHEMA, tool_name="t"
    )
    assert result is not None and result.ok is False


def test_error_result_shapes_a_tool_error() -> None:
    result = error_result("t", code="c", message="m", exc=ValueError("boom"))
    assert result.ok is False and result.tool_name == "t"
    assert result.error is not None and result.error.code == "c"
    assert result.error.detail["exception"] == "ValueError"
