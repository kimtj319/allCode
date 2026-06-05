"""Answer-route tool policy normalization."""

from __future__ import annotations

from typing import Literal

from allCode.agent.prompt_constraints import PromptConstraints
from allCode.agent.router import RoutingDecision, ToolCapability
from allCode.core.models import CoreModel

AnswerToolMode = Literal["not_answer", "direct", "web_only"]


class AnswerPolicyDecision(CoreModel):
    mode: AnswerToolMode
    tool_capabilities: set[ToolCapability]
    requires_external_knowledge: bool
    reason: str


def decide_answer_policy(
    route: RoutingDecision,
    *,
    constraints: PromptConstraints,
    local_workspace_request: bool,
) -> AnswerPolicyDecision:
    """Decide tool exposure for an already route-validated answer route."""

    if route.kind != "answer":
        return AnswerPolicyDecision(
            mode="not_answer",
            tool_capabilities=set(route.tool_capabilities),
            requires_external_knowledge=route.requires_external_knowledge,
            reason="Route is not an answer route.",
        )
    external_requested = bool(
        (constraints.external_knowledge_hint or route.requires_external_knowledge)
        and not constraints.no_external_network
        and not local_workspace_request
    )
    if external_requested:
        return AnswerPolicyDecision(
            mode="web_only",
            tool_capabilities={"web_search"},
            requires_external_knowledge=True,
            reason="Current or external evidence is required; expose web evidence only.",
        )
    return AnswerPolicyDecision(
        mode="direct",
        tool_capabilities=set(),
        requires_external_knowledge=False,
        reason="Stable answer route; no tools are exposed.",
    )


def apply_answer_policy(
    route: RoutingDecision,
    *,
    constraints: PromptConstraints,
    local_workspace_request: bool,
) -> RoutingDecision:
    """Normalize answer routes after route validation has resolved contradictions."""

    decision = decide_answer_policy(route, constraints=constraints, local_workspace_request=local_workspace_request)
    if decision.mode == "not_answer":
        return route
    workflow_hint = "external_research" if decision.mode == "web_only" else "none"
    flags = set(route.flags)
    if decision.requires_external_knowledge:
        flags.add("requires_external_knowledge")
    else:
        flags.discard("requires_external_knowledge")
    reason = route.reason
    suffix = f"; answer policy: {decision.reason}"
    if suffix not in reason:
        reason = f"{reason}{suffix}"
    return route.model_copy(
        update={
            "tool_capabilities": decision.tool_capabilities,
            "workflow_hint": workflow_hint,
            "flags": flags,
            "requires_tools": bool(decision.tool_capabilities),
            "requires_mutation": False,
            "requires_shell": False,
            "requires_validation": False,
            "requires_external_knowledge": decision.requires_external_knowledge,
            "reason": reason,
        }
    )
