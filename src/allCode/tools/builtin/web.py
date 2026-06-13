"""Evidence-only web tools for routing-aware use."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.web_provider import (
    DisabledWebSearchProvider,
    DisabledWebFetchProvider,
    WebEvidence,
    WebFetchProvider,
    WebSearchProvider,
    WebSearchUnavailable,
)
from allCode.tools.web_health import WebHealth, health_payload


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
        if _network_suppressed(context.user_prompt) or context.environment.get("ALLCODE_NO_NETWORK"):
            return _unavailable_result(
                call,
                query,
                reason="web_search was skipped because external network access is disabled for this turn.",
                health=WebHealth(backend="blocked", last_error_type="no_external_network", offline=True),
            )
        try:
            bundle = await self._provider.search(query, top_n=top_n)
        except WebSearchUnavailable as exc:
            return _unavailable_result(call, query, reason=str(exc), health=_provider_health(self._provider, last_error_type="web_search_unavailable"))
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=f"web_search provider failed: {exc}",
                error_type=exc.__class__.__name__,
                metadata={
                    "query": query,
                    "evidence_kind": "web_error",
                    "evidence_bundle": [],
                    "web_health": health_payload(_provider_health(self._provider, last_error_type=exc.__class__.__name__)),
                },
            )
        if not bundle:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="web_search provider returned no evidence.",
                error_type="ExternalSearchNoResults",
                metadata={"query": query, "evidence_kind": "web_no_results", "evidence_bundle": []},
            )
        return _bundle_result(call, query, bundle)


class WebFetchTool:
    def __init__(self, provider: WebFetchProvider | None = None) -> None:
        self._provider = provider or DisabledWebFetchProvider()
        self.definition = ToolDefinition(
            name="web_fetch",
            description="Collect a sanitized structured evidence bundle from a web page URL or supplied page content.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 12000},
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
            if _network_suppressed(context.user_prompt) or context.environment.get("ALLCODE_NO_NETWORK"):
                return _fetch_unavailable_result(
                    call,
                    url,
                    reason="web_fetch was skipped because external network access is disabled for this turn.",
                    health=WebHealth(backend="blocked", last_error_type="no_external_network", offline=True),
                )
            try:
                evidence = await self._provider.fetch(url, max_chars=_max_chars(call.arguments.get("max_chars")))
            except WebSearchUnavailable as exc:
                return _fetch_unavailable_result(
                    call,
                    url,
                    reason=str(exc),
                    health=_provider_health(self._provider, last_error_type="web_fetch_unavailable"),
                )
            except Exception as exc:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    error=f"web_fetch provider failed: {exc}",
                    error_type=exc.__class__.__name__,
                    metadata={
                        "url": url,
                        "evidence_kind": "web_error",
                        "evidence_bundle": [],
                        "web_health": health_payload(_provider_health(self._provider, last_error_type=exc.__class__.__name__)),
                    },
                )
            return _fetch_bundle_result(call, evidence)
        evidence = {"title": str(call.arguments.get("title", "")), "url": url, "snippet": content[:500]}
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=f"Collected page evidence for: {url}",
            metadata={"url": url, "evidence_bundle": [evidence]},
        )


def web_tools(provider: WebSearchProvider | None = None, fetch_provider: WebFetchProvider | None = None) -> list:
    return [WebSearchTool(provider), WebFetchTool(fetch_provider)]


def _top_n(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 5
    return min(max(parsed, 1), 10)


def _max_chars(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 5000
    return min(max(parsed, 500), 12000)


def _bundle_from_results(results: list, *, top_n: int) -> list[WebEvidence]:
    bundle: list[WebEvidence] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", ""))
        url = str(item.get("url", ""))
        snippet = str(item.get("snippet", ""))[:800]
        if not title and not url:
            continue
        bundle.append(
            WebEvidence(
                title=title,
                url=url,
                snippet=snippet,
                display_domain=urlparse(url).netloc or None,
                snippet_hash=hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16] if snippet else None,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
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
        metadata={
            "query": query,
            "evidence_kind": "web_evidence",
            "evidence_count": len(bundle),
            "evidence_bundle": [item.model_dump(mode="json") for item in bundle],
            "web_health": health_payload(WebHealth(configured=True, backend="evidence_bundle", supports_json=True)),
            "observation": {
                "kind": "web",
                "target": query,
                "summary": f"Collected {len(bundle)} web evidence item(s)",
                "risk": "low",
            },
        },
    )


def _fetch_bundle_result(call: ToolCall, evidence: WebEvidence) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=True,
        content=f"Collected page evidence for: {evidence.url}",
        metadata={
            "url": evidence.url,
            "evidence_kind": "web_evidence",
            "evidence_count": 1,
            "evidence_bundle": [evidence.model_dump(mode="json")],
            "web_health": health_payload(WebHealth(configured=True, backend="web_fetch", supports_json=False)),
            "observation": {
                "kind": "web",
                "target": evidence.url,
                "summary": "Collected 1 web page evidence item",
                "risk": "low",
            },
        },
    )


def _unavailable_result(call: ToolCall, query: str, *, reason: str, health: WebHealth) -> ToolResult:
    unavailable = {
        "backend": health.backend,
        "query": query,
        "reason": reason,
        "next_step": "Configure ALLCODE_WEB_SEARCH_BACKEND and ALLCODE_WEB_SEARCH_URL.",
    }
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=False,
        content="",
        error=reason,
        error_type="web_search_unavailable",
        metadata={
            "query": query,
            "backend": health.backend,
            "evidence_kind": "web_unavailable",
            "unavailable": unavailable,
            "evidence_bundle": [],
            "web_health": health_payload(health),
        },
    )


def _fetch_unavailable_result(call: ToolCall, url: str, *, reason: str, health: WebHealth) -> ToolResult:
    unavailable = {
        "backend": health.backend,
        "url": url,
        "reason": reason,
        "next_step": "Configure ALLCODE_WEB_SEARCH_BACKEND and ALLCODE_WEB_SEARCH_URL.",
    }
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=False,
        content="",
        error=reason,
        error_type="web_fetch_unavailable",
        metadata={
            "url": url,
            "backend": health.backend,
            "evidence_kind": "web_unavailable",
            "unavailable": unavailable,
            "evidence_bundle": [],
            "web_health": health_payload(health),
        },
    )


def _provider_health(provider: WebSearchProvider, *, last_error_type: str = "") -> WebHealth:
    health_method = getattr(provider, "health", None)
    if callable(health_method):
        try:
            health = health_method()
            if isinstance(health, WebHealth):
                return health.model_copy(update={"last_error_type": last_error_type or health.last_error_type})
        except Exception:
            return WebHealth(last_error_type=last_error_type or "health_failed")
    return WebHealth(configured=True, backend=provider.__class__.__name__, last_error_type=last_error_type)


def _network_suppressed(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    compact = "".join(lowered.split())
    english = any(marker in lowered for marker in ("no external network", "no network", "offline", "do not search", "without web"))
    korean = any(marker in compact for marker in ("외부검색금지", "검색금지", "네트워크차단", "인터넷금지", "웹검색금지"))
    return english or korean
