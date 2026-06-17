"""Model event aggregation and partial tool-call JSON parsing."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any, Literal

# Harmony/channel control tokens some providers (e.g. wise-lloa) leak into the
# visible text instead of a separate reasoning channel — e.g.
# "<|channel>thought<channel|>실제 답변". Strip the control tokens and a
# leftover channel-name label so they never reach the user.
_CHANNEL_TOKEN = re.compile(
    r"<\|?\s*(?:channel|message|start|end|return|assistant|system|user|developer|tool|constrain)\s*\|?>",
    re.IGNORECASE,
)
_CHANNEL_LABEL_LINE = re.compile(r"(?im)^[ \t]*(?:thought|analysis|commentary|final)[ \t]*$")


def sanitize_channel_markup(text: str) -> str:
    """Remove leaked harmony/channel control tokens from user-visible text."""
    if "<|" not in text and "|>" not in text and "<channel" not in text.lower():
        return text
    cleaned = _CHANNEL_TOKEN.sub("", text)
    cleaned = _CHANNEL_LABEL_LINE.sub("", cleaned)
    cleaned = re.sub(r"^\s*(?:thought|analysis|commentary)\b[:\s]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip("\n")
    return cleaned or text

from pydantic import Field

from allCode.core.events import ModelEvent, ModelToolCallDelta
from allCode.core.models import CoreModel, TokenUsage, ToolCall
from allCode.llm.tool_argument_repair import ToolArgumentRepairer

ParseStatus = Literal[
    "ok_text",
    "ok_tool_calls",
    "empty_response",
    "reasoning_only",
    "length_cutoff",
    "malformed_tool_call",
    "pseudo_tool_call",
    "slow_stream",
    "stream_timeout",
]


class ParsedResponse(CoreModel):
    status: ParseStatus
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    error: str | None = None
    metrics: dict[str, int] = Field(default_factory=dict)
    tool_argument_repairs: list[dict[str, str]] = Field(default_factory=list)


class ToolArgumentBuffer(CoreModel):
    id: str
    name: str | None = None
    text: str = ""
    last_valid_arguments: dict[str, Any] = Field(default_factory=dict)
    malformed: bool = False
    error: str | None = None
    repair_metadata: dict[str, str] = Field(default_factory=dict)

    def append(self, delta: ModelToolCallDelta, repairer: ToolArgumentRepairer) -> None:
        if delta.name:
            self.name = delta.name
        self.text += delta.arguments_delta
        complete = self._looks_complete_json(self.text)
        if not complete:
            return
        try:
            parsed = json.loads(self.text or "{}")
        except json.JSONDecodeError as exc:
            repaired = repairer.repair(tool_name=self.name, text=self.text)
            if repaired is not None:
                self.last_valid_arguments = repaired.arguments
                self.malformed = False
                self.error = None
                self.repair_metadata = {
                    "tool_name": self.name or "",
                    "confidence": repaired.confidence,
                    "reason": repaired.reason,
                }
                return
            self.malformed = True
            self.error = str(exc)
            return
        if not isinstance(parsed, dict):
            self.malformed = True
            self.error = "tool arguments must decode to an object"
            return
        self.last_valid_arguments = repairer.normalize_valid_arguments(tool_name=self.name, arguments=parsed)

    def to_tool_call(self) -> ToolCall | None:
        if self.malformed or self.name is None:
            return None
        if self.text and not self._looks_complete_json(self.text):
            return None
        return ToolCall(id=self.id, name=self.name, arguments=self.last_valid_arguments)

    def repair_to_tool_call(self, repairer: ToolArgumentRepairer) -> ToolCall | None:
        if self.malformed or self.name is None or not self.text.strip():
            return None
        repaired = repairer.repair(tool_name=self.name, text=self.text)
        if repaired is None:
            return None
        self.last_valid_arguments = repaired.arguments
        self.malformed = False
        self.error = None
        self.repair_metadata = {
            "tool_name": self.name or "",
            "confidence": repaired.confidence,
            "reason": f"last-mile {repaired.reason}",
        }
        return ToolCall(id=self.id, name=self.name, arguments=self.last_valid_arguments)

    @staticmethod
    def _looks_complete_json(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        depth = 0
        in_string = False
        escaped = False
        for char in stripped:
            if escaped:
                escaped = False
                continue
            if char == "\\" and in_string:
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char in "{[":
                depth += 1
            elif char in "}]":
                depth -= 1
                if depth < 0:
                    return True
        return depth == 0 and not in_string


class ResponseParser:
    """Aggregates provider-neutral stream events into one response summary."""

    def __init__(self, repairer: ToolArgumentRepairer | None = None) -> None:
        self._repairer = repairer or ToolArgumentRepairer()

    def parse_events(self, events: Iterable[ModelEvent]) -> ParsedResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        buffers: dict[str, ToolArgumentBuffer] = {}
        finish_reason: str | None = None
        usage: TokenUsage | None = None
        failed_error: str | None = None
        saw_reasoning_only_delta = False
        metrics = {
            "event_count": 0,
            "text_delta_chars": 0,
            "reasoning_delta_chars": 0,
            "tool_argument_delta_chars": 0,
            "tool_argument_repairs": 0,
        }
        tool_argument_repairs: list[dict[str, str]] = []

        for event in events:
            metrics["event_count"] += 1
            if event.kind == "text_delta":
                if any(
                    event.metadata.get(key)
                    for key in ("reasoning", "reasoning_delta", "reasoning_content")
                ):
                    saw_reasoning_only_delta = True
                    metrics["reasoning_delta_chars"] += len(
                        str(
                            event.metadata.get("reasoning_delta")
                            or event.metadata.get("reasoning_content")
                            or event.metadata.get("reasoning")
                            or ""
                        )
                    )
                else:
                    metrics["text_delta_chars"] += len(event.text)
                text_parts.append(event.text)
            elif event.kind == "tool_call_delta" and event.tool_call_delta is not None:
                delta = event.tool_call_delta
                metrics["tool_argument_delta_chars"] += len(delta.arguments_delta)
                buffer = buffers.setdefault(delta.id, ToolArgumentBuffer(id=delta.id))
                buffer.append(delta, self._repairer)
            elif event.kind == "tool_call_completed" and event.tool_call is not None:
                tool_calls.append(event.tool_call)
            elif event.kind == "usage":
                usage = event.usage
            elif event.kind == "response_failed":
                failed_error = event.error or "model response failed"
            elif event.kind == "response_completed":
                finish_reason = event.finish_reason
                if event.usage is not None:
                    usage = event.usage

        for buffer in buffers.values():
            if buffer.malformed:
                return ParsedResponse(
                    status="malformed_tool_call",
                    text="".join(text_parts),
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                    usage=usage,
                    error=buffer.error,
                    metrics=metrics,
                    tool_argument_repairs=tool_argument_repairs,
                )
            buffered_call = buffer.to_tool_call()
            if buffered_call is None:
                buffered_call = buffer.repair_to_tool_call(self._repairer)
            if buffered_call is not None:
                tool_calls.append(buffered_call)
                if buffer.repair_metadata:
                    metrics["tool_argument_repairs"] += 1
                    tool_argument_repairs.append(buffer.repair_metadata)
            elif buffer.text.strip():
                return ParsedResponse(
                    status="malformed_tool_call",
                    text="".join(text_parts),
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                    usage=usage,
                    error="tool call arguments ended before valid JSON completed",
                    metrics=metrics,
                    tool_argument_repairs=tool_argument_repairs,
                )

        text = sanitize_channel_markup("".join(text_parts))
        if failed_error:
            return ParsedResponse(
                status="malformed_tool_call",
                text=text,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                error=failed_error,
                metrics=metrics,
                tool_argument_repairs=tool_argument_repairs,
            )
        if finish_reason == "length":
            return ParsedResponse(
                status="length_cutoff",
                text=text,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                metrics=metrics,
                tool_argument_repairs=tool_argument_repairs,
            )
        if tool_calls:
            return ParsedResponse(
                status="ok_tool_calls",
                text=text,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                metrics=metrics,
                tool_argument_repairs=tool_argument_repairs,
            )
        pseudo_call, pseudo_error = self._pseudo_tool_call_from_text(text)
        if pseudo_call is not None:
            return ParsedResponse(
                status="pseudo_tool_call",
                text=text,
                tool_calls=[pseudo_call],
                finish_reason=finish_reason,
                usage=usage,
                error=f"model wrote a textual pseudo tool call for {pseudo_call.name}",
                metrics=metrics,
                tool_argument_repairs=tool_argument_repairs,
            )
        if pseudo_error is not None:
            return ParsedResponse(
                status="pseudo_tool_call",
                text=text,
                finish_reason=finish_reason,
                usage=usage,
                error=pseudo_error,
                metrics=metrics,
                tool_argument_repairs=tool_argument_repairs,
            )
        if text.strip():
            return ParsedResponse(
                status="ok_text",
                text=text,
                finish_reason=finish_reason,
                usage=usage,
                metrics=metrics,
                tool_argument_repairs=tool_argument_repairs,
            )
        if saw_reasoning_only_delta:
            return ParsedResponse(
                status="reasoning_only",
                finish_reason=finish_reason,
                usage=usage,
                error="model emitted reasoning-only deltas without user-visible text",
                metrics=metrics,
                tool_argument_repairs=tool_argument_repairs,
            )
        return ParsedResponse(
            status="empty_response",
            finish_reason=finish_reason,
            usage=usage,
            metrics=metrics,
            tool_argument_repairs=tool_argument_repairs,
        )

    def _pseudo_tool_call_from_text(self, text: str) -> tuple[ToolCall | None, str | None]:
        stripped = text.strip()
        if not stripped:
            return None, None
        for payload in self._json_objects_from_text(stripped):
            call, error = self._pseudo_tool_call_from_payload(payload)
            if call is not None or error is not None:
                return call, error
        return None, None

    def _pseudo_tool_call_from_payload(self, payload: dict[str, Any]) -> tuple[ToolCall | None, str | None]:
        raw_action = payload.get("action") or payload.get("tool") or payload.get("tool_name") or payload.get("name")
        if raw_action is None:
            return None, None
        action = str(raw_action).strip().lower().replace("-", "_")
        if action in {"search", "web_search"}:
            query = payload.get("query") or payload.get("q")
            if not isinstance(query, str) or not query.strip():
                return None, "pseudo web_search tool call is missing a non-empty query"
            arguments: dict[str, Any] = {"query": query.strip()}
            top_n = payload.get("top_n", payload.get("limit", payload.get("num_results")))
            if top_n is not None:
                try:
                    arguments["top_n"] = min(max(int(top_n), 1), 10)
                except (TypeError, ValueError):
                    return None, "pseudo web_search top_n must be an integer"
            if payload.get("recency_days") is not None:
                arguments["recency_days"] = payload["recency_days"]
            return ToolCall(
                id=self._pseudo_tool_id("web_search", arguments),
                name="web_search",
                arguments=arguments,
            ), None
        if action in {"fetch", "web_fetch"}:
            url = payload.get("url")
            if not isinstance(url, str) or not url.strip():
                return None, "pseudo web_fetch tool call is missing a non-empty url"
            return ToolCall(
                id=self._pseudo_tool_id("web_fetch", {"url": url.strip()}),
                name="web_fetch",
                arguments={"url": url.strip()},
            ), None
        if action in {"read_file", "write_file", "patch_file", "delete_path", "run_command", "run_tests"}:
            return None, f"pseudo tool call must use native tool-calling protocol: {action}"
        return None, None

    def _json_objects_from_text(self, text: str) -> list[dict[str, Any]]:
        decoder = json.JSONDecoder()
        objects: list[dict[str, Any]] = []
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                parsed, _end = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                objects.append(parsed)
        return objects

    @staticmethod
    def _pseudo_tool_id(name: str, arguments: dict[str, Any]) -> str:
        encoded = json.dumps({"name": name, "arguments": arguments}, sort_keys=True).encode("utf-8")
        return f"pseudo-{hashlib.sha256(encoded).hexdigest()[:12]}"
