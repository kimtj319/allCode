"""Builtin tool implementations."""

from allCode.tools.builtin.file_ops import file_tools
from allCode.tools.builtin.glob import GlobFilesTool
from allCode.tools.builtin.search import SearchFilesTool
from allCode.tools.builtin.shell import (
    GetCommandOutputTool,
    KillCommandTool,
    RunCommandTool,
    RunTestsTool,
)
from allCode.tools.builtin.source_overview import SourceOverviewTool
from allCode.tools.builtin.source_probe import SourceProbeTool
from allCode.tools.builtin.tree import ListTreeTool
from allCode.tools.builtin.web import web_tools
from allCode.tools.web_provider import WebFetchProvider, WebSearchProvider


def builtin_tools(
    *,
    web_search_provider: WebSearchProvider | None = None,
    web_fetch_provider: WebFetchProvider | None = None,
    shell_sandbox: str = "off",
) -> list:
    return [
        *file_tools(),
        SearchFilesTool(),
        GlobFilesTool(),
        ListTreeTool(),
        SourceOverviewTool(),
        SourceProbeTool(),
        RunCommandTool(shell_sandbox=shell_sandbox),
        RunTestsTool(shell_sandbox=shell_sandbox),
        GetCommandOutputTool(),
        KillCommandTool(),
        *web_tools(web_search_provider, web_fetch_provider),
    ]
