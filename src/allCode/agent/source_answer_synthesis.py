"""Synthesis helpers for source-inspection observations."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.language import ResponseLanguage
from allCode.core.models import ToolResult


def probe_evidence_lines(
    tool_results: Sequence[ToolResult],
    *,
    language: ResponseLanguage,
) -> tuple[list[str], list[str], list[str]]:
    file_lines: list[str] = []
    symbol_lines: list[str] = []
    edge_lines: list[str] = []
    for result in tool_results:
        observation = result.metadata.get("observation")
        if not result.ok or not isinstance(observation, dict) or observation.get("kind") != "source_probe":
            continue
        target = _clean(str(observation.get("target") or result.metadata.get("file_path") or ""))
        if not target:
            continue
        ranges = _range_labels(observation.get("line_ranges"))
        backend = _clean(str(observation.get("backend") or result.metadata.get("backend") or ""))
        detail = []
        if ranges:
            detail.append("ranges " + ", ".join(ranges[:4]))
        if backend:
            detail.append(f"backend `{backend}`")
        if detail:
            file_lines.append(f"`{target}`: " + "; ".join(detail))
        symbols = [str(item) for item in observation.get("observed_symbols", []) if str(item).strip()]
        if symbols:
            symbol_lines.append(f"`{target}`: " + ", ".join(f"`{symbol}`" for symbol in symbols[:8]))
        edges = _edge_labels(observation.get("outgoing_edges"))
        if edges:
            label = "import/reference" if language == "en" else "import/reference"
            edge_lines.append(f"`{target}` {label}: " + ", ".join(edges[:8]))
    return file_lines[:10], symbol_lines[:10], edge_lines[:10]


def _range_labels(value: object) -> list[str]:
    labels: list[str] = []
    if not isinstance(value, list):
        return labels
    for item in value:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        end = item.get("end")
        reason = _clean(str(item.get("reason") or "range"))
        if start and end:
            labels.append(f"{start}-{end}({reason})")
    return labels


def _edge_labels(value: object) -> list[str]:
    labels: list[str] = []
    if not isinstance(value, list):
        return labels
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = _clean(str(item.get("kind") or "edge"))
        target = _clean(str(item.get("target") or item.get("symbol") or ""))
        if target:
            label = f"{kind}:{target}"
            if label not in labels:
                labels.append(label)
    return labels


def _clean(value: str) -> str:
    return value.strip().strip("`")
