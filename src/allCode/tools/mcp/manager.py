"""Lifecycle manager that starts configured MCP servers and exposes their tools.

Servers are stdio subprocesses kept alive for the manager's lifetime. The agent
loop is async, so tool calls reach the same servers without per-call startup.
``load_mcp_tools`` is a synchronous helper for the CLI entry point, which builds
the tool registry outside the turn event loop.
"""

from __future__ import annotations

import asyncio
import atexit
import threading
from typing import TYPE_CHECKING

from allCode.tools.mcp.client import MCPStdioClient
from allCode.tools.mcp.http_client import MCPHttpClient
from allCode.tools.mcp.tool import MCPResourceTool, MCPTool

if TYPE_CHECKING:
    from allCode.config.schema import AppConfig, MCPServerConfig


class MCPManager:
    """Owns MCP client subprocesses and the tools they expose.

    All client I/O runs on one dedicated background event loop so the clients can
    be driven both from synchronous setup and from the async agent loop safely.
    """

    def __init__(self, *, startup_timeout: float = 8.0) -> None:
        self._startup_timeout = startup_timeout
        self._clients: list = []
        self._tools: list = []
        self._prompts: list[dict] = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="mcp-loop", daemon=True)
        self._thread.start()
        self._closed = False

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def submit_async(self, coro):
        """Schedule a coroutine on the MCP loop and return an awaitable for the
        caller's running loop (clients are bound to the background loop, so they
        cannot be awaited directly from the agent loop)."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return asyncio.wrap_future(future)

    def add_server(self, server: "MCPServerConfig") -> list[str]:
        """Start one server and register its tools/resources. Returns names added."""
        if server.transport in {"http", "sse"}:
            client = MCPHttpClient(
                url=server.url or "",
                headers=server.headers,
                startup_timeout=self._startup_timeout,
            )
        else:
            client = MCPStdioClient(
                command=server.command,
                args=server.args,
                env=server.env,
                startup_timeout=self._startup_timeout,
            )

        async def _bootstrap() -> tuple[list[dict], list[dict], list[dict]]:
            await client.start()
            return (await client.list_tools(), await client.list_resources(), await client.list_prompts())

        tool_specs, resources, prompts = self._submit(_bootstrap())
        self._clients.append(client)
        added: list[str] = []
        for spec in tool_specs:
            tool = MCPTool(client=client, server_name=server.name, spec=spec, dispatch=self.submit_async)
            self._tools.append(tool)
            added.append(tool.definition.name)
        if resources:
            resource_tool = MCPResourceTool(
                client=client, server_name=server.name, resources=resources, dispatch=self.submit_async
            )
            self._tools.append(resource_tool)
            added.append(resource_tool.definition.name)
        for prompt in prompts:
            self._prompts.append({**prompt, "server": server.name, "client": client})
        return added

    def tools(self) -> list:
        return list(self._tools)

    def prompts(self) -> list[dict]:
        """Prompts advertised by connected servers (MCP prompts → slash commands)."""
        return [{k: v for k, v in prompt.items() if k != "client"} for prompt in self._prompts]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for client in self._clients:
            try:
                self._submit(client.close())
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)


def load_mcp_tools(config: "AppConfig") -> tuple[list[MCPTool], MCPManager | None]:
    """Start enabled MCP servers and return their tools plus the owning manager.

    Failures to start a single server are isolated (logged-skip) so one bad
    server never blocks the rest of the toolset. Returns ``([], None)`` when no
    servers are configured.
    """
    servers = [server for server in config.mcp.servers if server.enabled]
    if not servers:
        return [], None
    manager = MCPManager(startup_timeout=config.mcp.startup_timeout_ms / 1000.0)
    for server in servers:
        try:
            manager.add_server(server)
        except Exception:
            # A misconfigured/unavailable server must not break startup.
            continue
    atexit.register(manager.close)
    return manager.tools(), manager
