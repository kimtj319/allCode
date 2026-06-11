"""Inspect-stage tool-call normalization helpers."""

from __future__ import annotations

from allCode.agent.inspect_targets import normalize_target
from allCode.core.models import ToolCall


def normalize_inspect_stage_call(tool_call: ToolCall, inspect_stage) -> ToolCall:
    tool_call = _normalize_broad_inspect_discovery(tool_call, inspect_stage)
    targets = list(getattr(inspect_stage, "target_paths", []) or [])
    if not targets:
        return tool_call
    if tool_call.name not in {"source_overview", "list_tree", "glob_files", "read_file", "source_probe"}:
        return tool_call
    target = _first_non_file_target(targets) if tool_call.name in {"source_overview", "list_tree", "glob_files"} else _first_file_target(targets)
    if not target:
        return tool_call
    allowed = set(getattr(inspect_stage, "allowed_tool_names", set()) or set())
    arguments = dict(tool_call.arguments)
    if tool_call.name in {"source_overview", "list_tree"}:
        current = str(arguments.get("path") or "").strip()
        if _should_replace_with_target(current, target):
            arguments["path"] = target
        if tool_call.name == "source_overview" and getattr(inspect_stage, "stage", "") == "source_discovery":
            _raise_min_int_argument(arguments, "max_files", 80)
            _raise_min_int_argument(arguments, "max_symbols", 120)
            _raise_min_int_argument(arguments, "max_depth", 3)
    elif tool_call.name == "glob_files":
        current_path = str(arguments.get("path") or "").strip()
        current_pattern = str(arguments.get("pattern") or "").strip()
        if _should_replace_with_target(current_path, target):
            arguments["path"] = target
        if not current_pattern:
            arguments["pattern"] = "**/*"
    elif tool_call.name == "read_file":
        current = str(arguments.get("file_path") or arguments.get("path") or "").strip()
        if current in {"", "."}:
            arguments["file_path"] = target
    elif tool_call.name == "source_probe":
        current = str(arguments.get("path") or arguments.get("file_path") or "").strip()
        strict_representative_probe = allowed == {"source_probe"}
        if current in {"", "."} or (strict_representative_probe and _should_replace_with_target(current, target)):
            arguments["path"] = target
    if arguments == tool_call.arguments:
        return tool_call
    return tool_call.model_copy(update={"arguments": arguments})


def _normalize_broad_inspect_discovery(tool_call: ToolCall, inspect_stage) -> ToolCall:
    allowed = set(getattr(inspect_stage, "allowed_tool_names", set()) or set())
    if allowed != {"source_overview"} or tool_call.name not in {"list_tree", "glob_files"}:
        return tool_call
    arguments = dict(tool_call.arguments)
    target = str(arguments.get("path") or "").strip()
    if not target:
        targets = list(getattr(inspect_stage, "target_paths", []) or [])
        target = _first_non_file_target(targets)
    overview_args: dict[str, object] = {"path": target or "."}
    if "max_entries" in arguments and "max_files" not in arguments:
        overview_args["max_files"] = arguments["max_entries"]
    if "max_depth" in arguments:
        overview_args["max_depth"] = arguments["max_depth"]
    return tool_call.model_copy(update={"name": "source_overview", "arguments": overview_args})


def _should_replace_with_target(current: str, target: str) -> bool:
    current_norm = normalize_target(current)
    target_norm = normalize_target(target)
    if not target_norm:
        return False
    if current_norm in {"", "."}:
        return True
    if current_norm == target_norm:
        return False
    if target_norm.startswith(f"{current_norm}/"):
        return True
    if current_norm.startswith(f"{target_norm}/"):
        return False
    return True


def _first_non_file_target(targets: list[str]) -> str:
    for target in targets:
        if target and "." not in target.rsplit("/", 1)[-1]:
            return target
    return targets[0] if targets else ""


def _first_file_target(targets: list[str]) -> str:
    for target in targets:
        name = target.rsplit("/", 1)[-1]
        if "." in name:
            return target
    return ""


def _raise_min_int_argument(arguments: dict, key: str, minimum: int) -> None:
    try:
        current = int(arguments.get(key, 0))
    except (TypeError, ValueError):
        current = 0
    if current < minimum:
        arguments[key] = minimum
