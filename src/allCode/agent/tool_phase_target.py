"""Phase-gate target checks for mutation tool calls."""

from __future__ import annotations

from allCode.agent.phase_gate import PhaseToolGate, target_matches_any
from allCode.core.models import ToolCall


def phase_target_denial(
    tool_call: ToolCall,
    *,
    phase_gate: PhaseToolGate | None,
    inspect_stage=None,
    workspace_root: str,
) -> str | None:
    """Return a schema-denial reason when a phase requires a specific target."""

    inspect_denial = inspect_target_denial(tool_call, inspect_stage=inspect_stage, workspace_root=workspace_root)
    if inspect_denial is not None:
        return inspect_denial
    return mutation_phase_target_denial(tool_call, phase_gate=phase_gate, workspace_root=workspace_root)


def mutation_phase_target_denial(
    tool_call: ToolCall,
    *,
    phase_gate: PhaseToolGate | None,
    workspace_root: str,
) -> str | None:
    if phase_gate is None or phase_gate.phase != "test_authoring_required":
        return None
    if tool_call.name not in {"patch_file", "write_file"}:
        return None
    required_targets = list(phase_gate.required_target_paths)
    if not required_targets:
        return None
    target = tool_file_target(tool_call)
    if not target:
        return "This phase requires updating the missing test artifact target, but the tool call did not include a file path."
    if target_matches_any(target, required_targets, workspace_root=workspace_root):
        return None
    return (
        "This phase requires updating the missing test artifact target. "
        f"Use one of these target paths: {', '.join(required_targets[:3])}."
    )


def inspect_target_denial(tool_call: ToolCall, *, inspect_stage, workspace_root: str) -> str | None:
    if inspect_stage is None or getattr(inspect_stage, "stage", "") not in {"source_discovery", "targeted_read"}:
        return None
    if tool_call.name not in {"source_probe", "read_file", "source_overview"}:
        return None
    required_targets = [path for path in getattr(inspect_stage, "target_paths", []) if path]
    if not required_targets:
        return None
    target = tool_file_target(tool_call)
    if not target:
        return "This inspect stage requires a target path, but the tool call did not include one."
    if target_matches_any(target, required_targets, workspace_root=workspace_root):
        return None
    return (
        "This inspect stage requires one of these target paths: "
        f"{', '.join(required_targets[:4])}."
    )


def tool_file_target(tool_call: ToolCall) -> str:
    """Extract the path-like target argument used by file mutation tools."""

    for key in ("file_path", "path", "target_path"):
        value = tool_call.arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
