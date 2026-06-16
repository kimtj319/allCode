"""Adapt a discovered MCP tool to allCode's BaseTool contract."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.mcp.client import MCPError, MCPStdioClient


def _normalized_tool_name(server: str, tool: str) -> str:
    raw = f"mcp__{server}__{tool}"
    return raw.strip().lower().replace("-", "_")


class MCPTool:
    """Expose one MCP server tool as an allCode tool.

    MCP tools mutate external systems we cannot reason about, so they are treated
    as approval-gated, non-read-only, network side-effecting by default.
    """

    def __init__(
        self,
        *,
        client: MCPStdioClient,
        server_name: str,
        spec: dict[str, Any],
        dispatch: Callable[[Awaitable[Any]], Awaitable[Any]] | None = None,
    ) -> None:
        self._client = client
        # Clients live on the manager's background loop; dispatch re-schedules a
        # client coroutine there and returns an awaitable for the agent loop.
        self._dispatch = dispatch
        self._server_name = server_name
        self._remote_name = str(spec.get("name"))
        schema = spec.get("inputSchema") or {"type": "object", "properties": {}, "additionalProperties": True}
        description = str(spec.get("description") or f"{self._remote_name} (MCP tool from {server_name})")
        self.definition = ToolDefinition(
            name=_normalized_tool_name(server_name, self._remote_name),
            description=description,
            parameters=schema if isinstance(schema, dict) else {"type": "object"},
            read_only=False,
            requires_approval=True,
            group="mcp",
            risk="medium",
            side_effects=["network"],
        )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            coro = self._client.call_tool(self._remote_name, dict(call.arguments or {}))
            result = await (self._dispatch(coro) if self._dispatch is not None else coro)
        except MCPError as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type="mcp_error")
        except Exception as exc:  # noqa: BLE001 - surface any transport failure as a tool error
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)
        text = _content_to_text(result.get("content"))
        is_error = bool(result.get("isError"))
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=not is_error,
            content=text,
            error=text if is_error else None,
            error_type="mcp_tool_error" if is_error else None,
            metadata={
                "mcp_server": self._server_name,
                "mcp_tool": self._remote_name,
                "structured_content": result.get("structuredContent"),
            },
        )


class MCPResourceTool:
    """Expose an MCP server's resources/read as a read-only allCode tool.

    MCP resources are server-curated context (files, docs, records). This tool
    lets the agent pull a resource by URI into the turn; advertised URIs are
    listed in the description so the model knows what is available.
    """

    def __init__(
        self,
        *,
        client: MCPStdioClient,
        server_name: str,
        resources: list[dict[str, Any]],
        dispatch: Callable[[Awaitable[Any]], Awaitable[Any]] | None = None,
    ) -> None:
        self._client = client
        self._dispatch = dispatch
        self._server_name = server_name
        listing = "; ".join(
            f"{item.get('uri')} ({item.get('name')})" if item.get("name") else str(item.get("uri"))
            for item in resources[:20]
        )
        self.definition = ToolDefinition(
            name=_normalized_tool_name(server_name, "read_resource"),
            description=f"Read a resource from MCP server '{server_name}'. Available: {listing}",
            parameters={
                "type": "object",
                "properties": {"uri": {"type": "string"}},
                "required": ["uri"],
                "additionalProperties": False,
            },
            read_only=True,
            requires_approval=False,
            group="mcp",
            risk="low",
            side_effects=["network"],
        )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        uri = str(call.arguments.get("uri", ""))
        if not uri:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error="uri is required", error_type="missing_uri")
        try:
            coro = self._client.read_resource(uri)
            result = await (self._dispatch(coro) if self._dispatch is not None else coro)
        except MCPError as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type="mcp_error")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)
        text = _resource_contents_to_text(result.get("contents"))
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=text,
            metadata={"mcp_server": self._server_name, "uri": uri},
        )


def _resource_contents_to_text(contents: Any) -> str:
    if not isinstance(contents, list):
        return str(contents or "")
    parts: list[str] = []
    for item in contents:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        if item.get("text"):
            parts.append(str(item["text"]))
        elif item.get("blob"):
            parts.append(f"[binary resource {item.get('uri', '')} omitted]")
    return "\n".join(part for part in parts if part)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            kind = item.get("type")
            if kind == "text":
                parts.append(str(item.get("text", "")))
            elif kind in {"image", "audio"}:
                parts.append(f"[{kind} content omitted]")
            elif item.get("text"):
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
    else:
        parts.append(str(content))
    return "\n".join(part for part in parts if part)
