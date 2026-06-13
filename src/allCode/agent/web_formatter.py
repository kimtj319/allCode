"""Formatting helpers for grounded web evidence synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from allCode.agent.language import ResponseLanguage

WEB_TOOL_NAMES = {"web_search", "web_fetch"}
MAX_WEB_REFS = 5
MAX_WEB_SNIPPET_CHARS = 220


@dataclass(frozen=True)
class WebReference:
    index: int
    title: str
    url: str
    snippet: str = ""
    domain: str = ""


def metadata_has_web_evidence(metadata: dict[str, Any]) -> bool:
    return str(metadata.get("tool_name") or "") in WEB_TOOL_NAMES and str(metadata.get("evidence_kind") or "") == "web_evidence"


def metadata_is_web_unavailable(metadata: dict[str, Any]) -> bool:
    if str(metadata.get("tool_name") or "") not in WEB_TOOL_NAMES:
        return False
    return (
        metadata.get("error_type") in {"web_search_unavailable", "web_fetch_unavailable", "ExternalSearchNoResults"}
        or metadata.get("evidence_kind") in {"web_unavailable", "web_error", "web_no_results"}
    )


def web_references_from_bundle(bundle: Any, *, limit: int = MAX_WEB_REFS) -> list[WebReference]:
    if not isinstance(bundle, list):
        return []
    refs: list[WebReference] = []
    seen: set[tuple[str, str]] = set()
    for item in bundle:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title")) or "Untitled"
        url = _clean_text(item.get("url"))
        snippet = _clean_text(item.get("snippet"))[:MAX_WEB_SNIPPET_CHARS]
        if not title and not url:
            continue
        key = (url, title)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            WebReference(
                index=len(refs) + 1,
                title=title,
                url=url,
                snippet=snippet,
                domain=_domain(item, url),
            )
        )
        if len(refs) >= limit:
            break
    return refs


def web_references_from_metadata(metadata: dict[str, Any], *, limit: int = MAX_WEB_REFS) -> list[WebReference]:
    return web_references_from_bundle(metadata.get("evidence_bundle"), limit=limit)


def web_reference_dicts_from_metadata(metadata: dict[str, Any], *, limit: int = MAX_WEB_REFS) -> list[dict[str, str]]:
    return [
        {"title": ref.title, "url": ref.url, "snippet": ref.snippet, "domain": ref.domain}
        for ref in web_references_from_metadata(metadata, limit=limit)
    ]


def format_web_tool_observation(metadata: dict[str, Any], *, response_language: ResponseLanguage) -> str:
    tool_name = str(metadata.get("tool_name") or "web")
    target = str(metadata.get("query") or metadata.get("url") or _observation_target(metadata) or "").strip()
    status = "ok" if metadata.get("ok") else f"failed:{metadata.get('error_type') or 'error'}"
    prefix = f"- {tool_name}"
    if target:
        prefix = f"{prefix} `{target}`"
    if metadata_has_web_evidence(metadata):
        refs = web_references_from_metadata(metadata)
        if refs:
            return "\n".join([f"{prefix} -> {status}", *_reference_lines(refs, response_language=response_language)])
    if metadata_is_web_unavailable(metadata):
        reason = _unavailable_reason(metadata)
        return f"{prefix} -> {status}\n  {reason}"
    return f"{prefix} -> {status}"


def web_citation_guard(messages_have_web_evidence: bool, *, response_language: ResponseLanguage) -> str:
    if not messages_have_web_evidence:
        return ""
    if response_language == "ko":
        return (
            "웹 근거 답변에서는 제공된 Web evidence refs의 번호([1], [2] 등)만 인용하세요. "
            "웹 관찰에 근거한 최신/외부 사실에만 번호를 붙이고, 일반 지식이나 코드 문법 설명에는 억지로 인용을 붙이지 마세요. "
            "제공되지 않은 번호, 비표준 provider citation artifact, 원문에 없는 URL을 만들지 마세요."
        )
    return (
        "For web-grounded answers, cite only the supplied Web evidence refs such as [1] or [2]. "
        "Attach refs only to facts grounded in web observations, not to general knowledge or code syntax. "
        "Do not invent missing ref numbers, non-standard provider citation artifacts, or URLs absent from the evidence."
    )


def format_web_references_for_answer(refs: list[dict[str, str]], *, response_language: ResponseLanguage, limit: int = MAX_WEB_REFS) -> list[str]:
    references = [
        WebReference(
            index=index + 1,
            title=_clean_text(item.get("title")) or "Untitled",
            url=_clean_text(item.get("url")),
            snippet=_clean_text(item.get("snippet"))[:MAX_WEB_SNIPPET_CHARS],
            domain=_clean_text(item.get("domain")) or _display_domain(_clean_text(item.get("url"))),
        )
        for index, item in enumerate(refs[:limit])
    ]
    return _reference_lines(references, response_language=response_language)


def _reference_lines(refs: list[WebReference], *, response_language: ResponseLanguage) -> list[str]:
    header = "Web evidence refs:" if response_language == "en" else "웹 근거 refs:"
    instruction = (
        "  Cite these observations only with the numeric labels below, for example [1]."
        if response_language == "en"
        else "  아래 숫자 라벨만 인용하세요. 예: [1]."
    )
    lines = [f"  {header}", instruction]
    for ref in refs:
        domain = f" ({ref.domain})" if ref.domain else ""
        lines.append(f"  [{ref.index}] {ref.title}{domain}")
        if ref.url:
            lines.append(f"      URL: {ref.url}")
        if ref.snippet:
            lines.append(f"      {ref.snippet}")
    return lines


def _unavailable_reason(metadata: dict[str, Any]) -> str:
    unavailable = metadata.get("unavailable")
    if isinstance(unavailable, dict):
        reason = _clean_text(unavailable.get("reason"))
        backend = _clean_text(unavailable.get("backend"))
        if reason and backend:
            return f"web evidence unavailable via {backend}: {reason}"
        if reason:
            return f"web evidence unavailable: {reason}"
    error = _clean_text(metadata.get("error") or metadata.get("content"))
    return error or "web evidence unavailable"


def _observation_target(metadata: dict[str, Any]) -> str:
    observation = metadata.get("observation")
    if isinstance(observation, dict):
        return str(observation.get("target") or "")
    return ""


def _domain(item: dict[str, Any], url: str) -> str:
    return _clean_text(item.get("display_domain")) or _display_domain(url)


def _display_domain(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).netloc


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())
