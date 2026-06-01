"""Evidence-only web tools for routing-aware use."""

from __future__ import annotations

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.web_provider import (
    DisabledWebSearchProvider,
    WebEvidence,
    WebSearchProvider,
    WebSearchUnavailable,
)


class WebSearchTool:
    def __init__(self, provider: WebSearchProvider | None = None) -> None:
        self._provider = provider or DisabledWebSearchProvider()
        self.definition = ToolDefinition(
            name="web_search",
            description="Collect a structured evidence bundle from web search results.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_n": {"type": "integer", "minimum": 1, "maximum": 10},
                    "results": {"type": "array"},
                },
                "required": ["query"],
                "additionalProperties": True,
            },
            read_only=True,
            group="web",
        )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        query = str(call.arguments["query"])
        results = call.arguments.get("results", [])
        top_n = _top_n(call.arguments.get("top_n", call.arguments.get("limit", 5)))
        if isinstance(results, list) and results:
            bundle = _bundle_from_results(results, top_n=top_n)
            return _bundle_result(call, query, bundle)
        try:
            bundle = await self._provider.search(query, top_n=top_n)
        except WebSearchUnavailable as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=str(exc),
                error_type="ExternalSearchUnavailable",
                metadata={"query": query, "evidence_bundle": []},
            )
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=f"web_search provider failed: {exc}",
                error_type=exc.__class__.__name__,
                metadata={"query": query, "evidence_bundle": []},
            )
        if not bundle:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="web_search provider returned no evidence.",
                error_type="ExternalSearchNoResults",
                metadata={"query": query, "evidence_bundle": []},
            )
        return _bundle_result(call, query, bundle)


class WebFetchTool:
    definition = ToolDefinition(
        name="web_fetch",
        description="Return a structured evidence bundle from supplied page content.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["url"],
            "additionalProperties": True,
        },
        read_only=True,
        group="web",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        url = str(call.arguments["url"])
        content = str(call.arguments.get("content", ""))
        if not content:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="web_fetch requires injected page content in this MVP.",
                error_type="ExternalFetchUnavailable",
                metadata={"url": url, "evidence_bundle": []},
            )
        evidence = {"title": str(call.arguments.get("title", "")), "url": url, "snippet": content[:500]}
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=f"Collected page evidence for: {url}",
            metadata={"url": url, "evidence_bundle": [evidence]},
        )


def web_tools(provider: WebSearchProvider | None = None) -> list:
    return [WebSearchTool(provider), WebFetchTool()]


def _top_n(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 5
    return min(max(parsed, 1), 10)


def _bundle_from_results(results: list, *, top_n: int) -> list[WebEvidence]:
    bundle: list[WebEvidence] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        bundle.append(
            WebEvidence(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=str(item.get("snippet", ""))[:800],
            )
        )
        if len(bundle) >= top_n:
            break
    return bundle


def _bundle_result(call: ToolCall, query: str, bundle: list[WebEvidence]) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=True,
        content=f"Collected {len(bundle)} web evidence item(s) for query: {query}",
        metadata={"query": query, "evidence_bundle": [item.model_dump(mode="json") for item in bundle]},
    )
