"""Builtin tool implementations."""

from allCode.tools.builtin.file_ops import file_tools
from allCode.tools.builtin.search import SearchFilesTool
from allCode.tools.builtin.shell import RunCommandTool, RunTestsTool
from allCode.tools.builtin.web import web_tools
from allCode.tools.web_provider import WebSearchProvider


def builtin_tools(*, web_search_provider: WebSearchProvider | None = None) -> list:
    return [
        *file_tools(),
        SearchFilesTool(),
        RunCommandTool(),
        RunTestsTool(),
        *web_tools(web_search_provider),
    ]
