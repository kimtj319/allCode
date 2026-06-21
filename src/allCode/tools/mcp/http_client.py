"""Model Context Protocol client over Streamable HTTP / SSE.

Speaks JSON-RPC 2.0 to an MCP server reachable at a URL. Each request is an
HTTP POST whose response is either a single JSON object (``application/json``)
or an SSE stream (``text/event-stream``) carrying one ``message`` event with the
JSON-RPC result. This is the transport Claude Code calls "HTTP" / "SSE".

The public surface mirrors :class:`allCode.tools.mcp.client.MCPStdioClient` so
the manager and :class:`MCPTool` treat both transports identically.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from allCode.tools.mcp.client import MCPError

PROTOCOL_VERSION = "2024-11-05"


def _parse_sse(text: str) -> Any:
    """Extract the JSON payload from an SSE response body (data: lines)."""
    data_lines = [line[len("data:") :].strip() for line in text.splitlines() if line.startswith("data:")]
    if not data_lines:
        raise MCPError("SSE response carried no data lines")
    payload = "\n".join(data_lines)
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MCPError(f"invalid SSE JSON payload: {exc}") from exc


class MCPHttpClient:
    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        startup_timeout: float = 8.0,
        request_timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        self._startup_timeout = startup_timeout
        self._request_timeout = request_timeout
        self._next_id = 0
        self._session_id: str | None = None
        # Default to the (larger) per-call budget so tools/call has room; the
        # initialize handshake passes the shorter startup_timeout explicitly.
        self._client = client or httpx.AsyncClient(timeout=request_timeout)
        self._owns_client = client is None
        self._server_info: dict[str, Any] = {}

    async def start(self) -> None:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "allCode", "version": "1.0"},
            },
            timeout=self._startup_timeout,
        )
        self._server_info = result.get("serverInfo", {}) if isinstance(result, dict) else {}
        await self._notify("notifications/initialized", {})

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._request("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return [tool for tool in tools if isinstance(tool, dict) and tool.get("name")]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if not isinstance(result, dict):
            raise MCPError("tools/call returned a non-object result")
        return result

    async def list_resources(self) -> list[dict[str, Any]]:
        try:
            result = await self._request("resources/list", {})
        except MCPError:
            return []
        resources = result.get("resources", []) if isinstance(result, dict) else []
        return [item for item in resources if isinstance(item, dict) and item.get("uri")]

    async def read_resource(self, uri: str) -> dict[str, Any]:
        result = await self._request("resources/read", {"uri": uri})
        if not isinstance(result, dict):
            raise MCPError("resources/read returned a non-object result")
        return result

    async def list_prompts(self) -> list[dict[str, Any]]:
        try:
            result = await self._request("prompts/list", {})
        except MCPError:
            return []
        prompts = result.get("prompts", []) if isinstance(result, dict) else []
        return [item for item in prompts if isinstance(item, dict) and item.get("name")]

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self._request("prompts/get", {"name": name, "arguments": arguments or {}})
        if not isinstance(result, dict):
            raise MCPError("prompts/get returned a non-object result")
        return result

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- internals -----------------------------------------------------------

    def _allocate_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _request_headers(self) -> dict[str, str]:
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        # A notification has no JSON-RPC response, but a transport error or a 4xx
        # (e.g. session not established) means the session is broken — surface it
        # so start() fails loudly instead of returning a half-initialized client
        # that rejects every later tools/call. Also pick up Mcp-Session-Id here.
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            response = await self._client.post(self._url, content=json.dumps(message), headers=self._request_headers())
        except httpx.HTTPError as exc:
            raise MCPError(f"{method} transport error: {exc}") from exc
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if response.status_code >= 400:
            raise MCPError(f"{method} failed: HTTP {response.status_code}")

    async def _request(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> Any:
        message = {"jsonrpc": "2.0", "id": self._allocate_id(), "method": method, "params": params}
        try:
            kwargs = {"content": json.dumps(message), "headers": self._request_headers()}
            if timeout is not None:
                kwargs["timeout"] = timeout
            response = await self._client.post(self._url, **kwargs)
        except httpx.HTTPError as exc:
            raise MCPError(f"{method} transport error: {exc}") from exc
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if response.status_code >= 400:
            raise MCPError(f"{method} failed: HTTP {response.status_code}")
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            envelope = _parse_sse(response.text)
        else:
            try:
                envelope = response.json()
            except json.JSONDecodeError as exc:
                raise MCPError(f"{method} returned invalid JSON: {exc}") from exc
        if isinstance(envelope, list):  # batched; take the matching id
            envelope = next((item for item in envelope if isinstance(item, dict)), {})
        if not isinstance(envelope, dict):
            raise MCPError(f"{method} returned an unexpected payload")
        if "error" in envelope:
            error = envelope["error"]
            raise MCPError(f"{method} failed: {error.get('message', error) if isinstance(error, dict) else error}")
        return envelope.get("result")
