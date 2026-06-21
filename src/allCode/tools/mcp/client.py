"""Minimal Model Context Protocol stdio client.

Speaks JSON-RPC 2.0 over a child process's stdin/stdout using newline-delimited
messages (the MCP stdio transport). Only the tool surface is implemented:
``initialize`` handshake, ``tools/list``, and ``tools/call`` — which is what
allCode needs to expose a server's tools to the agent.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class MCPError(RuntimeError):
    """An MCP server returned an error or violated the protocol."""


PROTOCOL_VERSION = "2024-11-05"


class MCPStdioClient:
    def __init__(
        self,
        *,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        startup_timeout: float = 8.0,
        request_timeout: float = 60.0,
    ) -> None:
        self._command = command
        self._args = list(args or [])
        self._env = dict(env or {})
        self._startup_timeout = startup_timeout
        self._request_timeout = request_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 0
        self._lock = asyncio.Lock()
        self._server_info: dict[str, Any] = {}

    async def start(self) -> None:
        import os

        merged_env = {**os.environ, **self._env}
        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
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
        process = self._process
        if process is None:
            return
        self._process = None
        try:
            if process.stdin is not None and not process.stdin.is_closing():
                process.stdin.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except Exception:
            try:
                process.kill()
                # Reap the killed child so it does not linger as a zombie and the
                # SIGKILL is confirmed delivered.
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                pass

    # -- internals -----------------------------------------------------------

    def _allocate_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise MCPError("MCP server is not running")
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        process.stdin.write(data)
        await process.stdin.drain()

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> Any:
        process = self._process
        if process is None or process.stdout is None:
            raise MCPError("MCP server is not running")
        request_id = self._allocate_id()
        async with self._lock:
            await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            deadline_message = await asyncio.wait_for(
                self._read_response(process, request_id), timeout=timeout or self._request_timeout
            )
        if "error" in deadline_message:
            error = deadline_message["error"]
            raise MCPError(f"{method} failed: {error.get('message', error)}")
        return deadline_message.get("result")

    async def _read_response(self, process: asyncio.subprocess.Process, request_id: int) -> dict[str, Any]:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                raise MCPError("MCP server closed the connection")
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                # Servers may emit non-JSON log lines on stdout; skip them.
                continue
            if not isinstance(message, dict):
                continue
            # Skip notifications / responses for other ids.
            if message.get("id") != request_id:
                continue
            return message
