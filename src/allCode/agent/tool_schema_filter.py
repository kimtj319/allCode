"""Tool schema exposure and provider-neutral validation aliases."""

from __future__ import annotations

from allCode.core.models import ToolCall
from allCode.llm.settings import ToolSchema

READ_ONLY_BLOCKED_TOOL_NAMES = {"write_file", "patch_file", "delete_path", "run_command", "run_tests"}


class ToolSchemaFilter:
    def __init__(self, *, registry, policy) -> None:
        self._registry = registry
        self._policy = policy

    def schemas_for_routing(
        self,
        routing,
        *,
        suppress_validation: bool = False,
        only_mutation: bool = False,
        only_validation: bool = False,
        include_validation_probe: bool = False,
        allowed_only: set[str] | None = None,
    ) -> list[ToolSchema]:
        definitions = self._registry.definitions()
        allowed_names = self._policy.allowed_registered_tool_names(routing, definitions)
        if getattr(routing, "read_only_requested", False):
            allowed_names = {name for name in allowed_names if name not in READ_ONLY_BLOCKED_TOOL_NAMES}
        if suppress_validation:
            allowed_names = {name for name in allowed_names if name != "run_tests"}
        if only_mutation:
            mutation_names = {"patch_file", "write_file"}
            if include_validation_probe:
                mutation_names.add("run_tests")
            allowed_names = {name for name in allowed_names if name in mutation_names}
        if only_validation:
            allowed_names = {name for name in allowed_names if name == "run_tests"}
        if allowed_only is not None:
            allowed_names = {name for name in allowed_names if name in allowed_only}
        return [
            ToolSchema(
                name=definition.name,
                description=definition.description,
                parameters=definition.parameters,
            )
            for definition in definitions
            if definition.name in allowed_names
        ]


def normalize_tool_call_for_routing(tool_call: ToolCall, routing) -> ToolCall:
    tool_call = _normalize_argument_aliases(tool_call)
    if tool_call.name in {"run_validation", "run_test"} and routing.requires_validation:
        return tool_call.model_copy(update={"name": "run_tests"})
    if tool_call.name != "run_command" or not routing.requires_validation:
        return tool_call
    command = str(tool_call.arguments.get("command", "")).strip().lower()
    if not looks_like_validation_command(command):
        return tool_call
    return tool_call.model_copy(update={"name": "run_tests"})


def _normalize_argument_aliases(tool_call: ToolCall) -> ToolCall:
    if tool_call.name != "read_file":
        return tool_call
    arguments = dict(tool_call.arguments)
    changed = False
    for alias, canonical in (("line_start", "start_line"), ("line_end", "end_line")):
        if alias in arguments and canonical not in arguments:
            arguments[canonical] = arguments.pop(alias)
            changed = True
    return tool_call.model_copy(update={"arguments": arguments}) if changed else tool_call


def looks_like_validation_command(command: str) -> bool:
    validation_markers = (
        "pytest",
        "python -m pytest",
        "unittest",
        "npm test",
        "npm run test",
        "cargo test",
        "go test",
        "gradle test",
        "./gradlew test",
        "mvn test",
    )
    return any(marker in command for marker in validation_markers)
