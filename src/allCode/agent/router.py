"""Routing decisions for user prompts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from allCode.agent.intent import IntentExtractor, IntentSignals
from allCode.core.models import CoreModel

RouteKind = Literal["answer", "inspect", "modify", "operate"]


class RoutingDecision(CoreModel):
    kind: RouteKind
    confidence: float
    reason: str
    target_hint: str | None = None
    flags: set[str] = Field(default_factory=set)
    read_only_requested: bool = False
    requires_tools: bool = False
    requires_mutation: bool = False
    requires_shell: bool = False
    requires_validation: bool = False
    requires_external_knowledge: bool = False

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @property
    def needs_llm_router(self) -> bool:
        return 0.45 <= self.confidence < 0.80

    @property
    def needs_clarification(self) -> bool:
        return self.confidence < 0.45


class RuleBasedRouter:
    """Static initial router. It does not execute tools."""

    def __init__(self, extractor: IntentExtractor | None = None) -> None:
        self._extractor = extractor or IntentExtractor()

    def classify(self, prompt: str) -> RoutingDecision:
        signals = self._extractor.extract(prompt)
        flags = self._flags(signals)

        if signals.read_only_requested:
            if signals.operate_action:
                return self._decision(
                    "inspect",
                    0.88,
                    "Read-only safety request overrides operation or mutation signals.",
                    signals,
                    flags,
                )
            return self._decision(
                "inspect" if signals.inspect_action or signals.target_hint else "answer",
                0.90,
                "Read-only request detected.",
                signals,
                flags,
            )
        if signals.conceptual_question and not signals.explicit_change_request:
            return self._decision(
                "inspect" if signals.target_hint else "answer",
                0.86,
                "Conceptual or explanatory question detected without an explicit change command.",
                signals,
                flags,
            )
        if signals.modify_action:
            return self._decision("modify", 0.84, "Modification or generation action requested.", signals, flags)
        if signals.operate_action and not signals.no_shell_requested:
            return self._decision("operate", 0.86, "Operation or validation command requested.", signals, flags)
        if signals.external_knowledge_requested and not signals.target_hint:
            return self._decision("answer", 0.72, "External knowledge may be needed for an answer.", signals, flags)
        if signals.inspect_action or signals.target_hint or signals.followup_requested:
            return self._decision("inspect", 0.82, "Inspection or target-oriented question requested.", signals, flags)
        if signals.external_knowledge_requested:
            return self._decision("answer", 0.72, "External knowledge may be needed for an answer.", signals, flags)
        return self._decision("answer", 0.60, "No tool-requiring action was clearly requested.", signals, flags)

    def _decision(
        self,
        kind: RouteKind,
        confidence: float,
        reason: str,
        signals: IntentSignals,
        flags: set[str],
    ) -> RoutingDecision:
        requires_mutation = kind == "modify" and not signals.read_only_requested
        requires_shell = kind == "operate" and not signals.no_shell_requested
        requires_validation = signals.validation_requested or (requires_mutation and "test" in flags)
        return RoutingDecision(
            kind=kind,
            confidence=confidence,
            reason=reason,
            target_hint=signals.target_hint,
            flags=flags,
            read_only_requested=signals.read_only_requested,
            requires_tools=kind in {"inspect", "modify", "operate"} or signals.external_knowledge_requested,
            requires_mutation=requires_mutation,
            requires_shell=requires_shell,
            requires_validation=requires_validation,
            requires_external_knowledge=signals.external_knowledge_requested and not signals.no_external_network,
        )

    @staticmethod
    def _flags(signals: IntentSignals) -> set[str]:
        flags: set[str] = set()
        if signals.read_only_requested:
            flags.add("read_only_requested")
        if signals.no_shell_requested:
            flags.add("no_shell")
        if signals.no_external_network:
            flags.add("no_external_network")
        if signals.validation_requested:
            flags.add("requires_validation")
        if signals.external_knowledge_requested:
            flags.add("requires_external_knowledge")
        if signals.followup_requested:
            flags.add("followup")
        if signals.conceptual_question:
            flags.add("conceptual_question")
        if signals.explicit_change_request:
            flags.add("explicit_change_request")
        return flags
