"""Provider-neutral web search backend contracts."""

from __future__ import annotations

import os
from typing import Any, Protocol

import httpx

from allCode.config.schema import WebConfig
from allCode.core.models import CoreModel


class WebSearchUnavailable(RuntimeError):
    """Raised when no configured search backend can serve a query."""


class WebEvidence(CoreModel):
    title: str = ""
    url: str = ""
    snippet: str = ""


class WebSearchProvider(Protocol):
    async def search(self, query: str, *, top_n: int = 5) -> list[WebEvidence]:
        raise NotImplementedError("web search providers must implement search")


class DisabledWebSearchProvider:
    async def search(self, query: str, *, top_n: int = 5) -> list[WebEvidence]:
        raise WebSearchUnavailable("web_search provider is not configured.")


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


def provider_from_config(config: WebConfig) -> WebSearchProvider:
    if not config.search_url:
        return DisabledWebSearchProvider()
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
        evidence.append(WebEvidence(title=title, url=url, snippet=snippet[:800]))
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
