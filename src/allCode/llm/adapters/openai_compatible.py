"""OpenAI-compatible adapter that emits provider-neutral model events."""

from __future__ import annotations

import json
import os
import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from allCode.core.errors import ModelAuthenticationError, ModelConfigurationError
from allCode.core.events import ModelEvent, ModelToolCallDelta
from allCode.core.models import Message, TokenUsage
from allCode.llm.client import ModelResponse
from allCode.llm.response_parser import ResponseParser
from allCode.llm.settings import ModelSettings, ToolSchema


class OpenAICompatibleClient:
    """Minimal HTTP adapter for OpenAI-compatible chat completions."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        retry_sleep_seconds: float = 0.25,
    ) -> None:
        self._http_client = http_client
        self._max_retries = max_retries
        self._retry_sleep_seconds = retry_sleep_seconds

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
    ) -> AsyncIterator[ModelEvent]:
        async with self._client(settings) as client:
            lines = self._stream_lines_with_retry(
                client,
                json_payload=self._payload(messages, tools, settings, stream=True),
                headers=self._headers(settings),
            )
            tool_call_ids_by_index: dict[int, str] = {}
            async for line in lines:
                for event in self._events_from_sse_line(line):
                    if event.kind == "response_failed":
                        yield event
                        continue
                    if event.kind == "tool_call_delta" and event.tool_call_delta is not None:
                        delta = event.tool_call_delta
                        existing_id = tool_call_ids_by_index.get(delta.index)
                        if existing_id is not None and delta.id.startswith("tool-"):
                            call_id = existing_id
                        else:
                            call_id = delta.id
                            tool_call_ids_by_index[delta.index] = call_id
                        if delta.id != call_id:
                            event = ModelEvent(
                                kind="tool_call_delta",
                                tool_call_delta=ModelToolCallDelta(
                                    id=call_id,
                                    index=delta.index,
                                    name=delta.name,
                                    arguments_delta=delta.arguments_delta,
                                ),
                            )
                    yield event

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
    ) -> ModelResponse:
        events = [event async for event in self.stream(messages, tools, settings)]
        parsed = ResponseParser().parse_events(events)
        return ModelResponse(
            final_text=parsed.text,
            tool_calls=parsed.tool_calls,
            finish_reason=parsed.finish_reason,
            usage=parsed.usage or TokenUsage(),
            status=parsed.status,
        )

    def _client(self, settings: ModelSettings) -> httpx.AsyncClient:
        if self._http_client is not None:
            return _BorrowedAsyncClient(self._http_client)
        base_url = settings.base_url or "https://api.openai.com/v1"
        return httpx.AsyncClient(base_url=base_url, timeout=settings.timeout_seconds)

    def _payload(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": settings.model_name,
            "messages": [self._message_payload(message) for message in messages],
            "stream": stream,
            "max_tokens": settings.max_output_tokens,
            "temperature": settings.temperature,
        }
        if stream:
            # Ask the provider to emit a final usage chunk; OpenAI-compatible
            # servers (e.g. vLLM) otherwise omit token counts in streaming mode,
            # which would leave the /status usage gauge stuck at zero.
            payload["stream_options"] = {"include_usage": True}
        self._merge_extra_body(payload, settings.extra_body)
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        return payload

    @staticmethod
    def _merge_extra_body(payload: dict[str, Any], extra_body: dict[str, object]) -> None:
        reserved = {"model", "messages", "stream", "tools"}
        for key, value in extra_body.items():
            if key in reserved:
                continue
            payload[key] = value

    def _headers(self, settings: ModelSettings) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get(settings.api_key_env)
        if not api_key:
            raise ModelConfigurationError(
                f"Model API key is not configured. Export {settings.api_key_env} before running allCode."
            )
        headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def _stream_lines_with_retry(
        self,
        client: httpx.AsyncClient,
        *,
        json_payload: dict[str, Any],
        headers: dict[str, str],
    ) -> AsyncIterator[str]:
        attempt = 0
        while True:
            try:
                async with client.stream(
                    "POST",
                    "/chat/completions",
                    json=json_payload,
                    headers=headers,
                ) as response:
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                        attempt += 1
                        await response.aread()
                        await asyncio.sleep(self._retry_sleep_seconds * attempt)
                        continue
                    self._raise_for_status(response)
                    async for line in response.aiter_lines():
                        yield line
                    return
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise
                attempt += 1
                await asyncio.sleep(self._retry_sleep_seconds * attempt)

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if response.status_code in {401, 403}:
                raise ModelAuthenticationError(
                    "Model endpoint rejected the configured API key. "
                    "Check the API token environment variable and base URL."
                ) from exc
            raise

    def _events_from_sse_line(self, line: str) -> list[ModelEvent]:
        stripped = line.strip()
        if not stripped or not stripped.startswith("data:"):
            return []
        data = stripped.removeprefix("data:").strip()
        if data == "[DONE]":
            return [ModelEvent(kind="response_completed", finish_reason="stop")]
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            return [ModelEvent(kind="response_failed", error=str(exc))]
        return self._events_from_chunk(chunk)

    def _events_from_chunk(self, chunk: dict[str, Any]) -> list[ModelEvent]:
        events: list[ModelEvent] = []
        choices = chunk.get("choices") or []
        for choice in choices:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if text:
                events.append(ModelEvent(kind="text_delta", text=text, metadata={"delta_chars": len(text)}))
            reasoning = (
                delta.get("reasoning")
                or delta.get("reasoning_delta")
                or delta.get("reasoning_content")
            )
            if reasoning:
                events.append(
                    ModelEvent(
                        kind="text_delta",
                        text="",
                        metadata={"reasoning_delta": str(reasoning), "delta_chars": len(str(reasoning))},
                    )
                )
            for raw_tool_call in delta.get("tool_calls") or []:
                function = raw_tool_call.get("function") or {}
                index = raw_tool_call.get("index", 0)
                call_id = raw_tool_call.get("id") or f"tool-{index}"
                events.append(
                    ModelEvent(
                        kind="tool_call_delta",
                        tool_call_delta=ModelToolCallDelta(
                            id=call_id,
                            index=index,
                            name=function.get("name"),
                            arguments_delta=function.get("arguments") or "",
                        ),
                        metadata={"argument_delta_chars": len(function.get("arguments") or "")},
                    )
                )
            legacy_function_call = delta.get("function_call")
            if isinstance(legacy_function_call, dict):
                events.append(
                    ModelEvent(
                        kind="tool_call_delta",
                        tool_call_delta=ModelToolCallDelta(
                            id="function_call",
                            index=0,
                            name=legacy_function_call.get("name"),
                            arguments_delta=legacy_function_call.get("arguments") or "",
                        ),
                        metadata={"argument_delta_chars": len(legacy_function_call.get("arguments") or "")},
                    )
                )
            finish_reason = choice.get("finish_reason")
            if finish_reason:
                events.append(ModelEvent(kind="response_completed", finish_reason=finish_reason))
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            events.append(
                ModelEvent(
                    kind="usage",
                    usage=TokenUsage(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                    ),
                )
            )
        return events

    @staticmethod
    def _message_payload(message: Message) -> dict[str, Any]:
        if message.images:
            # Multimodal content for vision-capable models: text block + one
            # image_url block per attachment.
            content_blocks: list[dict[str, Any]] = []
            if message.content:
                content_blocks.append({"type": "text", "text": message.content})
            for image in message.images:
                content_blocks.append({"type": "image_url", "image_url": {"url": image}})
            payload: dict[str, Any] = {"role": message.role, "content": content_blocks}
        else:
            payload = {"role": message.role, "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments, sort_keys=True),
                    },
                }
                for tool_call in message.tool_calls
            ]
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        return payload


class _BorrowedAsyncClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None
