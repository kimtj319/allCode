"""Provider-neutral web search backend contracts."""

from __future__ import annotations

import asyncio
import os
import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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


class WebFetchProvider(Protocol):
    def health(self) -> WebHealth:
        raise NotImplementedError("web fetch providers may expose health metadata")

    async def fetch(self, url: str, *, max_chars: int = 5000) -> WebEvidence:
        raise NotImplementedError("web fetch providers must implement fetch")


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


class DisabledWebFetchProvider:
    def health(self) -> WebHealth:
        return WebHealth(
            configured=False,
            backend="disabled",
            supports_json=False,
            last_error_type="web_fetch_unavailable",
        )

    async def fetch(self, url: str, *, max_chars: int = 5000) -> WebEvidence:
        _ = url, max_chars
        raise WebSearchUnavailable("web_fetch backend is disabled. Configure ALLCODE_WEB_SEARCH_BACKEND and ALLCODE_WEB_SEARCH_URL.")


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


class HttpWebFetchProvider:
    """Small HTTP fetch provider that returns sanitized text evidence."""

    def __init__(
        self,
        *,
        timeout_seconds: int = 15,
        http_client: httpx.AsyncClient | None = None,
        backend: str = "http_fetch",
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._backend = backend

    def health(self) -> WebHealth:
        return WebHealth(configured=True, backend=self._backend, supports_json=False)

    async def fetch(self, url: str, *, max_chars: int = 5000) -> WebEvidence:
        if self._http_client is not None:
            response = await self._http_client.get(url)
            return self._parse_response(url, response, max_chars=max_chars)
        async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url)
            return self._parse_response(url, response, max_chars=max_chars)

    def _parse_response(self, url: str, response: httpx.Response, *, max_chars: int) -> WebEvidence:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        text = response.text
        if "html" in content_type.lower() or "<html" in text.lower():
            title, snippet = sanitize_html_to_text(text, max_chars=max_chars)
        else:
            title = ""
            snippet = _collapse_ws(text)[:max_chars]
        return WebEvidence(
            title=title,
            url=str(response.url) or url,
            snippet=snippet,
            source="web_fetch",
            display_domain=_display_domain(str(response.url) or url),
            snippet_hash=_snippet_hash(snippet),
            retrieved_at=_utc_timestamp(),
            rank=1,
        )


class DuckDuckGoHtmlSearchProvider:
    """No-key HTML search provider that normalizes results into evidence."""

    def __init__(
        self,
        *,
        search_url: str = "https://html.duckduckgo.com/html/",
        timeout_seconds: int = 15,
        http_client: httpx.AsyncClient | None = None,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.8,
        max_pages: int = 2,
    ) -> None:
        self._search_url = search_url
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        # DuckDuckGo's HTML endpoint throttles automated traffic with an
        # intermittent anti-bot challenge, so a single request frequently fails
        # even when the query is fine. Retry with backoff (the challenge is
        # transient) and page deeper when one page is short — this is what makes
        # web search persistent instead of giving up on the first failure.
        self._max_attempts = max(1, max_attempts)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._max_pages = max(1, max_pages)

    def health(self) -> WebHealth:
        return WebHealth(
            configured=bool(self._search_url),
            backend="duckduckgo_html",
            search_url_host=host_from_url(self._search_url),
            supports_json=False,
        )

    async def search(self, query: str, *, top_n: int = 5) -> list[WebEvidence]:
        evidence: list[WebEvidence] = []
        seen_urls: set[str] = set()
        last_error: WebSearchUnavailable | None = None
        for page in range(self._max_pages):
            try:
                page_results = await self._fetch_page_with_retry(query, offset=page * 30, top_n=top_n)
            except WebSearchUnavailable as exc:
                last_error = exc
                break
            for item in page_results:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                evidence.append(item.model_copy(update={"rank": len(evidence) + 1}))
                if len(evidence) >= top_n:
                    return evidence
            # A short page means there is nothing more to page into.
            if len(page_results) < top_n:
                break
        if evidence:
            return evidence
        # The HTML scrape produced nothing (commonly a sustained anti-bot
        # throttle). Fall back to the Instant Answer API, a different endpoint
        # that is not throttled the same way, before giving up.
        fallback = await self._instant_answer_search(query, top_n=top_n)
        if fallback:
            return fallback
        if last_error is not None:
            raise last_error
        raise WebSearchUnavailable("DuckDuckGo HTML search returned no parseable evidence.")

    async def _instant_answer_search(self, query: str, *, top_n: int) -> list[WebEvidence]:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        try:
            if self._http_client is not None:
                response = await self._http_client.get(url, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                    response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        return self._parse_instant_answer(payload, query=query, top_n=top_n)

    def _parse_instant_answer(self, payload: Any, *, query: str, top_n: int) -> list[WebEvidence]:
        if not isinstance(payload, dict):
            return []
        collected: list[WebEvidence] = []

        def add(title: str, url: str, snippet: str) -> None:
            title = _collapse_ws(title)
            url = (url or "").strip()
            snippet = _collapse_ws(snippet)[:800]
            if not title or not url:
                return
            collected.append(
                WebEvidence(
                    title=title[:120],
                    url=url,
                    snippet=snippet,
                    source="duckduckgo_instant_answer",
                    display_domain=_display_domain(url),
                    snippet_hash=_snippet_hash(snippet),
                    retrieved_at=_utc_timestamp(),
                    rank=len(collected) + 1,
                )
            )

        abstract = payload.get("AbstractText") or ""
        if abstract and payload.get("AbstractURL"):
            add(payload.get("Heading") or query, payload.get("AbstractURL", ""), abstract)

        def walk(topics: list) -> None:
            for topic in topics:
                if not isinstance(topic, dict):
                    continue
                nested = topic.get("Topics")
                if isinstance(nested, list):
                    walk(nested)
                    continue
                text = topic.get("Text") or ""
                add(text, topic.get("FirstURL", ""), text)

        walk(payload.get("RelatedTopics") or [])

        deduped: list[WebEvidence] = []
        seen: set[str] = set()
        for item in collected:
            if item.url in seen:
                continue
            seen.add(item.url)
            deduped.append(item.model_copy(update={"rank": len(deduped) + 1}))
            if len(deduped) >= top_n:
                break
        return deduped

    async def _fetch_page_with_retry(self, query: str, *, offset: int, top_n: int) -> list[WebEvidence]:
        attempt = 0
        while True:
            attempt += 1
            try:
                return await self._fetch_page(query, offset=offset, top_n=top_n)
            except (WebSearchUnavailable, httpx.HTTPError) as exc:
                if attempt >= self._max_attempts:
                    if isinstance(exc, WebSearchUnavailable):
                        raise
                    raise WebSearchUnavailable(f"DuckDuckGo HTML search request failed: {exc}") from exc
                if self._retry_backoff_seconds:
                    await asyncio.sleep(self._retry_backoff_seconds * attempt)

    async def _fetch_page(self, query: str, *, offset: int, top_n: int) -> list[WebEvidence]:
        params = {"q": query}
        if offset:
            params["s"] = str(offset)
        # A realistic browser User-Agent is treated less aggressively than a
        # bot-identifying one by the anti-bot filter.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self._http_client is not None:
            response = await self._http_client.get(self._search_url, params=params, headers=headers)
            return self._parse_response(response, top_n=top_n)
        async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
            response = await client.get(self._search_url, params=params, headers=headers)
            return self._parse_response(response, top_n=top_n)

    def _parse_response(self, response: httpx.Response, *, top_n: int) -> list[WebEvidence]:
        response.raise_for_status()
        lowered_text = response.text.lower()
        if "anomaly-modal" in lowered_text or "unfortunately, bots use duckduckgo too" in lowered_text:
            raise WebSearchUnavailable("DuckDuckGo HTML search returned an anti-bot challenge instead of search results.")
        parser = _DuckDuckGoHTMLParser(base_url=str(response.url))
        parser.feed(response.text)
        parser.close()
        evidence: list[WebEvidence] = []
        for row in parser.results:
            title = _collapse_ws(row.get("title", ""))
            url = _normalize_duckduckgo_url(row.get("url", ""))
            snippet = _collapse_ws(row.get("snippet", ""))[:800]
            if not title or not url:
                continue
            evidence.append(
                WebEvidence(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="duckduckgo_html",
                    display_domain=_display_domain(url),
                    snippet_hash=_snippet_hash(snippet),
                    retrieved_at=_utc_timestamp(),
                    rank=len(evidence) + 1,
                )
            )
            if len(evidence) >= top_n:
                break
        if not evidence:
            raise WebSearchUnavailable("DuckDuckGo HTML search returned no parseable evidence.")
        return evidence


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
    if config.backend == "duckduckgo_html":
        return DuckDuckGoHtmlSearchProvider(
            search_url=config.search_url,
            timeout_seconds=config.timeout_seconds,
        )
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


def fetch_provider_from_config(config: WebConfig) -> WebFetchProvider:
    if config.backend == "disabled":
        return DisabledWebFetchProvider()
    return HttpWebFetchProvider(timeout_seconds=config.timeout_seconds, backend=f"{config.backend}_fetch")


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


def _normalize_duckduckgo_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.path == "/l/" and parsed.query:
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return url


def _snippet_hash(snippet: str) -> str | None:
    if not snippet:
        return None
    return hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16]


def _utc_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def sanitize_html_to_text(html: str, *, max_chars: int = 5000) -> tuple[str, str]:
    parser = _TextHTMLParser()
    parser.feed(html)
    parser.close()
    title = _collapse_ws(parser.title)
    text = _collapse_ws(" ".join(parser.parts))
    return title, text[: max(0, max_chars)]


def _collapse_ws(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", unescape(value or "")).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", collapsed)


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        _ = attrs
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "canvas"}:
            self._ignored_depth += 1
            return
        if lowered == "title":
            self._in_title = True
            return
        if lowered in {"p", "br", "li", "section", "article", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "canvas"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if lowered == "title":
            self._in_title = False
            return
        if lowered in {"p", "li", "section", "article", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        cleaned = _collapse_ws(data)
        if not cleaned:
            return
        if self._in_title:
            self.title = f"{self.title} {cleaned}".strip()
            return
        self.parts.append(cleaned)


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {str(key).lower(): str(value or "") for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag.lower() == "a" and "result__a" in classes:
            self._flush_current()
            href = attributes.get("href", "")
            self._current = {"url": urljoin(self.base_url, href), "title": "", "snippet": ""}
            self._capture = "title"
            return
        if self._current is not None and "result__snippet" in classes:
            self._capture = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._capture == "title":
            self._capture = ""

    def handle_data(self, data: str) -> None:
        if self._current is None or not self._capture:
            return
        key = self._capture
        self._current[key] = f"{self._current.get(key, '')} {data}".strip()

    def close(self) -> None:
        self._flush_current()
        super().close()

    def _flush_current(self) -> None:
        if self._current and (self._current.get("title") or self._current.get("url")):
            self.results.append(self._current)
        self._current = None
        self._capture = ""
