"""Shared work-payload schema validation and tool-result error builders.

Extracted from ``agent_tools/facade.py`` so both the essay facade and the
generic writing facade validate submitted work payloads through one
implementation instead of a copy. The essay facade re-imports these under its
historical private names, so its behavior is unchanged.
"""

from __future__ import annotations

from essay_writer.agent_tools.schemas import ToolError, ToolResult


def error_result(
    tool_name: str,
    *,
    code: str,
    message: str,
    exc: Exception,
) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=tool_name,
        error=ToolError(
            code=code,
            message=message,
            detail={"exception": type(exc).__name__},
        ),
    )


def error_result_with_next(
    tool_name: str,
    *,
    code: str,
    message: str,
    exc: Exception,
    next_suggested_tools: list[str],
) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=tool_name,
        error=ToolError(
            code=code,
            message=message,
            detail={"exception": type(exc).__name__},
        ),
        next_suggested_tools=list(next_suggested_tools),
    )


def validate_work_payload(
    payload: dict[str, object],
    schema: dict[str, object],
    *,
    tool_name: str,
) -> ToolResult | None:
    try:
        import jsonschema  # type: ignore[import-not-found]
    except ImportError:
        fallback_error = _validate_with_local_schema_subset(payload, schema, path="$")
        if fallback_error is None:
            return None
        code, message = fallback_error
        return error_result(
            tool_name,
            code=code,
            message=message,
            exc=ValueError(message),
        )

    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        return error_result(
            tool_name,
            code="work_result_payload_invalid",
            message=f"work result payload does not match response_schema: {exc.message}",
            exc=exc,
        )
    except jsonschema.SchemaError as exc:
        return error_result(
            tool_name,
            code="work_result_schema_invalid",
            message=f"work packet response_schema is invalid: {exc.message}",
            exc=exc,
        )
    return None


def _validate_with_local_schema_subset(
    value: object,
    schema: dict[str, object],
    *,
    path: str,
) -> tuple[str, str] | None:
    supported = {"type", "required", "properties", "additionalProperties", "items", "enum"}
    unsupported = sorted(set(schema) - supported)
    if unsupported:
        return (
            "work_result_schema_validator_unavailable",
            "response_schema uses unsupported keywords without jsonschema installed; "
            "install `.[agent-tools]` to validate this packet",
        )
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        type_names = [item for item in schema_type if isinstance(item, str)]
        if len(type_names) != len(schema_type):
            return _unsupported_schema_subset()
        if value is None and "null" in type_names:
            return None
        validation_errors: list[tuple[str, str]] = []
        for type_name in [item for item in type_names if item != "null"]:
            narrowed = dict(schema)
            narrowed["type"] = type_name
            error = _validate_with_local_schema_subset(value, narrowed, path=path)
            if error is None:
                return None
            validation_errors.append(error)
        if any(code == "work_result_schema_validator_unavailable" for code, _ in validation_errors):
            return _unsupported_schema_subset()
        return (
            "work_result_payload_invalid",
            f"{path} must match one of: {', '.join(type_names)}",
        )
    if schema_type == "object":
        if not isinstance(value, dict):
            return ("work_result_payload_invalid", f"{path} must be an object")
        required = schema.get("required", [])
        if not isinstance(required, list):
            return _unsupported_schema_subset()
        missing = [str(key) for key in required if str(key) not in value]
        if missing:
            return (
                "work_result_payload_invalid",
                f"{path} is missing required fields: {', '.join(missing)}",
            )
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return _unsupported_schema_subset()
        additional = schema.get("additionalProperties", True)
        if not isinstance(additional, (bool, dict)):
            return _unsupported_schema_subset()
        property_names = {str(key) for key in properties}
        extra = sorted(str(key) for key in value if str(key) not in property_names)
        if additional is False and extra:
            return (
                "work_result_payload_invalid",
                f"{path} has unsupported additional fields: {', '.join(extra)}",
            )
        for key, item in value.items():
            key_str = str(key)
            if key_str in properties:
                subschema = properties[key_str]
                if not isinstance(subschema, dict):
                    return _unsupported_schema_subset()
                error = _validate_with_local_schema_subset(
                    item,
                    subschema,
                    path=f"{path}.{key_str}",
                )
                if error is not None:
                    return error
            elif isinstance(additional, dict):
                error = _validate_with_local_schema_subset(
                    item,
                    additional,
                    path=f"{path}.{key_str}",
                )
                if error is not None:
                    return error
        return None
    if schema_type == "string":
        if not isinstance(value, str):
            return ("work_result_payload_invalid", f"{path} must be a string")
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            allowed = ", ".join(str(item) for item in enum_values)
            return ("work_result_payload_invalid", f"{path} must be one of: {allowed}")
        return None
    if schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return ("work_result_payload_invalid", f"{path} must be an integer")
        return None
    if schema_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return ("work_result_payload_invalid", f"{path} must be a number")
        return None
    if schema_type == "boolean":
        if not isinstance(value, bool):
            return ("work_result_payload_invalid", f"{path} must be a boolean")
        return None
    if schema_type == "null":
        if value is not None:
            return ("work_result_payload_invalid", f"{path} must be null")
        return None
    if schema_type == "array":
        if not isinstance(value, list):
            return ("work_result_payload_invalid", f"{path} must be an array")
        items = schema.get("items", {})
        if not isinstance(items, dict):
            return _unsupported_schema_subset()
        for idx, item in enumerate(value):
            error = _validate_with_local_schema_subset(item, items, path=f"{path}[{idx}]")
            if error is not None:
                return error
        return None
    return _unsupported_schema_subset()


def _unsupported_schema_subset() -> tuple[str, str]:
    return (
        "work_result_schema_validator_unavailable",
        "response_schema uses unsupported validation keywords without jsonschema installed; "
        "install `.[agent-tools]` to validate this packet",
    )
