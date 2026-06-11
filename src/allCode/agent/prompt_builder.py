"""Prompt construction for the initial fake-loop implementation."""

from __future__ import annotations

from collections.abc import Sequence
from allCode.agent.context import ContextBundle
from allCode.agent.language import (
    ResponseLanguage,
    blocked_summary_labels,
    detect_response_language,
    final_answer_request_text,
    language_instruction,
    normalize_response_language,
    response_language_from_messages,
)
from allCode.agent.prompt_builder_helpers import (
    blocked_next_step,
    blocked_reason_detail,
    content_with_evidence_bundle,
    tool_results_from_messages,
)
from allCode.agent.prompt_sections import (
    context_instruction,
    feature_objective_instruction,
    format_repair_targets,
    join_prompt_parts,
    routing_instruction,
)
from allCode.agent.router import RoutingDecision
from allCode.agent.source_answer_synthesis import source_analysis_final_answer_instruction
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
        content = f"{content}\n\n{language_instruction(detect_response_language(turn_input.user_prompt))}"
        if routing is not None:
            content = f"{content}\n\n{routing_instruction(routing)}"
        objectives = (
            feature_objectives_from_prompt(turn_input.user_prompt)
            if routing is not None and routing.requires_mutation
            else []
        )
        if objectives:
            content = f"{content}\n\n{feature_objective_instruction(objectives)}"
        messages = [Message(role="system", content=content)]
        if context_bundle is not None and context_bundle.sections:
            messages.append(Message(role="system", content=context_instruction(context_bundle)))
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
            content = content_with_evidence_bundle(content, result)
            metadata = dict(result.metadata)
            metadata.update(
                {
                    "tool_name": result.name,
                    "ok": result.ok,
                    "error_type": result.error_type,
                }
            )
            updated.append(
                Message(
                    role="tool",
                    content=content,
                    tool_call_id=result.call_id,
                    metadata=metadata,
                )
            )
        return updated
    def final_answer_request(
        self,
        messages: Sequence[Message],
        *,
        response_language: ResponseLanguage | None = None,
    ) -> list[Message]:
        language = response_language or response_language_from_messages(messages)
        return [
            *messages,
            Message(
                role="user",
                content=final_answer_request_text(language),
            ),
        ]

    def source_analysis_final_answer_request(
        self,
        messages: Sequence[Message],
        *,
        response_language: ResponseLanguage | None = None,
    ) -> list[Message]:
        language = response_language or response_language_from_messages(messages)
        return [
            *messages,
            Message(
                role="user",
                content=source_analysis_final_answer_instruction(language),
            ),
        ]

    def inspect_stage_request(
        self,
        messages: Sequence[Message],
        *,
        stage: str,
        target_paths: Sequence[str] = (),
        reason: str = "",
    ) -> list[Message]:
        targets = [path for path in target_paths if path][:6]
        details: list[str] = []
        if targets:
            details.append("Target paths: " + ", ".join(targets))
        if reason:
            details.append("Stage reason: " + reason)
        if stage == "targeted_read":
            instruction = (
                "Before producing the final source analysis, inspect still-unread representative files from the latest overview. "
                "Prefer source_probe on the listed targets in priority order within the remaining budget; use read_file only when a precise line range or missing symbol detail is still needed. "
                "Avoid repeating files that were already probed or read. "
                "For each file, collect only bounded evidence: public classes/functions, import or runtime wiring, and entrypoint clues. "
                "Pay close attention to cross-module interactions, delegation sequence, and instantiation flow across packages. "
                "Keep this turn strictly read-only; do not create README, SUMMARY, report, or other document files. "
                "After representative evidence is observed, provide the analysis in the final answer, explaining the relationships and execution flow between components, and separate observed facts from inferred roles."
            )
        else:
            instruction = (
                "Continue the read-only source analysis with bounded evidence gathering. "
                "If target paths are listed, call source_overview on those paths before narrowing to files. "
                "Do not mutate files."
            )
        return [
            *messages,
            Message(role="user", content=join_prompt_parts(instruction, "\n".join(details))),
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
        target_lines = format_repair_targets(repair_targets)
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
                content=join_prompt_parts(
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
                content=join_prompt_parts(
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

    def related_test_discovery_request(
        self,
        messages: Sequence[Message],
        *,
        changed_source_paths: Sequence[str] = (),
        symbols: Sequence[str] = (),
        phase_block_reason: str = "",
    ) -> list[Message]:
        details: list[str] = []
        sources = [path for path in changed_source_paths if path][:6]
        if sources:
            details.append("Changed source files: " + ", ".join(sources))
        symbol_list = [symbol for symbol in symbols if symbol][:8]
        if symbol_list:
            details.append("Public symbols or API hints: " + ", ".join(symbol_list))
        if phase_block_reason:
            details.append(f"Blocked phase feedback: {phase_block_reason}")
        return [
            *messages,
            Message(
                role="user",
                content=join_prompt_parts(
                    "Before validation, discover tests related to the changed source. "
                    "Use exactly one read-only discovery tool call: search_files, source_overview, glob_files, or list_tree. "
                    "Prefer search_files for changed symbol names or file stems, and source_overview with focus=tests for broad test inventory. "
                    "Do not call run_tests yet, and do not mutate files in this phase.",
                    "\n".join(details),
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
        response_language: ResponseLanguage | None = None,
    ) -> str:
        language = normalize_response_language(response_language or response_language_from_messages(messages))
        labels = blocked_summary_labels(language)
        lines = [
            labels.title,
            f"- {labels.reason}: {reason}",
        ]
        tool_results = list(last_tool_results) or tool_results_from_messages(messages)
        reason_detail = blocked_reason_detail(reason, tool_results, response_language=language)
        if reason_detail:
            lines.append(f"- {labels.details}: {reason_detail}")
        if tool_results:
            lines.append(f"- {labels.evidence}:")
            for result in tool_results[-3:]:
                status = labels.success if result.ok else labels.failure
                detail = (result.content if result.ok else result.error or "").strip()
                if len(detail) > 500:
                    detail = detail[:500].rstrip() + "..."
                if not detail:
                    detail = result.error_type or "no output"
                lines.append(f"  - {result.name}: {status} - {detail}")
        lines.append(f"- {labels.next_step}: {blocked_next_step(reason, tool_results, response_language=language)}")
        return "\n".join(lines)
