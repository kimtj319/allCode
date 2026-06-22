"""Deterministic preflight actions before the model/tool loop."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from allCode.agent.intent import IntentExtractor
from allCode.agent.router import RoutingDecision
from allCode.core.models import CoreModel, ToolCall, ToolResult
from allCode.core.path_patterns import extract_prompt_path, is_followup_reference
from allCode.core.result import CompletionEvidence


class PreflightPlan(CoreModel):
    """Safe actions or clarification needed before model routing continues."""

    tool_calls: list[ToolCall] = Field(default_factory=list)
    clarification_answer: str | None = None


class PreflightPlanner:
    """Adds grounded first actions without replacing model-owned routing."""

    CONDITIONAL_DELETE_PATTERN = re.compile(
        r"(?:delete|remove|삭제|제거).{0,32}(?:if\s+(?:it\s+)?(?:exists|is\s+there)|있으면|존재하면|있는\s*경우)",
        re.IGNORECASE,
    )

    def __init__(self, extractor: IntentExtractor | None = None) -> None:
        self._extractor = extractor or IntentExtractor()

    def plan(self, *, prompt: str, routing: RoutingDecision) -> PreflightPlan:
        explicit_target = extract_prompt_path(prompt)
        target = routing.target_hint or explicit_target
        signals = self._extractor.extract(prompt)
        if self._needs_target_clarification(prompt=prompt, routing=routing, target=target):
            return PreflightPlan(
                clarification_answer=(
                    "어떤 파일을 수정해야 하는지 확인이 필요합니다. "
                    "파일명이나 경로를 명확히 지정해 주시면 그 대상을 먼저 읽고 변경하겠습니다."
                )
            )
        if explicit_target is None and not signals.followup_requested and routing.kind == "inspect" and "search_workspace" in routing.tool_capabilities:
            # Broad architecture/structure analysis must start from the actual
            # source tree, not a keyword search: a "def " search matches code
            # fences inside design docs (plan/*.md) and generated output trees and
            # steers the model to summarize docs instead of the real code. Seed a
            # code-prioritized source_overview so src/ packages are the first
            # evidence the model sees.
            if self._is_architecture_overview(prompt):
                return PreflightPlan(
                    tool_calls=[
                        ToolCall(
                            id=f"preflight-{uuid4().hex}",
                            name="source_overview",
                            arguments={"path": ".", "focus": "package_roles", "query": prompt[:400]},
                        )
                    ]
                )
            query = self._inspection_search_query(prompt)
            if query:
                return PreflightPlan(
                    tool_calls=[
                        ToolCall(
                            id=f"preflight-{uuid4().hex}",
                            name="search_files",
                            arguments={"query": query, "max_results": 20, "context_lines": 1},
                        )
                    ]
                )
        if (
            explicit_target is None
            and not signals.followup_requested
            and routing.kind == "modify"
            and not routing.read_only_requested
            and "search_workspace" in routing.tool_capabilities
        ):
            query = self._mutation_discovery_query(prompt)
            if query:
                return PreflightPlan(
                    tool_calls=[
                        ToolCall(
                            id=f"preflight-{uuid4().hex}",
                            name="search_files",
                            arguments={"query": query, "max_results": 20, "context_lines": 2},
                        )
                    ]
                )
        if target and routing.kind == "modify" and not routing.read_only_requested and self._conditional_delete(prompt):
            return PreflightPlan(
                tool_calls=[
                    ToolCall(
                        id=f"preflight-{uuid4().hex}",
                        name="delete_path",
                        arguments={"path": target, "missing_ok": True},
                    )
                ]
            )
        if target and self._should_read_target_first(routing) and self._looks_file_target(target) and not self._is_targeted_lookup(prompt):
            return PreflightPlan(
                tool_calls=[
                    ToolCall(
                        id=f"preflight-{uuid4().hex}",
                        name="read_file",
                        arguments={"file_path": target, "max_bytes": 12_000},
                    )
                ]
            )
        return PreflightPlan()

    def _needs_target_clarification(
        self,
        *,
        prompt: str,
        routing: RoutingDecision,
        target: str | None,
    ) -> bool:
        if target:
            return False
        if routing.read_only_requested:
            return False
        if routing.kind == "modify" and routing.requires_mutation:
            return is_followup_reference(prompt)
        return False

    def _conditional_delete(self, prompt: str) -> bool:
        return bool(self.CONDITIONAL_DELETE_PATTERN.search(prompt))

    def _should_read_target_first(self, routing: RoutingDecision) -> bool:
        if routing.requires_external_knowledge:
            return False
        return (
            routing.route_source == "model"
            and routing.kind in {"inspect", "modify", "operate"}
            and "read_file" in routing.tool_capabilities
        )

    @staticmethod
    def _looks_file_target(target: str) -> bool:
        name = Path(target).name
        if "." in name:
            return True
        return name in {"Makefile", "Dockerfile", "Procfile", "Gemfile", "Rakefile"}

    def _is_targeted_lookup(self, prompt: str) -> bool:
        normalized = " ".join(prompt.lower().split())
        markers = (
            "전체를 요약하지 말고",
            "값만",
            "줄만",
            "찾아서",
            "찾아줘",
            "find only",
            "only find",
            "only line",
            "line only",
            "do not summarize",
            "don't summarize",
        )
        if any(marker in normalized for marker in markers):
            return True
        return bool(re.search(r"\b[A-Z][A-Z0-9_]{3,}\b", prompt))

    def _is_architecture_overview(self, prompt: str) -> bool:
        """Broad "understand the project/architecture" requests (no explicit
        target) that should begin from a code-prioritized source overview."""

        normalized = " ".join(prompt.lower().split())
        markers = (
            "architecture", "아키텍처", "구조", "전체 흐름", "전반", "overall", "overview",
            "module", "modules", "모듈", "responsibility", "responsibilities", "책임",
            "layer", "layered", "계층", "codebase", "코드베이스", "프로젝트 목적", "project purpose",
            "도메인 로직", "domain logic", "핵심 코드", "important code", "핵심 도메인",
        )
        return any(marker in normalized for marker in markers)

    def _inspection_search_query(self, prompt: str) -> str | None:
        normalized = " ".join(prompt.lower().split())
        markers = (
            "module",
            "modules",
            "responsibility",
            "responsibilities",
            "directory structure",
            "file layout",
            "file list",
            "모듈",
            "책임",
            "디렉터리 구조",
            "디렉토리 구조",
            "파일 구조",
            "파일 목록",
            "파일 근거",
        )
        if not any(marker in normalized for marker in markers):
            return None
        return "def "

    def _mutation_discovery_query(self, prompt: str) -> str | None:
        lowered = prompt.lower()
        localized = (
            ("설정", "config"),
            ("환경", "config"),
            ("서비스", "service"),
            ("테스트", "test"),
            ("문자열", "text"),
        )
        for marker, query in localized:
            if marker in prompt:
                return query
        ignored = {
            "add",
            "create",
            "update",
            "modify",
            "write",
            "test",
            "tests",
            "function",
            "validate",
        }
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", lowered):
            pieces = [piece for piece in token.split("_") if len(piece) >= 3]
            if pieces:
                for piece in reversed(pieces):
                    if piece not in ignored:
                        return piece
            if token not in ignored:
                return token
        return None


def missing_read_search_fallback(
    tool_calls: Sequence[ToolCall],
    results: Sequence[ToolResult],
    routing: RoutingDecision,
) -> list[ToolCall]:
    if "search_workspace" not in routing.tool_capabilities:
        return []
    fallback: list[ToolCall] = []
    calls_by_id = {call.id: call for call in tool_calls}
    for result in results:
        if result.name != "read_file" or result.error_type != "not_found":
            continue
        original = calls_by_id.get(result.call_id)
        target = str(original.arguments.get("file_path", "")) if original is not None else ""
        query = Path(target).name or target
        if query:
            fallback.append(
                ToolCall(
                    id=f"{result.call_id}-search",
                    name="search_files",
                    arguments={"query": query, "max_results": 20},
                )
            )
    return fallback


def should_force_mutation_after_inspection(
    results: Sequence[ToolResult],
    routing: RoutingDecision,
    evidence: CompletionEvidence,
) -> bool:
    if routing.read_only_requested:
        return False
    if not routing.requires_mutation or evidence.has_resolution_evidence():
        return False
    return any(result.name == "read_file" and result.ok for result in results)


def followup_target_hint(prompt: str, recent_targets: Sequence[str]) -> str | None:
    if not recent_targets or not is_followup_reference(prompt):
        return None
    lowered = prompt.lower()
    if any(marker in lowered for marker in ("test", "테스트")):
        for target in recent_targets:
            if "test" in Path(target).name.lower() or "/test" in target.lower():
                return target
    if any(marker in lowered for marker in ("cli", "command", "option", "명령", "옵션", "--")):
        for target in recent_targets:
            name = Path(target).name.lower()
            if name in {"main.py", "cli.py", "__main__.py"}:
                return target
        for target in recent_targets:
            lowered_target = target.lower()
            if "/src/" in lowered_target and "/test" not in lowered_target:
                return target
    for target in recent_targets:
        if "/test" not in target.lower():
            return target
    return recent_targets[0]
