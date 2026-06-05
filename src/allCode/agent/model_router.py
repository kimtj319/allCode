"""Model-backed structured routing with safe fallback."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError

from allCode.agent.answer_policy import apply_answer_policy
from allCode.agent.context import ContextBundle
from allCode.agent.prompt_constraints import PromptConstraintExtractor, PromptConstraints
from allCode.agent.model_router_signals import answer_followup_request, local_workspace_request as detect_local_workspace_request
from allCode.agent.router import (
    RouteKind,
    RoutingDecision,
    RuleBasedRouter,
    ToolCapability,
    WorkflowHint,
)
from allCode.agent.route_validator import validate_route
from allCode.core.models import CoreModel, Message
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings


class ModelRoutingDecision(CoreModel):
    kind: RouteKind
    confidence: float = 0.0
    tool_capabilities: set[ToolCapability] = Field(default_factory=set)
    workflow_hint: WorkflowHint = "none"
    target_hint: str | None = None
    requires_validation: bool = False
    requires_external_knowledge: bool = False
    read_only_requested: bool = False
    reason: str = ""


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
        messages = self._messages(prompt, constraints, context_bundle, recent_targets or [])
        try:
            response = await self._llm_client.complete(messages, [], self._settings)
            payload = _first_json_object(response.final_text)
            if payload is None:
                raise ValueError("routing response did not contain a JSON object")
            model_decision = ModelRoutingDecision.model_validate(payload)
        except (ValidationError, ValueError, json.JSONDecodeError):
            return self._safe_fallback(prompt, constraints)
        return self._merge_constraints(model_decision, constraints, prompt=prompt)

    def _messages(
        self,
        prompt: str,
        constraints: PromptConstraints,
        context_bundle: ContextBundle | None,
        recent_targets: Sequence[str],
    ) -> list[Message]:
        context_sources = context_bundle.sources() if context_bundle is not None else []
        context_section_names = [section.name for section in context_bundle.sections] if context_bundle is not None else []
        system = (
            "You are the allCode routing model. Do not answer the user's task. "
            "Return one JSON object only. Decide which tool capabilities the agent should expose.\n"
            'kind must be one of "answer", "inspect", "modify", "operate".\n'
            "Use inspect when the user asks to read, find, search, locate, analyze repository files, "
            "or asks a follow-up that requires workspace evidence.\n"
            "Use answer only when no tool evidence is needed.\n"
            "Use modify for file creation/edit/delete. Use operate for shell/build/test operation.\n"
            "tool_capabilities may include read_file, search_workspace, mutate_file, delete_file, "
            "run_shell, run_validation, web_search.\n"
            "workflow_hint must be none, direct_answer, direct_file_edit, single_file_create, "
            "multi_file_generation, validation_repair, or external_research.\n"
            "Single file creation/edit/delete must not be multi_file_generation. "
            "Existing file edits or fixes with a concrete filename or path must use direct_file_edit, "
            "not multi_file_generation or validation_repair."
        )
        user = {
            "prompt": prompt,
            "constraints": constraints.model_dump(mode="json"),
            "recent_targets": list(recent_targets),
            "context_sources": context_sources[:20],
            "context_sections": context_section_names[:20],
            "required_json_shape": {
                "kind": "answer|inspect|modify|operate",
                "confidence": 0.0,
                "tool_capabilities": ["read_file"],
                "workflow_hint": "none",
                "target_hint": None,
                "requires_validation": False,
                "requires_external_knowledge": False,
                "read_only_requested": False,
                "reason": "short rationale",
            },
        }
        return [Message(role="system", content=system), Message(role="user", content=json.dumps(user, ensure_ascii=False))]

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
        if read_only_requested:
            kind = "inspect" if _read_only_needs_workspace_tools(constraints, local_workspace_request, capabilities) else "answer"
            capabilities.difference_update({"mutate_file", "delete_file", "run_shell", "run_validation"})
            workflow_hint = "none"
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
            if kind == "answer" and (constraints.workspace_evidence_requested or local_workspace_request or constraints.path_hints):
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
        if constraints.followup_requested or constraints.workspace_evidence_requested or constraints.path_hints:
            kind = "inspect"
            capabilities.update({"read_file", "search_workspace"})
        local_workspace_request = detect_local_workspace_request(constraints)
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
        if constraints.read_only_requested:
            local_workspace_request = detect_local_workspace_request(constraints)
            capabilities.difference_update({"mutate_file", "delete_file", "run_shell", "run_validation"})
            kind = "inspect" if _read_only_needs_workspace_tools(constraints, local_workspace_request, capabilities) else "answer"
            if kind == "inspect":
                capabilities.update({"read_file", "search_workspace"})
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
                "workflow_hint": workflow_hint,
                "route_source": "fallback",
                "requires_tools": kind in {"inspect", "modify", "operate"} or bool(capabilities),
                "requires_mutation": False if constraints.read_only_requested else kind == "modify" and bool(capabilities.intersection({"mutate_file", "delete_file"})),
                "requires_shell": kind == "operate" and "run_shell" in capabilities,
                "requires_validation": bool(decision.requires_validation or constraints.validation_requested_hint)
                and "run_validation" in capabilities,
                "requires_external_knowledge": bool(capabilities.intersection({"web_search"})) and not local_workspace_request,
            }
        )
        return _sanitize_read_only_route(
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


def _read_only_needs_workspace_tools(
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


def _sanitize_read_only_route(
    route: RoutingDecision,
    *,
    constraints: PromptConstraints,
    local_workspace_request: bool,
) -> RoutingDecision:
    if not route.read_only_requested:
        return route
    capabilities = set(route.tool_capabilities)
    capabilities.difference_update({"mutate_file", "delete_file", "run_shell", "run_validation"})
    flags = set(route.flags)
    flags.add("read_only_requested")
    flags.discard("requires_validation")
    if local_workspace_request:
        capabilities.discard("web_search")
    needs_workspace_tools = bool(
        _read_only_needs_workspace_tools(constraints, local_workspace_request, capabilities)
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


def _first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
