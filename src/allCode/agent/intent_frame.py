"""Consolidated intent frame for route validation and telemetry."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from allCode.agent.prompt_constraints import PromptConstraints
from allCode.agent.router import RoutingDecision
from allCode.core.models import CoreModel

TaskKind = Literal["answer", "inspect", "modify", "operate"]
EvidenceNeed = Literal["none", "workspace", "web", "workspace_and_web"]
ArtifactNeed = Literal["none", "answer", "source", "test", "document", "project"]


class IntentFrame(CoreModel):
    """Small structured frame that explains route decisions without prompt-specific branches."""

    task_kind: TaskKind
    scope: str = "general"
    artifact_need: ArtifactNeed = "none"
    evidence_need: EvidenceNeed = "none"
    mutation_allowed: bool = False
    validation_need: bool = False
    external_freshness_need: bool = False
    workspace_target_hints: list[str] = Field(default_factory=list)
    confidence_reasons: list[str] = Field(default_factory=list)


def build_intent_frame(
    route: RoutingDecision,
    *,
    constraints: PromptConstraints,
    local_workspace_request: bool,
    target_hint: str | None,
) -> IntentFrame:
    workspace_hints = [hint for hint in [target_hint, *constraints.path_hints] if hint]
    workspace_needed = bool(local_workspace_request or constraints.workspace_evidence_requested or workspace_hints)
    web_needed = bool(
        (route.requires_external_knowledge or constraints.external_knowledge_hint or constraints.unstable_knowledge_hint)
        and not constraints.no_external_network
    )
    if workspace_needed and web_needed:
        evidence_need: EvidenceNeed = "workspace_and_web"
    elif workspace_needed:
        evidence_need = "workspace"
    elif web_needed:
        evidence_need = "web"
    else:
        evidence_need = "none"
    return IntentFrame(
        task_kind=route.kind,
        scope="workspace" if workspace_needed else "general",
        artifact_need=_artifact_need(route, constraints),
        evidence_need=evidence_need,
        mutation_allowed=bool(route.requires_mutation and not constraints.read_only_requested),
        validation_need=bool(route.requires_validation or constraints.validation_requested_hint),
        external_freshness_need=web_needed,
        workspace_target_hints=_dedupe(workspace_hints)[:5],
        confidence_reasons=_confidence_reasons(route, constraints, local_workspace_request=local_workspace_request),
    )


def _artifact_need(route: RoutingDecision, constraints: PromptConstraints) -> ArtifactNeed:
    if constraints.project_generation_hint or route.workflow_hint == "multi_file_generation":
        return "project"
    if constraints.validation_requested_hint:
        return "test"
    if constraints.answer_artifact_hint:
        return "answer"
    if constraints.code_artifact_hint or constraints.mutation_requested_hint:
        return "source"
    return "none"


def _confidence_reasons(
    route: RoutingDecision,
    constraints: PromptConstraints,
    *,
    local_workspace_request: bool,
) -> list[str]:
    reasons = [f"route_source={route.route_source}", f"confidence={route.confidence:.2f}"]
    if constraints.read_only_requested:
        reasons.append("read_only=true")
    if constraints.no_shell_requested:
        reasons.append("no_shell=true")
    if constraints.no_external_network:
        reasons.append("no_network=true")
    if constraints.external_knowledge_hint or constraints.unstable_knowledge_hint:
        reasons.append("freshness_or_external=true")
    if local_workspace_request:
        reasons.append("workspace_scope=true")
    if route.workflow_hint != "none":
        reasons.append(f"workflow={route.workflow_hint}")
    return reasons


def _dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen
