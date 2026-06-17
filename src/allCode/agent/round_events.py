"""Event publishing helpers for round execution."""

from __future__ import annotations

from allCode.agent.finalization_helpers import message_chars, tool_observation_chars
from allCode.agent.round_runtime import RoundRuntime
from allCode.core.events import ModelMetricsRecorded, ModelRequestPrepared, ModelResponseParsed
from allCode.core.models import TurnState


async def publish_model_request(
    event_bus,
    *,
    state: TurnState,
    runtime: RoundRuntime,
    routing,
    phase_gate,
    allowed_tool_names: set[str],
    round_index: int,
) -> None:
    await event_bus.publish(
        ModelRequestPrepared(
            turn_id=state.turn_id,
            message=f"Model request prepared for round {round_index + 1}.",
            data={
                "round": round_index + 1,
                "message_count": len(runtime.messages),
                "message_chars": message_chars(runtime.messages),
                "prompt_chars": message_chars(runtime.messages),
                "tool_observation_chars": tool_observation_chars(runtime.messages),
                "request_tool_schema_count": len(allowed_tool_names),
                "allowed_tools": sorted(allowed_tool_names),
                "routing": routing.model_dump(mode="json"),
                "phase_gate": phase_gate.model_dump(mode="json"),
            },
        )
    )


async def publish_parsed_response(
    event_bus, *, state: TurnState, parsed, runtime: RoundRuntime, round_index: int, model: str | None = None
) -> None:
    await event_bus.publish(
        ModelResponseParsed(
            turn_id=state.turn_id,
            message=f"Model response parsed: {parsed.status}.",
            data={
                "status": parsed.status,
                "finish_reason": parsed.finish_reason,
                "text_length": len(parsed.text),
                "response_chars": len(parsed.text),
                "response_tool_call_count": len(parsed.tool_calls),
                "tool_calls": [{"id": tool_call.id, "name": tool_call.name} for tool_call in parsed.tool_calls],
                "usage": parsed.usage.model_dump(mode="json") if parsed.usage is not None else None,
                "error": parsed.error,
                "metrics": parsed.metrics,
                "tool_argument_repairs": parsed.tool_argument_repairs,
            },
        )
    )
    await event_bus.publish(
        ModelMetricsRecorded(
            turn_id=state.turn_id,
            message=f"Model metrics recorded for round {round_index + 1}.",
            data={
                "round": round_index + 1,
                "model": model,
                "request_message_count": len(runtime.messages),
                "request_chars": message_chars(runtime.messages),
                "prompt_chars": message_chars(runtime.messages),
                "request_tool_observation_chars": tool_observation_chars(runtime.messages),
                "response_text_chars": len(parsed.text),
                "response_chars": len(parsed.text),
                "response_tool_call_count": len(parsed.tool_calls),
                "finish_reason": parsed.finish_reason,
                "status": parsed.status,
                "response_metrics": parsed.metrics,
                "usage": parsed.usage.model_dump(mode="json") if parsed.usage is not None else None,
            },
        )
    )
