"""Prompt construction for the initial fake-loop implementation."""

from __future__ import annotations

from collections.abc import Sequence
from allCode.agent.context import ContextBundle
from allCode.agent.router import RoutingDecision
from allCode.core.models import Message, ToolResult, TurnInput
from allCode.core.result import RepairTarget
from allCode.memory.project_obligations import feature_objectives_from_prompt

SYSTEM_PROMPT = (
    "You are allCode, a lightweight all-rounder coding agent. "
    "Use tools when needed, keep actions observable, and provide a grounded final answer."
)

class PromptBuilder:
    def initial_messages(
        self,
        turn_input: TurnInput,
        routing: RoutingDecision | None = None,
        context_bundle: ContextBundle | None = None,
    ) -> list[Message]:
        content = SYSTEM_PROMPT
        if routing is not None:
            content = f"{content}\n\n{self._routing_instruction(routing)}"
        objectives = feature_objectives_from_prompt(turn_input.user_prompt)
        if objectives:
            content = f"{content}\n\n{self._feature_objective_instruction(objectives)}"
        messages = [Message(role="system", content=content)]
        if context_bundle is not None and context_bundle.sections:
            messages.append(Message(role="system", content=self._context_instruction(context_bundle)))
        messages.append(Message(role="user", content=turn_input.user_prompt))
        return messages
    def append_tool_results(
        self,
        messages: Sequence[Message],
        results: Sequence[ToolResult],
    ) -> list[Message]:
        updated = list(messages)
        for result in results:
            content = result.content or (result.error if not result.ok else "") or "Tool execution failed."
            content = self._content_with_evidence_bundle(content, result)
            updated.append(
                Message(
                    role="tool",
                    content=content,
                    tool_call_id=result.call_id,
                    metadata={
                        "tool_name": result.name,
                        "ok": result.ok,
                        "error_type": result.error_type,
                    },
                )
            )
        return updated
    def final_answer_request(self, messages: Sequence[Message]) -> list[Message]:
        return [
            *messages,
            Message(
                role="user",
                content=(
                    "Provide the final answer only, grounded in the observed tool results. "
                    "If the task cannot be completed, explicitly say what was checked, why it is blocked, "
                    "and what safe next step is available."
                ),
            ),
        ]

    def empty_response_retry(self, messages: Sequence[Message]) -> list[Message]:
        return [
            *messages,
            Message(
                role="user",
                content="Your previous response was empty. Answer concisely or call a relevant tool.",
            ),
        ]

    def validation_repair_request(
        self,
        messages: Sequence[Message],
        *,
        repair_targets: Sequence[RepairTarget] = (),
        patch_ambiguous_files: Sequence[str] = (),
        preferred_next_tools: Sequence[str] = (),
        failure_symbols: Sequence[str] = (),
        api_expectations: Sequence[str] = (),
        failure_excerpt: str = "",
        phase_block_reason: str = "",
    ) -> list[Message]:
        target_lines = self._format_repair_targets(repair_targets)
        ambiguous = [path for path in patch_ambiguous_files if path][:3]
        symbols = [symbol for symbol in failure_symbols if symbol][:3]
        expectations = [expectation for expectation in api_expectations if expectation][:5]
        preferred = [tool for tool in preferred_next_tools if tool][:3]
        details: list[str] = []
        if target_lines:
            details.append("Detected repair targets:\n" + "\n".join(target_lines))
        if symbols:
            details.append("Failure symbols: " + ", ".join(symbols))
        if expectations:
            details.append("Public API expectations from validation: " + "; ".join(expectations))
        if ambiguous:
            details.append("Patch ambiguity files: " + ", ".join(ambiguous))
        if preferred:
            details.append("Preferred next tools: " + ", ".join(preferred))
        if failure_excerpt:
            details.append("Failure excerpt:\n" + failure_excerpt[:900])
        if phase_block_reason:
            details.append(f"Blocked phase feedback: {phase_block_reason}")
        detail_text = "\n".join(details)
        return [
            *messages,
            Message(
                role="user",
                content=self._join_prompt_parts(
                    "Validation is failing or missing for this change. "
                    "Use the latest validation failure metadata as the repair source. "
                    "Inspect the failing file and line range when a repair target is present, then repair the concrete issue. "
                    "If patching was ambiguous, do not repeat the same patch; read the relevant range first and then use write_file when the current file context is available. "
                    "If the failure is a ModuleNotFoundError or missing import, create the missing source module instead of repeatedly validating. "
                    "If the failure is a TypeError about missing or unexpected constructor/function arguments, preserve backward-compatible public APIs already exercised by existing tests unless the user explicitly requested a breaking change. "
                    "If public API expectations are listed, satisfy them in the source code rather than weakening tests. "
                    "After a successful mutation, rerun run_tests. Do not provide a final answer until validation passes. "
                    "Use exactly one allowed native tool call and provide arguments matching that tool schema.",
                    detail_text,
                ),
            ),
        ]

    def test_authoring_request(
        self,
        messages: Sequence[Message],
        *,
        missing_artifacts: Sequence[str] = (),
        recent_source_paths: Sequence[str] = (),
        feature_objectives: Sequence[str] = (),
        phase_block_reason: str = "",
    ) -> list[Message]:
        missing = ", ".join(artifact for artifact in missing_artifacts if artifact) or "test"
        sources = [path for path in recent_source_paths if path][:5]
        details = [f"Missing artifact obligation: {missing}"]
        explicit_targets = [
            artifact.split(":", 1)[1]
            for artifact in missing_artifacts
            if ":" in artifact and artifact.split(":", 1)[1]
        ][:5]
        if explicit_targets:
            details.append("Exact missing target paths: " + ", ".join(explicit_targets))
        if sources:
            details.append("Recent source files to cover: " + ", ".join(sources))
        objectives = [objective for objective in feature_objectives if objective][:8]
        if objectives:
            details.append("Active feature objectives to cover: " + ", ".join(objectives))
        if phase_block_reason:
            details.append(f"Blocked phase feedback: {phase_block_reason}")
        return [
            *messages,
            Message(
                role="user",
                content=self._join_prompt_parts(
                    "A requested source, document, or test artifact is still missing. "
                    "Create or update the missing artifact now with write_file or patch_file. "
                    "If a missing artifact includes a target path and only write_file is allowed, "
                    "your next response must be one write_file tool call with file_path set to that exact path "
                    "and content containing the complete requested artifact. "
                    "If source and test artifacts are both missing, create the source file first. "
                    "If active feature objectives are listed, implement visible source behavior/API for them "
                    "and write tests that exercise those objectives instead of adding unrelated coverage only. "
                    "For non-English domain objectives in code, choose conventional code-facing English identifiers "
                    "when the language ecosystem normally uses English APIs, while preserving user-facing wording where useful. "
                    "Do not inspect configuration files or directory listings when only mutation tools are exposed. "
                    "Do not call list_directory, search_files, read_file, run_tests, or any hidden tool in this phase. "
                    "Do not call run_tests and do not provide a final answer until the missing artifact has changed. "
                    "Use exactly one allowed native tool call and provide arguments matching that tool schema.",
                    "\n".join(details),
                ),
            ),
        ]

    def mutation_action_request(self, messages: Sequence[Message]) -> list[Message]:
        return [
            *messages,
            Message(
                role="user",
                content=(
                    "This is a file modification request. Inspect observations already available, then call "
                    "patch_file or write_file with the concrete file change. Do not provide a final answer and "
                    "do not emit reasoning-only content until a file mutation tool has run. "
                    "If no exact target was named, choose the most relevant source file from the latest search_files, "
                    "read_file, or list_directory observations instead of repeatedly listing directories. "
                    "If the current phase only exposes mutation tools, do not call list_directory, search_files, "
                    "read_file, shell, or web tools; use the observations already present and call patch_file or write_file. "
                    "If tests were requested, create or update a relevant test file before validation."
                ),
            ),
        ]

    def validation_action_request(self, messages: Sequence[Message]) -> list[Message]:
        return [
            *messages,
            Message(
                role="user",
                content=(
                    "A file change has already been made and validation is now required. "
                    "Call run_tests with the appropriate validation command now. "
                    "Do not call mutation tools again unless validation fails."
                ),
            ),
        ]

    def native_tool_call_retry(self, messages: Sequence[Message], *, parser_error: str | None = None) -> list[Message]:
        detail = f" Parser note: {parser_error}" if parser_error else ""
        return [
            *messages,
            Message(
                role="user",
                content=(
                    "Use the registered native tool-calling protocol for the next action. "
                    "Do not print JSON, action blocks, or pseudo tool-call text in the answer."
                    f"{detail}"
                ),
            ),
        ]

    def natural_language_retry(self, messages: Sequence[Message]) -> list[Message]:
        return [
            *messages,
            Message(
                role="user",
                content=(
                    "Your previous response was a JSON object or tool-style payload. "
                    "Provide a concise natural-language answer only."
                ),
            ),
        ]

    def summarize_blocked_turn(
        self,
        messages: Sequence[Message],
        *,
        reason: str,
        last_tool_results: Sequence[ToolResult] = (),
    ) -> str:
        lines = [
            "요청을 완료하지 못했습니다.",
            f"- 차단 사유: {reason}",
        ]
        tool_results = list(last_tool_results) or self._tool_results_from_messages(messages)
        reason_detail = self._blocked_reason_detail(reason, tool_results)
        if reason_detail:
            lines.append(f"- 세부 내용: {reason_detail}")
        if tool_results:
            lines.append("- 확인한 근거:")
            for result in tool_results[-3:]:
                status = "성공" if result.ok else "실패"
                detail = (result.content if result.ok else result.error or "").strip()
                if len(detail) > 500:
                    detail = detail[:500].rstrip() + "..."
                if not detail:
                    detail = result.error_type or "no output"
                lines.append(f"  - {result.name}: {status} - {detail}")
        lines.append(f"- 다음 단계: {self._blocked_next_step(reason, tool_results)}")
        return "\n".join(lines)

    @staticmethod
    def _feature_objective_instruction(objectives: Sequence[str]) -> str:
        compact = ", ".join(list(dict.fromkeys(objective for objective in objectives if objective))[:8])
        return (
            "Active feature objectives for this turn: "
            f"{compact}.\n"
            "Treat these as implementation and validation obligations, not as final-answer keywords. "
            "When modifying code, implement visible behavior/API and tests for the objectives. "
            "For non-English domain objectives, use conventional code-facing English identifiers when appropriate "
            "for the target language, and keep the original user-facing meaning intact."
        )

    def _routing_instruction(self, routing: RoutingDecision) -> str:
        lines = [
            f"Routing decision: {routing.kind} (confidence {routing.confidence:.2f}).",
            f"Reason: {routing.reason}",
            f"Allowed tool capabilities: {', '.join(sorted(routing.tool_capabilities)) or 'none'}.",
            f"Workflow hint: {routing.workflow_hint}.",
        ]
        if routing.target_hint:
            lines.append(f"Target hint: {routing.target_hint}.")
        if routing.read_only_requested:
            lines.append("Read-only constraint: do not call mutation or shell tools.")
        if routing.kind == "answer" and not routing.requires_external_knowledge and not routing.allows_tool_use:
            lines.extend(
                [
                    "This route is direct-answer only.",
                    "Do not call tools for this turn; answer from the prompt and supplied context.",
                ]
            )
            if "refused" in routing.reason.lower() or "disallowed" in routing.reason.lower():
                lines.append(
                    "For safety refusals, explicitly mention that the request is 위험 and cannot proceed without proper 승인."
                )
        if routing.kind == "inspect":
            lines.extend(
                [
                    "For file-grounded inspection, use search_files or read_file before answering when the user names a file, asks to actually read/verify evidence, or requests a source filename.",
                    "Do not answer from workspace context alone when the prompt asks for file evidence; create an observable tool result first.",
                    "If the user asks for directory structure, file layout, module inventory, or file list, verify with list_directory or search_files before answering.",
                    "For symbols, classes, functions, or project-name evidence, prefer search_files to locate candidates, then read_file the selected file once.",
                    "Avoid repeated read_file calls for the same target; reuse the latest observation unless a new line range is needed.",
                ]
            )
        if routing.requires_mutation:
            lines.extend(
                [
                    "For modification work, inspect the target first with list_directory, search_files, or read_file.",
                    "If the prompt does not name an exact file, discover candidate files from workspace context and tools before editing.",
                    "If the prompt names an existing file or path, edit that file in the current workspace; do not scaffold a new project.",
                    "If a Target hint is present and has already been read, prefer patch_file or write_file for that exact target instead of listing directories again.",
                    "If the prompt requests a named new file, call write_file for that exact path instead of only describing the intended content.",
                    "If the prompt requests conditional deletion, call delete_path for the exact target once after resolving the path; if it is missing, report the tool's not_found observation without inventing a deletion.",
                    "Do not ask the user for the repository tree when file/search tools are available.",
                    "Make concrete file changes through write_file or patch_file, then run an available validation command.",
                    "When the user asks to add or update tests, modify test files before validation; pre-existing passing tests alone are not enough.",
                    "When only mutation tools are available, do not call list_directory, search_files, or read_file; use the observations already present.",
                    "Ground the final answer in CompletionEvidence; never claim completion without changed files and validation evidence when validation is required.",
                ]
            )
        if routing.requires_validation:
            lines.extend(
                [
                    "Validation is required before reporting success.",
                    "Use run_tests for pytest, unittest, npm test, cargo test, gradle test, or mvn test commands; do not use run_command for validation commands.",
                ]
            )
        if routing.requires_external_knowledge:
            lines.extend(
                [
                    "Only use web_search or web_fetch for external evidence; do not call file, shell, mutation, or validation tools.",
                    "Use the registered native web_search or web_fetch tool only to collect external evidence.",
                    "If web_search reports web_search_unavailable or backend disabled, state that the web backend is not configured and cite the setting to configure.",
                    "When explaining unavailable web evidence in Korean, include the term 검색 so the user can recognize the web-search failure.",
                    "Never print tool-call plans, action JSON, or raw search results as the final answer.",
                    "After web evidence is observed, write a natural-language answer grounded in that evidence.",
                ]
            )
        return "\n".join(lines)

    def _context_instruction(self, context_bundle: ContextBundle) -> str:
        rendered = context_bundle.render().strip()
        return "\n".join(
            [
                "Workspace context for this turn:",
                rendered,
                "",
                "Use this context to choose relevant files and preserve follow-up continuity.",
                "For file modifications, verify current contents with tools before writing or patching.",
                "For large files, use search_files first and then read_file with start_line/end_line or max_bytes instead of dumping whole files.",
            ]
        )

    def _content_with_evidence_bundle(self, content: str, result: ToolResult) -> str:
        bundle = result.metadata.get("evidence_bundle")
        if not isinstance(bundle, list) or not bundle:
            return content
        lines = [content, "Evidence bundle:"]
        for item in bundle[:10]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            lines.append(f"- title: {title}")
            if url:
                lines.append(f"  url: {url}")
            if snippet:
                lines.append(f"  snippet: {snippet}")
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _format_repair_targets(repair_targets: Sequence[RepairTarget]) -> list[str]:
        lines: list[str] = []
        for target in repair_targets[:3]:
            path = target.file_path
            if not path:
                continue
            location = f"{path}:{target.line_number}" if target.line_number is not None else path
            if target.symbol:
                location = f"{location} ({target.symbol})"
            if target.reason:
                location = f"- {location} [{target.reason}]"
            else:
                location = f"- {location}"
            lines.append(location)
        return lines

    @staticmethod
    def _join_prompt_parts(instruction: str, details: str = "") -> str:
        detail = details.strip()
        if not detail:
            return instruction
        return f"{instruction}\n\n{detail}"

    def _tool_results_from_messages(self, messages: Sequence[Message]) -> list[ToolResult]:
        results: list[ToolResult] = []
        for message in messages:
            if message.role != "tool":
                continue
            results.append(
                ToolResult(
                    call_id=message.tool_call_id or "unknown",
                    name=str(message.metadata.get("tool_name") or "tool"),
                    ok=bool(message.metadata.get("ok")),
                    content=message.content,
                    error=None if message.metadata.get("ok") else message.content,
                    error_type=str(message.metadata.get("error_type") or "") or None,
                )
            )
        return results

    def _blocked_reason_detail(self, reason: str, tool_results: Sequence[ToolResult]) -> str | None:
        if reason == "target_clarification_required" or "clarification" in reason:
            return "수정 대상이 되는 어떤 파일인지 확정되지 않았습니다."
        if any(result.error_type == "not_found" for result in tool_results):
            return "요청한 파일이나 경로를 찾지 못했습니다."
        if any(result.error_type in {"approval_required", "policy_denied"} for result in tool_results):
            return "위험하거나 권한이 필요한 작업이라 승인 없이 실행하지 않았습니다."
        if any(result.error_type in {"tool_loop_detected", "no_progress_detected"} for result in tool_results):
            return "같은 도구 호출이 반복되어 더 진행해도 새 근거가 나오지 않는 상태입니다."
        if any(result.error_type in {"patch_ambiguous", "patch_not_found", "patch_invalid_request", "patch_strategy_required"} for result in tool_results):
            return "patch_file 검색 블록이 현재 파일 내용과 정확히 일치하지 않아 수리 전에 파일을 다시 확인해야 합니다."
        return None

    def _blocked_next_step(self, reason: str, tool_results: Sequence[ToolResult]) -> str:
        if reason == "target_clarification_required" or "clarification" in reason:
            return "어떤 파일을 수정할지 파일명이나 경로를 지정해 주세요."
        if any(result.error_type == "not_found" for result in tool_results):
            return "찾지 못한 경로를 확인하거나 올바른 파일명을 지정해 주세요."
        if any(result.error_type in {"approval_required", "policy_denied"} for result in tool_results):
            return "승인이 필요한 작업이면 approval mode를 조정하거나 더 안전한 명령으로 다시 요청해 주세요."
        if any(result.error_type in {"tool_loop_detected", "no_progress_detected"} for result in tool_results):
            return "이미 확인한 결과와 다른 파일, 검색어, 또는 검증 조건을 지정해 주세요."
        if any(result.error_type == "patch_ambiguous" for result in tool_results):
            return "해당 파일의 관련 범위를 다시 읽은 뒤 더 구체적인 patch_file 또는 write_file로 수리해야 합니다."
        if any(result.error_type == "patch_strategy_required" for result in tool_results):
            return "같은 patch를 반복하지 말고 관련 범위를 read_file로 다시 확인한 뒤 더 구체적인 patch_file 또는 write_file로 전환해야 합니다."
        if any(result.error_type in {"patch_not_found", "patch_invalid_request"} for result in tool_results):
            return "현재 파일 내용을 다시 읽은 뒤 실제 존재하는 텍스트를 기준으로 patch_file을 재시도해야 합니다."
        return "필요한 파일명, 승인, 또는 검색/검증 조건을 명확히 지정해 다시 요청해 주세요."
