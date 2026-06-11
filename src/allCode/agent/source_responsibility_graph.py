"""Lightweight responsibility graph for source-analysis synthesis."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from allCode.agent.source_analysis_types import RepresentativeFile, SourceEdge
from allCode.core.models import CoreModel, ToolResult

MAX_SYMBOLS_PER_FILE = 8
MAX_GRAPH_NODES = 16
MAX_GRAPH_ENTRYPOINTS = 6
MAX_GRAPH_FLOWS = 10
MAX_GRAPH_LIMITATIONS = 8
MAX_NODE_ANCHORS = 3
MAX_NODE_EDGES = 4
MAX_RENDERED_NODES = 10
MAX_RENDERED_FLOWS = 6
MAX_RENDERED_LIMITATIONS = 5
MAX_COMPACT_NODES = 5


class SourceResponsibilityNode(CoreModel):
    path: str
    symbol: str
    role_hint: str = ""
    body_anchors: list[str] = Field(default_factory=list)
    signature_anchors: list[str] = Field(default_factory=list)
    incoming_edges: list[str] = Field(default_factory=list)
    outgoing_edges: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class SourceResponsibilityGraph(CoreModel):
    nodes: list[SourceResponsibilityNode] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    flows: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def build_source_responsibility_graph(
    tool_results: Sequence[ToolResult],
    *,
    representative_files: Sequence[RepresentativeFile],
    edges: Sequence[SourceEdge],
) -> SourceResponsibilityGraph:
    observations = _source_probe_observations(tool_results)
    outgoing_by_path = _outgoing_by_path(edges)
    incoming_by_path = _incoming_by_path(edges)
    nodes: list[SourceResponsibilityNode] = []
    for observation in observations:
        path = _clean_path(str(observation.get("target") or ""))
        if not path:
            continue
        ranges = _range_anchors(path, observation.get("line_ranges"))
        body_by_symbol = _anchors_by_symbol(ranges, body=True)
        signature_by_symbol = _anchors_by_symbol(ranges, body=False)
        observed_symbols = _observed_symbols(observation)
        wide_symbols = _wide_symbols(observation)
        symbols = _rank_symbols(observed_symbols, body_by_symbol, signature_by_symbol, wide_symbols)
        if not symbols:
            symbols = [Path(path).stem]
        for symbol in symbols[:MAX_SYMBOLS_PER_FILE]:
            body_anchors = body_by_symbol.get(symbol, [])
            signature_anchors = signature_by_symbol.get(symbol, [])
            limitations = _node_limitations(symbol, body_anchors=body_anchors, wide_symbols=wide_symbols)
            nodes.append(
                SourceResponsibilityNode(
                    path=path,
                    symbol=symbol,
                    role_hint=_role_hint(symbol, path=path, outgoing_edges=outgoing_by_path.get(path, [])),
                    body_anchors=body_anchors[:MAX_NODE_ANCHORS],
                    signature_anchors=signature_anchors[:MAX_NODE_ANCHORS],
                    incoming_edges=incoming_by_path.get(path, [])[:MAX_NODE_EDGES],
                    outgoing_edges=outgoing_by_path.get(path, [])[:MAX_NODE_EDGES],
                    limitations=limitations[:MAX_NODE_ANCHORS],
                    confidence=_confidence(body_anchors=body_anchors, signature_anchors=signature_anchors, edges=outgoing_by_path.get(path, [])),
                )
            )
    if not nodes:
        nodes = _nodes_from_representative_files(representative_files, outgoing_by_path=outgoing_by_path)
    return SourceResponsibilityGraph(
        nodes=nodes[:MAX_GRAPH_NODES],
        entrypoints=_entrypoint_nodes(nodes)[:MAX_GRAPH_ENTRYPOINTS],
        flows=_flow_lines(edges, nodes)[:MAX_GRAPH_FLOWS],
        limitations=_graph_limitations(nodes, representative_files)[:MAX_GRAPH_LIMITATIONS],
    )


def responsibility_graph_from_payload(value: object) -> SourceResponsibilityGraph:
    if isinstance(value, SourceResponsibilityGraph):
        return value
    if isinstance(value, dict):
        try:
            return SourceResponsibilityGraph.model_validate(value)
        except Exception:
            return SourceResponsibilityGraph()
    return SourceResponsibilityGraph()


def render_responsibility_matrix(value: object, *, language: str) -> list[str]:
    graph = responsibility_graph_from_payload(value)
    if not graph.nodes:
        return []
    if language == "en":
        lines = ["Function responsibility matrix:"]
        for node in graph.nodes[:MAX_RENDERED_NODES]:
            details = _node_details(node, language=language)
            lines.append(f"- `{node.path}` `{node.symbol}`: {node.role_hint}; {details}")
        if graph.flows:
            lines.extend(["", "Responsibility flow hints:", *[f"- {flow}" for flow in graph.flows[:MAX_RENDERED_FLOWS]]])
        if graph.limitations:
            lines.extend(["", "Responsibility graph limits:", *[f"- {item}" for item in graph.limitations[:MAX_RENDERED_LIMITATIONS]]])
        return lines
    lines = ["함수/모듈 책임 매트릭스:"]
    for node in graph.nodes[:MAX_RENDERED_NODES]:
        details = _node_details(node, language=language)
        lines.append(f"- `{node.path}` `{node.symbol}`: {node.role_hint}; {details}")
    if graph.flows:
        lines.extend(["", "책임 흐름 단서:", *[f"- {flow}" for flow in graph.flows[:MAX_RENDERED_FLOWS]]])
    if graph.limitations:
        lines.extend(["", "책임 그래프 한계:", *[f"- {item}" for item in graph.limitations[:MAX_RENDERED_LIMITATIONS]]])
    return lines


def render_compact_responsibility_matrix(value: object, *, language: str) -> str:
    graph = responsibility_graph_from_payload(value)
    if not graph.nodes:
        return ""
    labels = []
    for node in graph.nodes[:MAX_COMPACT_NODES]:
        anchors = node.body_anchors or node.signature_anchors
        suffix = f" anchors={', '.join(anchors[:2])}" if anchors else ""
        labels.append(f"{node.path}:{node.symbol}={node.role_hint}{suffix}")
    if language == "en":
        return "responsibilities=" + "; ".join(labels)
    return "책임=" + "; ".join(labels)


def _source_probe_observations(tool_results: Sequence[ToolResult]) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for result in tool_results:
        observation = result.metadata.get("observation")
        if result.ok and isinstance(observation, dict) and observation.get("kind") == "source_probe":
            observations.append(observation)
    return observations


def _range_anchors(path: str, value: object) -> list[tuple[str, str]]:
    anchors: list[tuple[str, str]] = []
    if not isinstance(value, list):
        return anchors
    for item in value:
        if not isinstance(item, dict):
            continue
        start = _positive_int(item.get("start"))
        end = _positive_int(item.get("end"))
        if not start or not end:
            continue
        reason = str(item.get("reason") or "range").strip()
        symbol = str(item.get("symbol") or "").strip()
        label = f"`{path}:L{start}-L{end}({reason}{':' + symbol if symbol else ''})`"
        anchors.append((symbol, label))
    return anchors


def _anchors_by_symbol(ranges: Sequence[tuple[str, str]], *, body: bool) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for symbol, label in ranges:
        is_body = "body_sample" in label
        if body != is_body:
            continue
        key = symbol or "__module__"
        grouped.setdefault(key, []).append(label)
        if "." in key:
            grouped.setdefault(key.rsplit(".", 1)[-1], []).append(label)
    return grouped


def _observed_symbols(observation: dict[str, object]) -> list[str]:
    return _dedupe([str(item).strip() for item in observation.get("observed_symbols", []) if str(item).strip()])


def _wide_symbols(observation: dict[str, object]) -> set[str]:
    symbols: set[str] = set()
    for item in observation.get("wide_symbols", []):
        if isinstance(item, dict):
            symbol = str(item.get("symbol") or "").strip()
            if symbol:
                symbols.add(symbol)
    return symbols


def _rank_symbols(
    observed: Sequence[str],
    body_by_symbol: dict[str, list[str]],
    signature_by_symbol: dict[str, list[str]],
    wide_symbols: set[str],
) -> list[str]:
    symbols = _dedupe([*body_by_symbol.keys(), *observed, *signature_by_symbol.keys(), *wide_symbols])
    return sorted(symbols, key=lambda symbol: _symbol_priority(symbol, body_by_symbol, signature_by_symbol, wide_symbols))


def _symbol_priority(
    symbol: str,
    body_by_symbol: dict[str, list[str]],
    signature_by_symbol: dict[str, list[str]],
    wide_symbols: set[str],
) -> tuple[int, str]:
    if symbol in body_by_symbol:
        return (0, symbol)
    if symbol in wide_symbols and symbol in signature_by_symbol:
        return (1, symbol)
    if "." in symbol:
        return (2, symbol)
    if symbol in signature_by_symbol:
        return (3, symbol)
    return (4, symbol)


def _outgoing_by_path(edges: Sequence[SourceEdge]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for edge in edges:
        grouped.setdefault(edge.source, []).append(f"{edge.kind}->{edge.target}")
    return grouped


def _incoming_by_path(edges: Sequence[SourceEdge]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for edge in edges:
        target = edge.target
        if target.endswith((".py", ".js", ".ts", ".go", ".rs", ".java")):
            grouped.setdefault(target, []).append(f"{edge.kind}<-{edge.source}")
    return grouped


def _role_hint(symbol: str, *, path: str, outgoing_edges: Sequence[str]) -> str:
    lowered = f"{path} {symbol}".lower()
    edge_text = " ".join(outgoing_edges).lower()
    if any(term in lowered for term in ("route", "router", "classify", "intent")):
        return "routing and intent decision responsibility"
    if any(term in lowered for term in ("execute", "executor", "run_", ".run", "dispatch", "handler")):
        return "execution or dispatch responsibility"
    if any(term in lowered for term in ("validate", "validation", "check", "completion")):
        return "validation or completion responsibility"
    if any(term in lowered for term in ("render", "format", "report", "answer")):
        return "answer rendering or reporting responsibility"
    if any(term in lowered for term in ("load", "save", "store", "session", "memory", "persist")):
        return "state persistence or memory responsibility"
    if edge_text:
        return "coordination responsibility across observed internal edges"
    return "observed source responsibility"


def _node_limitations(symbol: str, *, body_anchors: Sequence[str], wide_symbols: set[str]) -> list[str]:
    limitations: list[str] = []
    if not body_anchors:
        limitations.append("body sample not observed")
    if symbol in wide_symbols:
        limitations.append("wide symbol was sampled partially")
    return limitations


def _confidence(*, body_anchors: Sequence[str], signature_anchors: Sequence[str], edges: Sequence[str]) -> float:
    score = 0.45
    if signature_anchors:
        score += 0.15
    if body_anchors:
        score += 0.25
    if edges:
        score += 0.10
    return min(score, 0.95)


def _entrypoint_nodes(nodes: Sequence[SourceResponsibilityNode]) -> list[str]:
    entries: list[str] = []
    for node in nodes:
        lowered = node.symbol.lower()
        if lowered in {"main", "__main__"} or lowered.endswith(".main") or "cli" in lowered:
            entries.append(f"{node.path}:{node.symbol}")
    return entries


def _flow_lines(edges: Sequence[SourceEdge], nodes: Sequence[SourceResponsibilityNode]) -> list[str]:
    if edges:
        return [f"`{edge.source}` -> `{edge.target}` ({edge.kind})" for edge in edges[:10]]
    return [f"`{node.path}`의 `{node.symbol}`가 {node.role_hint}를 담당합니다." for node in nodes[:6]]


def _graph_limitations(nodes: Sequence[SourceResponsibilityNode], representatives: Sequence[RepresentativeFile]) -> list[str]:
    limitations: list[str] = []
    if not any(node.body_anchors for node in nodes) and representatives:
        limitations.append("No body-sample anchors were observed; body-level behavior must remain limited.")
    if not any(node.outgoing_edges for node in nodes) and representatives:
        limitations.append("No repo-internal outgoing edges were observed for responsibility flow.")
    for node in nodes:
        for limitation in node.limitations:
            label = f"{node.path}:{node.symbol} - {limitation}"
            if label not in limitations:
                limitations.append(label)
    return limitations


def _nodes_from_representative_files(
    files: Sequence[RepresentativeFile],
    *,
    outgoing_by_path: dict[str, list[str]],
) -> list[SourceResponsibilityNode]:
    nodes: list[SourceResponsibilityNode] = []
    for file in files[:8]:
        symbols = file.symbols or [Path(file.path).stem]
        for symbol in symbols[:MAX_NODE_ANCHORS]:
            body_anchors = [f"`{file.path}:{label}`" for label in file.ranges if "body_sample" in label]
            signature_anchors = [f"`{file.path}:{label}`" for label in file.ranges if "body_sample" not in label]
            nodes.append(
                SourceResponsibilityNode(
                    path=file.path,
                    symbol=symbol,
                    role_hint=_role_hint(symbol, path=file.path, outgoing_edges=outgoing_by_path.get(file.path, [])),
                    body_anchors=body_anchors[:MAX_NODE_ANCHORS],
                    signature_anchors=signature_anchors[:MAX_NODE_ANCHORS],
                    outgoing_edges=outgoing_by_path.get(file.path, [])[:MAX_NODE_EDGES],
                    limitations=_node_limitations(symbol, body_anchors=body_anchors, wide_symbols=set())[:MAX_NODE_ANCHORS],
                    confidence=_confidence(body_anchors=body_anchors, signature_anchors=signature_anchors, edges=outgoing_by_path.get(file.path, [])),
                )
            )
    return nodes


def _node_details(node: SourceResponsibilityNode, *, language: str) -> str:
    anchors = node.body_anchors or node.signature_anchors
    parts: list[str] = []
    if anchors:
        label = "body anchors" if node.body_anchors else "anchors"
        parts.append(label + " " + ", ".join(anchors[:2]))
    if node.outgoing_edges:
        parts.append("outgoing " + ", ".join(node.outgoing_edges[:2]))
    if node.incoming_edges:
        parts.append("incoming " + ", ".join(node.incoming_edges[:2]))
    if node.limitations:
        prefix = "limits " if language == "en" else "한계 "
        parts.append(prefix + ", ".join(node.limitations[:2]))
    parts.append(f"confidence={node.confidence:.2f}")
    return "; ".join(parts)


def _clean_path(path: str) -> str:
    value = path.strip().strip("`").replace("\\", "/")
    if not value:
        return ""
    parts = Path(value).parts
    for anchor in ("src", "tests", "test"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor) :])
    return value.strip("/")


def _positive_int(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen
