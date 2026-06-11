"""Structured schema for model-backed routing decisions."""

from __future__ import annotations

from pydantic import Field

from allCode.agent.router import RouteKind, ToolCapability, WorkflowHint
from allCode.core.models import CoreModel


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
