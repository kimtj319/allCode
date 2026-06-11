"""Provider-neutral web search backend contracts."""

from __future__ import annotations

import os
import hashlib
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from allCode.config.schema import WebConfig
from allCode.core.models import CoreModel
from allCode.tools.web_health import WebHealth, host_from_url


class WebSearchUnavailable(RuntimeError):
    """Raised when no configured search backend can serve a query."""


class WebEvidence(CoreModel):
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str | None = None
    published_at: str | None = None
    display_domain: str | None = None
    snippet_hash: str | None = None
    retrieved_at: str | None = None
    rank: int = 0


class WebSearchProvider(Protocol):
    def health(self) -> WebHealth:
        raise NotImplementedError("web search providers may expose health metadata")

    async def search(self, query: str, *, top_n: int = 5) -> list[WebEvidence]:
        raise NotImplementedError("web search providers must implement search")


class DisabledWebSearchProvider:
    def health(self) -> WebHealth:
        return WebHealth(
            configured=False,
            backend="disabled",
            supports_json=False,
            last_error_type="web_search_unavailable",
        )

    async def search(self, query: str, *, top_n: int = 5) -> list[WebEvidence]:
        _ = query, top_n
        raise WebSearchUnavailable("web_search backend is disabled. Configure ALLCODE_WEB_SEARCH_BACKEND and ALLCODE_WEB_SEARCH_URL.")


class HttpWebSearchProvider:
    """HTTP JSON search provider with a small provider-neutral response parser."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key_env: str | None = None,
        timeout_seconds: int = 15,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._api_key_env = api_key_env
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    def health(self) -> WebHealth:
        return WebHealth(
            configured=bool(self._endpoint),
            backend="http_json",
            search_url_host=host_from_url(self._endpoint),
            supports_json=True,
        )

    async def search(self, query: str, *, top_n: int = 5) -> list[WebEvidence]:
        headers = {"Content-Type": "application/json"}
        if self._api_key_env:
            api_key = os.environ.get(self._api_key_env)
            if not api_key:
                raise WebSearchUnavailable(f"web_search API key env is not set: {self._api_key_env}")
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"query": query, "top_n": top_n}
        if self._http_client is not None:
            response = await self._http_client.post(self._endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return parse_web_evidence(response.json(), top_n=top_n)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(self._endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return parse_web_evidence(response.json(), top_n=top_n)


class SearxngSearchProvider:
    """SearXNG JSON API provider."""

    def __init__(
        self,
        *,
        search_url: str,
        timeout_seconds: int = 15,
        language: str = "ko-KR",
        categories: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._search_url = search_url
        self._timeout_seconds = timeout_seconds
        self._language = language
        self._categories = categories or ["general"]
        self._http_client = http_client

    def health(self) -> WebHealth:
        return WebHealth(
            configured=bool(self._search_url),
            backend="searxng",
            search_url_host=host_from_url(self._search_url),
            supports_json=True,
        )

    async def search(self, query: str, *, top_n: int = 5) -> list[WebEvidence]:
        params = {
            "q": query,
            "format": "json",
            "language": self._language,
            "categories": ",".join(self._categories),
        }
        if self._http_client is not None:
            response = await self._http_client.get(self._search_url, params=params)
            return self._parse_response(response, top_n)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(self._search_url, params=params)
            return self._parse_response(response, top_n)

    def _parse_response(self, response: httpx.Response, top_n: int) -> list[WebEvidence]:
        if response.status_code in {403, 404, 406}:
            raise WebSearchUnavailable("SearXNG JSON search API is unavailable or disabled for this instance.")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise WebSearchUnavailable("SearXNG response was not JSON. Check format=json support.") from exc
        return parse_web_evidence(payload, top_n=top_n)


def provider_from_config(config: WebConfig) -> WebSearchProvider:
    if config.backend == "disabled" or not config.search_url:
        return DisabledWebSearchProvider()
    if config.backend == "searxng":
        return SearxngSearchProvider(
            search_url=config.search_url,
            timeout_seconds=config.timeout_seconds,
            language=config.default_language,
            categories=config.default_categories,
        )
    return HttpWebSearchProvider(
        endpoint=config.search_url,
        api_key_env=config.api_key_env,
        timeout_seconds=config.timeout_seconds,
    )


def parse_web_evidence(payload: Any, *, top_n: int = 5) -> list[WebEvidence]:
    rows = _result_rows(payload)
    evidence: list[WebEvidence] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("name") or "")
        url = str(row.get("url") or row.get("link") or "")
        snippet = str(row.get("snippet") or row.get("description") or row.get("content") or "")
        evidence.append(
            WebEvidence(
                title=title,
                url=url,
                snippet=snippet[:800],
                source=str(row.get("engine") or row.get("source") or "") or None,
                published_at=str(row.get("publishedDate") or row.get("published_at") or "") or None,
                display_domain=_display_domain(url),
                snippet_hash=_snippet_hash(snippet),
                retrieved_at=_utc_timestamp(),
                rank=len(evidence) + 1,
            )
        )
        if len(evidence) >= top_n:
            break
    return evidence


def _result_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("results", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _display_domain(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.netloc or None


def _snippet_hash(snippet: str) -> str | None:
    if not snippet:
        return None
    return hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16]


def _utc_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
