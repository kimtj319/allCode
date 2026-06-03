"""Lightweight tool argument validation against registered tool definitions."""

from __future__ import annotations

from typing import Any

from allCode.core.models import ToolCall
from allCode.tools.base import ToolDefinition

HARMLESS_EXTRA_ARGUMENTS = {
    "thought",
    "reasoning",
    "rationale",
    "explanation",
    "comment",
    "notes",
}


def strip_harmless_extra_arguments(call: ToolCall, definition: ToolDefinition) -> ToolCall:
    """Remove provider-added explanatory fields while preserving real schema errors."""

    parameters = definition.parameters or {}
    if parameters.get("type") != "object" or parameters.get("additionalProperties") is not False:
        return call
    properties = parameters.get("properties", {})
    if not isinstance(properties, dict):
        return call
    arguments = dict(call.arguments)
    changed = False
    for key in list(arguments):
        if key in properties:
            continue
        if key in HARMLESS_EXTRA_ARGUMENTS:
            arguments.pop(key, None)
            changed = True
    return call.model_copy(update={"arguments": arguments}) if changed else call


def validate_tool_arguments(call: ToolCall, definition: ToolDefinition) -> str | None:
    """Return a schema error string when a tool call misses required arguments."""

    parameters = definition.parameters or {}
    if parameters.get("type") != "object":
        return None
    arguments = call.arguments
    required = [str(item) for item in parameters.get("required", []) if str(item)]
    missing = [name for name in required if name not in arguments or arguments.get(name) is None]
    if missing:
        return f"Missing required argument(s) for {call.name}: {', '.join(missing)}."
    properties = parameters.get("properties", {})
    if isinstance(properties, dict):
        unexpected = [name for name in arguments if name not in properties]
        if unexpected and parameters.get("additionalProperties") is False:
            return f"Unexpected argument(s) for {call.name}: {', '.join(sorted(unexpected))}."
        for name, schema in properties.items():
            if name not in arguments or not isinstance(schema, dict):
                continue
            if arguments[name] is None and name not in required:
                continue
            error = _type_error(name, arguments[name], schema)
            if error:
                return f"Invalid argument for {call.name}: {error}."
    for path_key in ("file_path", "path"):
        if path_key in required and not str(arguments.get(path_key, "")).strip():
            return f"Missing required argument(s) for {call.name}: {path_key}."
    return None


def _type_error(name: str, value: Any, schema: dict[str, Any]) -> str | None:
    expected = schema.get("type")
    if expected is None:
        return None
    if isinstance(expected, list):
        return None if any(_matches_type(value, item) for item in expected) else f"{name} must match one of {expected}"
    return None if _matches_type(value, expected) else f"{name} must be {expected}"


def _matches_type(value: Any, expected: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True
