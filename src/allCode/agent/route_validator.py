"""Post-merge routing invariants for model-backed route decisions."""

from __future__ import annotations

from pydantic import Field

from allCode.agent.prompt_constraints import PromptConstraints
from allCode.agent.router import RouteKind, RoutingDecision, ToolCapability, WorkflowHint
from allCode.core.models import CoreModel

MUTATION_CAPABILITIES: set[ToolCapability] = {"mutate_file", "delete_file"}
SHELL_CAPABILITIES: set[ToolCapability] = {"run_shell"}
VALIDATION_CAPABILITIES: set[ToolCapability] = {"run_validation"}
LOCAL_CAPABILITIES: set[ToolCapability] = {"read_file", "search_workspace"}
WEB_CAPABILITIES: set[ToolCapability] = {"web_search"}
NON_ANSWER_CAPABILITIES = MUTATION_CAPABILITIES | SHELL_CAPABILITIES | VALIDATION_CAPABILITIES | LOCAL_CAPABILITIES


class RouteValidationReport(CoreModel):
    repairs: list[str] = Field(default_factory=list)

    @property
    def repaired(self) -> bool:
        return bool(self.repairs)


def validate_route(
    route: RoutingDecision,
    *,
    constraints: PromptConstraints,
    local_workspace_request: bool,
    answer_followup: bool = False,
) -> tuple[RoutingDecision, RouteValidationReport]:
    """Normalize a route using structural signals, not scenario-specific prompts."""

    repairs: list[str] = []
    capabilities = set(route.tool_capabilities)
    flags = set(route.flags)
    kind: RouteKind = route.kind
    workflow_hint: WorkflowHint = route.workflow_hint
    target_hint = route.target_hint or constraints.primary_target_hint
    read_only_requested = bool(route.read_only_requested or constraints.read_only_requested)
    workspace_evidence = _workspace_evidence_required(constraints, local_workspace_request, target_hint)
    external_requested = bool(
        (route.requires_external_knowledge or constraints.external_knowledge_hint or "web_search" in capabilities)
        and not constraints.no_external_network
        and not local_workspace_request
    )

    if constraints.no_shell_requested:
        flags.add("no_shell")
        if capabilities & (SHELL_CAPABILITIES | VALIDATION_CAPABILITIES):
            repairs.append("removed shell/validation capabilities for no-shell request")
        capabilities.difference_update(SHELL_CAPABILITIES | VALIDATION_CAPABILITIES)

    if constraints.no_external_network:
        flags.add("no_external_network")
        if "web_search" in capabilities:
            repairs.append("removed web capability for no-network request")
        capabilities.difference_update(WEB_CAPABILITIES)
        external_requested = False

    if read_only_requested:
        flags.add("read_only_requested")
        removed = capabilities & (MUTATION_CAPABILITIES | SHELL_CAPABILITIES | VALIDATION_CAPABILITIES)
        if removed:
            repairs.append("removed mutation/shell/validation capabilities for read-only request")
        capabilities.difference_update(MUTATION_CAPABILITIES | SHELL_CAPABILITIES | VALIDATION_CAPABILITIES)
        flags.discard("requires_validation")
        workflow_hint = "none"
        if external_requested and not workspace_evidence:
            kind = "answer"
            capabilities = {"web_search"}
        elif workspace_evidence or capabilities & LOCAL_CAPABILITIES:
            kind = "inspect"
            capabilities.update(LOCAL_CAPABILITIES)
        else:
            kind = "answer"
            capabilities.clear()
        if route.kind != kind:
            repairs.append(f"normalized read-only route to {kind}")

    if answer_followup:
        if kind != "answer" or capabilities:
            repairs.append("normalized answer follow-up to direct answer")
        kind = "answer"
        capabilities.clear()
        workflow_hint = "none"
        target_hint = None
        flags.add("answer_followup")
        external_requested = False

    if not read_only_requested and not answer_followup and external_requested and not workspace_evidence:
        if kind != "answer" or capabilities - WEB_CAPABILITIES:
            repairs.append("normalized external knowledge route to answer with web-only tools")
        kind = "answer"
        capabilities = {"web_search"}
        workflow_hint = "external_research"
        flags.add("requires_external_knowledge")

    if not read_only_requested and not answer_followup and kind == "modify":
        if not _mutation_is_structurally_supported(route, constraints, target_hint):
            capabilities.difference_update(MUTATION_CAPABILITIES | VALIDATION_CAPABILITIES)
            flags.discard("requires_validation")
            if workspace_evidence:
                kind = "inspect"
                capabilities.update(LOCAL_CAPABILITIES)
                repairs.append("downgraded unsupported mutation route to inspect")
            else:
                kind = "answer"
                capabilities.clear()
                workflow_hint = "none"
                repairs.append("downgraded unsupported mutation route to answer")

    if not read_only_requested and not answer_followup and workspace_evidence and kind == "answer" and not external_requested:
        if capabilities & LOCAL_CAPABILITIES or constraints.workspace_evidence_requested or local_workspace_request:
            kind = "inspect"
            capabilities.update(LOCAL_CAPABILITIES)
            repairs.append("upgraded workspace-evidence answer route to inspect")

    if kind == "answer":
        if external_requested:
            if capabilities != {"web_search"}:
                repairs.append("removed non-web tools from external answer route")
            capabilities = {"web_search"}
            workflow_hint = "external_research"
        else:
            if capabilities:
                repairs.append("removed tools from direct answer route")
            capabilities.clear()
            workflow_hint = "none" if workflow_hint not in {"none", "direct_answer"} else workflow_hint

    if kind == "inspect":
        capabilities.difference_update(MUTATION_CAPABILITIES | SHELL_CAPABILITIES | VALIDATION_CAPABILITIES)
        if workspace_evidence or not external_requested:
            capabilities.update(LOCAL_CAPABILITIES)
        if local_workspace_request:
            capabilities.discard("web_search")
            flags.discard("requires_external_knowledge")
            external_requested = False
        workflow_hint = "none"

    if kind == "operate" and constraints.no_shell_requested:
        kind = "inspect" if workspace_evidence else "answer"
        capabilities = set(LOCAL_CAPABILITIES) if kind == "inspect" else set()
        workflow_hint = "none"
        repairs.append("downgraded operate route because shell is disallowed")

    if kind == "modify" and not read_only_requested:
        capabilities.update({"read_file", "mutate_file"})
        if constraints.validation_requested_hint and not constraints.no_shell_requested:
            capabilities.add("run_validation")
            flags.add("requires_validation")
        if target_hint and "." in target_hint.rsplit("/", 1)[-1] and workflow_hint in {"multi_file_generation", "validation_repair"}:
            workflow_hint = "direct_file_edit"
            repairs.append("normalized concrete-file workflow hint to direct_file_edit")
        elif constraints.project_generation_hint:
            workflow_hint = "multi_file_generation"

    requires_external = bool("web_search" in capabilities and not constraints.no_external_network and not local_workspace_request)
    requires_mutation = bool(kind == "modify" and capabilities & MUTATION_CAPABILITIES and not read_only_requested)
    requires_shell = bool(kind == "operate" and "run_shell" in capabilities and not constraints.no_shell_requested)
    requires_validation = bool(
        kind in {"modify", "operate"}
        and not read_only_requested
        and "run_validation" in capabilities
        and not constraints.no_shell_requested
    )
    requires_tools = bool(kind in {"inspect", "modify", "operate"} or capabilities)

    if repairs:
        flags.add("route_validated")

    normalized = route.model_copy(
        update={
            "kind": kind,
            "target_hint": target_hint,
            "tool_capabilities": capabilities,
            "workflow_hint": workflow_hint,
            "flags": flags,
            "read_only_requested": read_only_requested,
            "requires_tools": requires_tools,
            "requires_mutation": requires_mutation,
            "requires_shell": requires_shell,
            "requires_validation": requires_validation,
            "requires_external_knowledge": requires_external,
        }
    )
    return normalized, RouteValidationReport(repairs=repairs)


def _workspace_evidence_required(
    constraints: PromptConstraints,
    local_workspace_request: bool,
    target_hint: str | None,
) -> bool:
    if constraints.external_knowledge_hint and not constraints.path_hints and not local_workspace_request:
        return False
    return bool(constraints.workspace_evidence_requested or constraints.path_hints or local_workspace_request or target_hint)


def _mutation_is_structurally_supported(
    route: RoutingDecision,
    constraints: PromptConstraints,
    target_hint: str | None,
) -> bool:
    if constraints.read_only_requested:
        return False
    if constraints.project_generation_hint:
        return True
    if target_hint:
        return True
    if route.workflow_hint == "multi_file_generation" and constraints.project_generation_hint:
        return True
    if route.workflow_hint == "validation_repair" and constraints.validation_requested_hint and target_hint:
        return True
    return False
