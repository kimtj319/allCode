"""Safety sanitizers for model-backed route decisions."""

from __future__ import annotations

from allCode.agent.prompt_constraints import PromptConstraints
from allCode.agent.router import RouteKind, RoutingDecision, ToolCapability


def read_only_needs_workspace_tools(
    constraints: PromptConstraints,
    local_workspace_request: bool,
    capabilities: set[ToolCapability],
) -> bool:
    return bool(
        constraints.workspace_evidence_requested
        or constraints.path_hints
        or local_workspace_request
        or capabilities.intersection({"read_file", "search_workspace"})
    )


def sanitize_read_only_route(
    route: RoutingDecision,
    *,
    constraints: PromptConstraints,
    local_workspace_request: bool,
) -> RoutingDecision:
    if not route.read_only_requested:
        return route
    if constraints.answer_artifact_hint and not constraints.path_hints and not local_workspace_request:
        flags = set(route.flags)
        flags.add("read_only_requested")
        flags.add("answer_artifact")
        return route.model_copy(
            update={
                "kind": "answer",
                "tool_capabilities": set(),
                "workflow_hint": "direct_answer",
                "flags": flags,
                "read_only_requested": True,
                "requires_tools": False,
                "requires_mutation": False,
                "requires_shell": False,
                "requires_validation": False,
                "requires_external_knowledge": False,
            }
        )
    capabilities = set(route.tool_capabilities)
    capabilities.difference_update({"mutate_file", "delete_file", "run_shell", "run_validation"})
    flags = set(route.flags)
    flags.add("read_only_requested")
    flags.discard("requires_validation")
    if local_workspace_request:
        capabilities.discard("web_search")
    needs_workspace_tools = bool(
        read_only_needs_workspace_tools(constraints, local_workspace_request, capabilities)
        or route.target_hint
        or (route.kind in {"inspect", "modify", "operate"} and route.requires_tools and "web_search" not in capabilities)
    )
    if needs_workspace_tools:
        kind: RouteKind = "inspect"
        capabilities.update({"read_file", "search_workspace"})
    elif "web_search" in capabilities and not local_workspace_request:
        kind = "inspect"
    else:
        kind = "answer"
        capabilities.clear()
    return route.model_copy(
        update={
            "kind": kind,
            "tool_capabilities": capabilities,
            "workflow_hint": "none",
            "flags": flags,
            "read_only_requested": True,
            "requires_tools": kind == "inspect" or bool(capabilities),
            "requires_mutation": False,
            "requires_shell": False,
            "requires_validation": False,
            "requires_external_knowledge": bool("web_search" in capabilities and not local_workspace_request),
        }
    )
