"""Prompt construction for the initial fake-loop implementation."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.context import ContextBundle
from allCode.agent.router import RoutingDecision
from allCode.core.models import Message, ToolResult, TurnInput

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
            content = result.content if result.ok else result.error or "Tool execution failed."
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
                content="Provide the final answer only, grounded in the observed tool results.",
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

    def validation_repair_request(self, messages: Sequence[Message]) -> list[Message]:
        return [
            *messages,
            Message(
                role="user",
                content=(
                    "Validation is failing or missing for this change. "
                    "Inspect the failing file or test output, repair the concrete issue with write_file or patch_file, "
                    "and replace the full file with write_file if patching has produced duplicated or malformed code. "
                    "then rerun run_tests. Do not provide a final answer until validation passes."
                ),
            ),
        ]

    def _routing_instruction(self, routing: RoutingDecision) -> str:
        lines = [
            f"Routing decision: {routing.kind} (confidence {routing.confidence:.2f}).",
            f"Reason: {routing.reason}",
        ]
        if routing.read_only_requested:
            lines.append("Read-only constraint: do not call mutation or shell tools.")
        if routing.kind == "answer" and not routing.requires_external_knowledge:
            lines.extend(
                [
                    "This route is direct-answer only.",
                    "Do not call tools for this turn; answer from the prompt and supplied context.",
                ]
            )
        if routing.requires_mutation:
            lines.extend(
                [
                    "For modification work, inspect the target first with list_directory, search_files, or read_file.",
                    "If the prompt does not name an exact file, discover candidate files from workspace context and tools before editing.",
                    "Do not ask the user for the repository tree when file/search tools are available.",
                    "Make concrete file changes through write_file or patch_file, then run an available validation command.",
                    "When the user asks to add or update tests, modify test files before validation; pre-existing passing tests alone are not enough.",
                    "Ground the final answer in CompletionEvidence; never claim completion without changed files and validation evidence when validation is required.",
                ]
            )
        if routing.requires_validation:
            lines.append("Validation is required before reporting success.")
        if routing.requires_external_knowledge:
            lines.extend(
                [
                    "Only use web_search or web_fetch for external evidence; do not call file, shell, mutation, or validation tools.",
                    "Use the registered native web_search or web_fetch tool only to collect external evidence.",
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
