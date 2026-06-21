"""Add/remove/list MCP servers in the project config.

Shared by the ``/mcp`` slash command and the ``allcode mcp`` CLI so users can
register a Model Context Protocol server without hand-editing config.yaml. All
writes go to the project ``.allCode/config.yaml`` ``mcp.servers`` list and take
effect on the next launch (MCP servers start at session init).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from allCode.config.manager import update_project_config_file
from allCode.config.schema import MCPServerConfig

_CONFIG_REL = Path(".allCode") / "config.yaml"


def _config_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser() / _CONFIG_REL


def list_servers(project_root: str | Path) -> list[dict]:
    """Server dicts currently in the project config (may be empty)."""
    path = _config_path(project_root)
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    mcp = data.get("mcp") or {}
    servers = mcp.get("servers") or []
    return [s for s in servers if isinstance(s, dict)]


def add_server(
    project_root: str | Path,
    name: str,
    *,
    command: str = "",
    args: list[str] | None = None,
    url: str | None = None,
    transport: str = "stdio",
    env: dict[str, str] | None = None,
) -> Path:
    """Validate and persist a server (replacing any existing one of the same name).

    Raises ``ValueError`` (via the schema) if required fields are missing for the
    transport (stdio needs a command; http/sse needs a url)."""
    server = MCPServerConfig(
        name=name,
        transport=transport,
        command=command,
        args=list(args or []),
        url=url,
        env=dict(env or {}),
    )
    servers = [s for s in list_servers(project_root) if s.get("name") != server.name]
    servers.append(server.model_dump(mode="python"))
    return update_project_config_file(project_root, {"mcp": {"servers": servers}})


def remove_server(project_root: str | Path, name: str) -> tuple[Path | None, bool]:
    """Remove a server by name. Returns (path, removed?)."""
    name = (name or "").strip()
    servers = list_servers(project_root)
    remaining = [s for s in servers if s.get("name") != name]
    if len(remaining) == len(servers):
        return None, False
    return update_project_config_file(project_root, {"mcp": {"servers": remaining}}), True


def describe_server(server: dict) -> str:
    """One-line human summary of a configured server."""
    name = server.get("name", "?")
    transport = server.get("transport", "stdio")
    enabled = server.get("enabled", True)
    if transport == "stdio":
        target = " ".join([server.get("command", ""), *server.get("args", [])]).strip()
    else:
        target = server.get("url", "") or ""
    state = "" if enabled else " (disabled)"
    return f"{name} [{transport}]{state}: {target}"
