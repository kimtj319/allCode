"""Model-backed structured routing with safe fallback."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from allCode.agent.answer_policy import apply_answer_policy
from allCode.agent.context import ContextBundle
from allCode.agent.prompt_constraints import PromptConstraintExtractor, PromptConstraints
from allCode.agent.model_router_json import first_json_object
from allCode.agent.model_router_prompt import build_routing_messages
from allCode.agent.model_router_safety import read_only_needs_workspace_tools, sanitize_read_only_route
from allCode.agent.model_router_schema import ModelRoutingDecision
from allCode.agent.model_router_signals import answer_followup_request, local_workspace_request as detect_local_workspace_request
from allCode.agent.router import (
    RoutingDecision,
    RuleBasedRouter,
)
from allCode.agent.route_validator import validate_route
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings


def _fallback_flags(existing: set[str], constraints: PromptConstraints) -> set[str]:
    flags = set(existing or set())
    if constraints.read_only_requested:
        flags.add("read_only_requested")
    if constraints.no_shell_requested:
        flags.add("no_shell")
    if constraints.no_external_network:
        flags.add("no_external_network")
    if constraints.followup_requested:
        flags.add("followup")
    if constraints.workspace_evidence_requested:
        flags.add("workspace_evidence_requested")
    if constraints.answer_artifact_hint:
        flags.add("answer_artifact")
    if constraints.code_artifact_hint:
        flags.add("code_artifact")
    if constraints.stdlib_only_requested:
        flags.add("stdlib_only_requested")
    if constraints.unstable_knowledge_hint:
        flags.add("unstable_knowledge_requested")
    return flags


class ModelRouter:
    """Ask the configured model to classify intent, while code enforces safety."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        settings: ModelSettings,
        constraints: PromptConstraintExtractor | None = None,
        fallback_router: RuleBasedRouter | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._settings = settings
        self._constraints = constraints or PromptConstraintExtractor()
        self._fallback_router = fallback_router or RuleBasedRouter()

    async def classify(
        self,
        prompt: str,
        *,
        context_bundle: ContextBundle | None = None,
        recent_targets: Sequence[str] | None = None,
    ) -> RoutingDecision:
        constraints = self._constraints.extract(prompt)
        messages = build_routing_messages(prompt, constraints, context_bundle, recent_targets or [])
        try:
            response = await self._llm_client.complete(messages, [], self._settings)
            payload = first_json_object(response.final_text)
            if payload is None:
                raise ValueError("routing response did not contain a JSON object")
            model_decision = ModelRoutingDecision.model_validate(payload)
        except (ValidationError, ValueError, json.JSONDecodeError):
            return self._safe_fallback(prompt, constraints)
        return self._merge_constraints(model_decision, constraints, prompt=prompt)

    def _merge_constraints(
        self,
        decision: ModelRoutingDecision,
        constraints: PromptConstraints,
        *,
        prompt: str,
    ) -> RoutingDecision:
        capabilities = set(decision.tool_capabilities)
        flags: set[str] = set()
        read_only_requested = constraints.read_only_requested or decision.read_only_requested
        if read_only_requested:
            flags.add("read_only_requested")
            capabilities.difference_update({"mutate_file", "delete_file", "run_shell", "run_validation"})
        if constraints.no_shell_requested:
            flags.add("no_shell")
            capabilities.difference_update({"run_shell", "run_validation"})
        if constraints.no_external_network:
            flags.add("no_external_network")
            capabilities.discard("web_search")
        answer_followup = answer_followup_request(constraints, prompt)
        if constraints.validation_requested_hint and not answer_followup and not read_only_requested:
            flags.add("requires_validation")
            if not constraints.no_shell_requested:
                capabilities.add("run_validation")
        if constraints.mutation_requested_hint and not read_only_requested and not answer_followup:
            flags.add("explicit_change_request")
            capabilities.update({"read_file", "mutate_file"})
            if constraints.validation_requested_hint and not constraints.no_shell_requested:
                capabilities.add("run_validation")
        if constraints.project_generation_hint and not read_only_requested:
            flags.add("project_generation_requested")
        if constraints.directory_output_hint and not read_only_requested:
            flags.add("directory_output_requested")
        if constraints.multi_artifact_hint and not read_only_requested:
            flags.add("multi_artifact_requested")
        if constraints.project_output_hint and not read_only_requested:
            flags.add("project_output_requested")
        if constraints.code_artifact_hint:
            flags.add("code_artifact")
        if constraints.stdlib_only_requested:
            flags.add("stdlib_only_requested")
        if constraints.unstable_knowledge_hint:
            flags.add("unstable_knowledge_requested")
        if constraints.external_knowledge_hint and not constraints.no_external_network:
            flags.add("requires_external_knowledge")
            capabilities.add("web_search")
        if constraints.followup_requested:
            flags.add("followup")
        if constraints.workspace_evidence_requested:
            flags.add("workspace_evidence_requested")
        confidence = min(max(decision.confidence, 0.0), 1.0)
        kind = decision.kind
        target_hint = decision.target_hint or constraints.primary_target_hint
        workflow_hint = decision.workflow_hint
        if confidence < 0.45:
            kind = "inspect"
            capabilities = {"read_file", "search_workspace"}
        local_workspace_request = detect_local_workspace_request(constraints)
        answer_artifact = bool(
            read_only_requested
            and constraints.answer_artifact_hint
            and not constraints.path_hints
            and not local_workspace_request
        )
        if constraints.external_knowledge_hint and not constraints.no_external_network and not local_workspace_request:
            kind = "inspect"
        if constraints.mutation_requested_hint and not read_only_requested and not answer_followup:
            kind = "modify"
        if answer_followup:
            kind = "answer"
            capabilities.clear()
            workflow_hint = "none"
            target_hint = None
            flags.add("answer_followup")
        if answer_artifact:
            kind = "answer"
            capabilities.clear()
            workflow_hint = "direct_answer"
            target_hint = None
            flags.add("answer_artifact")
        if read_only_requested:
            kind = "answer" if answer_artifact else (
                "inspect" if read_only_needs_workspace_tools(constraints, local_workspace_request, capabilities) else "answer"
            )
            capabilities.difference_update({"mutate_file", "delete_file", "run_shell", "run_validation"})
            if answer_artifact:
                capabilities.clear()
            workflow_hint = "none"
            if answer_artifact:
                workflow_hint = "direct_answer"
        if not read_only_requested and capabilities.intersection({"mutate_file", "delete_file"}):
            kind = "modify"
        if constraints.workspace_evidence_requested and not capabilities and not answer_followup:
            capabilities.update({"read_file", "search_workspace"})
        if target_hint and Path(target_hint).suffix:
            if kind == "modify":
                capabilities.update({"read_file", "mutate_file"})
                if constraints.validation_requested_hint and not constraints.no_shell_requested:
                    capabilities.add("run_validation")
            if workflow_hint in {"multi_file_generation", "validation_repair"}:
                workflow_hint = "direct_file_edit"
        elif constraints.project_generation_hint and kind == "modify":
            workflow_hint = "multi_file_generation"
        requires_mutation = kind == "modify" and bool(capabilities.intersection({"mutate_file", "delete_file"}))
        requires_shell = kind == "operate" and "run_shell" in capabilities
        if local_workspace_request and not answer_followup:
            capabilities.discard("web_search")
            capabilities.update({"read_file", "search_workspace"})
            flags.discard("requires_external_knowledge")
            flags.add("workspace_evidence_requested")
            kind = "inspect" if kind == "answer" else kind
        if read_only_requested:
            capabilities.difference_update({"mutate_file", "delete_file", "run_shell", "run_validation"})
            if answer_artifact:
                kind = "answer"
                capabilities.clear()
                workflow_hint = "direct_answer"
            elif kind == "answer" and (constraints.workspace_evidence_requested or local_workspace_request or constraints.path_hints):
                capabilities.update({"read_file", "search_workspace"})
                kind = "inspect"
        requires_external = (
            bool(decision.requires_external_knowledge or "web_search" in capabilities)
            and not constraints.no_external_network
            and not local_workspace_request
        )
        requires_tools = kind in {"inspect", "modify", "operate"} or bool(capabilities)
        route = RoutingDecision(
            kind=kind,
            confidence=confidence,
            reason=decision.reason or "Model-routed decision.",
            target_hint=target_hint,
            tool_capabilities=capabilities,
            workflow_hint=workflow_hint,
            route_source="model",
            flags=flags,
            read_only_requested=read_only_requested,
            requires_tools=requires_tools,
            requires_mutation=requires_mutation,
            requires_shell=requires_shell,
            requires_validation=bool(decision.requires_validation or constraints.validation_requested_hint)
            and "run_validation" in capabilities,
            requires_external_knowledge=requires_external,
        )
        return self._validate_route(
            route,
            constraints=constraints,
            local_workspace_request=local_workspace_request,
            answer_followup=answer_followup,
        )

    def _safe_fallback(self, prompt: str, constraints: PromptConstraints) -> RoutingDecision:
        decision = self._fallback_router.classify(prompt)
        capabilities = set(decision.tool_capabilities)
        kind = decision.kind
        answer_followup = answer_followup_request(constraints, prompt)
        local_workspace_request = detect_local_workspace_request(constraints)
        answer_artifact = bool(
            constraints.read_only_requested
            and constraints.answer_artifact_hint
            and not constraints.path_hints
            and not local_workspace_request
        )
        if constraints.followup_requested or constraints.workspace_evidence_requested or constraints.path_hints:
            kind = "inspect"
            capabilities.update({"read_file", "search_workspace"})
        if constraints.external_knowledge_hint and not constraints.no_external_network and not local_workspace_request:
            kind = "inspect"
            capabilities.add("web_search")
        if constraints.mutation_requested_hint and not constraints.read_only_requested and not answer_followup:
            kind = "modify"
            capabilities.update({"read_file", "mutate_file"})
            if constraints.validation_requested_hint and not constraints.no_shell_requested:
                capabilities.add("run_validation")
        if answer_followup:
            kind = "answer"
            capabilities.clear()
        if answer_artifact:
            kind = "answer"
            capabilities.clear()
        if constraints.read_only_requested:
            capabilities.difference_update({"mutate_file", "delete_file", "run_shell", "run_validation"})
            kind = "answer" if answer_artifact else (
                "inspect" if read_only_needs_workspace_tools(constraints, local_workspace_request, capabilities) else "answer"
            )
            if kind == "inspect":
                capabilities.update({"read_file", "search_workspace"})
            elif answer_artifact:
                capabilities.clear()
        if local_workspace_request and not answer_followup:
            kind = "inspect"
            capabilities.discard("web_search")
            capabilities.update({"read_file", "search_workspace"})
        if not constraints.read_only_requested and capabilities.intersection({"mutate_file", "delete_file"}):
            kind = "modify"
        target_hint = decision.target_hint or constraints.primary_target_hint
        workflow_hint = decision.workflow_hint
        if target_hint and Path(target_hint).suffix and workflow_hint in {"multi_file_generation", "validation_repair"}:
            workflow_hint = "direct_file_edit"
        elif constraints.project_generation_hint and kind == "modify":
            workflow_hint = "multi_file_generation"
        route = decision.model_copy(
            update={
                "kind": kind,
                "confidence": min(decision.confidence, 0.74),
                "reason": f"Safe fallback after model routing failure. {decision.reason}",
                "target_hint": target_hint,
                "tool_capabilities": capabilities,
                "workflow_hint": "direct_answer" if answer_artifact else workflow_hint,
                "route_source": "fallback",
                "flags": _fallback_flags(decision.flags, constraints),
                "requires_tools": kind in {"inspect", "modify", "operate"} or bool(capabilities),
                "requires_mutation": False if constraints.read_only_requested else kind == "modify" and bool(capabilities.intersection({"mutate_file", "delete_file"})),
                "requires_shell": kind == "operate" and "run_shell" in capabilities,
                "requires_validation": bool(decision.requires_validation or constraints.validation_requested_hint)
                and "run_validation" in capabilities,
                "requires_external_knowledge": bool(capabilities.intersection({"web_search"})) and not local_workspace_request,
            }
        )
        return sanitize_read_only_route(
            route,
            constraints=constraints,
            local_workspace_request=local_workspace_request,
        )

    @staticmethod
    def _validate_route(
        route: RoutingDecision,
        *,
        constraints: PromptConstraints,
        local_workspace_request: bool,
        answer_followup: bool,
    ) -> RoutingDecision:
        validated, report = validate_route(
            route,
            constraints=constraints,
            local_workspace_request=local_workspace_request,
            answer_followup=answer_followup,
        )
        if not report.repaired:
            return apply_answer_policy(validated, constraints=constraints, local_workspace_request=local_workspace_request)
        reason = validated.reason
        suffix = "; route validation repaired: " + ", ".join(report.repairs[:4])
        if suffix not in reason:
            reason = f"{reason}{suffix}"
        return apply_answer_policy(
            validated.model_copy(update={"reason": reason}),
            constraints=constraints,
            local_workspace_request=local_workspace_request,
        )
