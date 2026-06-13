"""Model Context Protocol (MCP) stdio client integration for allCode."""

from allCode.tools.mcp.client import MCPStdioClient, MCPError
from allCode.tools.mcp.manager import MCPManager, load_mcp_tools
from allCode.tools.mcp.tool import MCPTool

__all__ = ["MCPStdioClient", "MCPError", "MCPManager", "MCPTool", "load_mcp_tools"]
