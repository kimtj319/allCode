"""Event models for observing agent actions without coupling to UI code."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, field_validator

from allCode.core.models import CoreModel, TokenUsage, ToolCall, ToolResult, _json_safe

EventSeverity = Literal["user_visible", "status_only", "debug_only"]
ModelEventKind = Literal[
    "text_delta",
    "tool_call_delta",
    "tool_call_completed",
    "response_completed",
    "response_failed",
    "usage",
]


def _event_time() -> datetime:
    return datetime.now(timezone.utc)


class AgentEvent(CoreModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    turn_id: str
    event_type: str
    severity: EventSeverity = "status_only"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_event_time)

    @field_validator("data")
    @classmethod
    def data_must_be_json_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _json_safe(value):
            raise ValueError("event data must be JSON-serializable")
        return value


class UserPromptSubmitted(AgentEvent):
    event_type: Literal["user_prompt_submitted"] = "user_prompt_submitted"
    severity: EventSeverity = "user_visible"


class TurnStarted(AgentEvent):
    event_type: Literal["turn_started"] = "turn_started"


class RoutingDecided(AgentEvent):
    event_type: Literal["routing_decided"] = "routing_decided"


class ModelStreamStarted(AgentEvent):
    event_type: Literal["model_stream_started"] = "model_stream_started"


class ModelStreamHeartbeat(AgentEvent):
    event_type: Literal["model_stream_heartbeat"] = "model_stream_heartbeat"


class ModelStreamTimedOut(AgentEvent):
    event_type: Literal["model_stream_timed_out"] = "model_stream_timed_out"
    severity: EventSeverity = "user_visible"


class ModelTextDelta(AgentEvent):
    event_type: Literal["model_text_delta"] = "model_text_delta"
    severity: EventSeverity = "user_visible"
    delta: str


class ToolCallRequested(AgentEvent):
    event_type: Literal["tool_call_requested"] = "tool_call_requested"
    tool_call: ToolCall


class ToolExecutionStarted(AgentEvent):
    event_type: Literal["tool_execution_started"] = "tool_execution_started"
    tool_call: ToolCall


class ToolExecutionFinished(AgentEvent):
    event_type: Literal["tool_execution_finished"] = "tool_execution_finished"
    result: ToolResult


class ApprovalRequested(AgentEvent):
    event_type: Literal["approval_requested"] = "approval_requested"
    severity: EventSeverity = "user_visible"


class ApprovalResolved(AgentEvent):
    event_type: Literal["approval_resolved"] = "approval_resolved"


class ValidationStarted(AgentEvent):
    event_type: Literal["validation_started"] = "validation_started"


class ValidationFinished(AgentEvent):
    event_type: Literal["validation_finished"] = "validation_finished"
    severity: EventSeverity = "user_visible"


class GenerationWorkflowStarted(AgentEvent):
    event_type: Literal["generation_workflow_started"] = "generation_workflow_started"


class GenerationStepStarted(AgentEvent):
    event_type: Literal["generation_step_started"] = "generation_step_started"


class GenerationStepFinished(AgentEvent):
    event_type: Literal["generation_step_finished"] = "generation_step_finished"


class GenerationWorkflowFinished(AgentEvent):
    event_type: Literal["generation_workflow_finished"] = "generation_workflow_finished"
    severity: EventSeverity = "user_visible"


class WorkspaceRootAdded(AgentEvent):
    event_type: Literal["workspace_root_added"] = "workspace_root_added"


class WorkspaceRootRejected(AgentEvent):
    event_type: Literal["workspace_root_rejected"] = "workspace_root_rejected"
    severity: EventSeverity = "user_visible"


class WorkspaceIndexed(AgentEvent):
    event_type: Literal["workspace_indexed"] = "workspace_indexed"


class PathResolved(AgentEvent):
    event_type: Literal["path_resolved"] = "path_resolved"


class PathResolutionAmbiguous(AgentEvent):
    event_type: Literal["path_resolution_ambiguous"] = "path_resolution_ambiguous"
    severity: EventSeverity = "user_visible"


class WorkspaceIndexUpdated(AgentEvent):
    event_type: Literal["workspace_index_updated"] = "workspace_index_updated"


class FinalAnswerReady(AgentEvent):
    event_type: Literal["final_answer_ready"] = "final_answer_ready"
    severity: EventSeverity = "user_visible"
    final_answer: str


class TurnFailed(AgentEvent):
    event_type: Literal["turn_failed"] = "turn_failed"
    severity: EventSeverity = "user_visible"
    error_type: str
    cancelled: bool = False


class TurnCancelled(AgentEvent):
    event_type: Literal["turn_cancelled"] = "turn_cancelled"
    severity: EventSeverity = "user_visible"


class EventDropped(AgentEvent):
    event_type: Literal["event_dropped"] = "event_dropped"
    dropped_count: int


class ToolLoopDetected(AgentEvent):
    event_type: Literal["tool_loop_detected"] = "tool_loop_detected"
    severity: EventSeverity = "user_visible"
    tool_call: ToolCall


class ModelToolCallDelta(CoreModel):
    id: str
    name: str | None = None
    arguments_delta: str = ""
    index: int = 0


class ModelEvent(CoreModel):
    kind: ModelEventKind
    text: str = ""
    tool_call: ToolCall | None = None
    tool_call_delta: ModelToolCallDelta | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_json_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _json_safe(value):
            raise ValueError("metadata must be JSON-serializable")
        return value
