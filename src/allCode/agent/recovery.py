"""Recovery helpers for empty responses and repeated tool calls."""

from __future__ import annotations

import hashlib
import json
from collections import deque

from allCode.core.models import ToolCall, ToolResult
from allCode.core.result import CompletionEvidence, RecoveryState, ToolLoopSignature


class ToolLoopGuard:
    """Detects repeated identical tool calls without blocking new evidence paths."""

    def __init__(self, *, window_size: int = 10, repeat_limit: int = 3, recent_span: int = 6) -> None:
        self._window: deque[str] = deque(maxlen=window_size)
        self._counts: dict[str, int] = {}
        self._observation_window: deque[str] = deque(maxlen=window_size)
        self._observation_counts: dict[str, int] = {}
        self.signatures_by_key: dict[str, ToolLoopSignature] = {}
        self._repeat_limit = repeat_limit
        self._recent_span = recent_span

    def record(self, tool_call: ToolCall) -> tuple[ToolLoopSignature, bool]:
        key = self._hash(tool_call)
        self._window.append(key)
        self._counts[key] = self._counts.get(key, 0) + 1
        recent = list(self._window)[-self._recent_span :]
        repeat_limit = 2 if tool_call.name == "read_file" else self._repeat_limit
        detected = recent.count(key) >= repeat_limit
        signature = ToolLoopSignature.from_tool_call(tool_call, count=self._counts[key])
        self.signatures_by_key[key] = signature
        return signature, detected

    def record_and_check(self, tool_call: ToolCall) -> bool:
        return self.record(tool_call)[1]

    def record_observation(self, tool_call: ToolCall, result: ToolResult) -> tuple[int, bool, str]:
        """Detect repeated action-observation patterns after execution."""

        key = self._observation_hash(tool_call, result)
        self._observation_window.append(key)
        self._observation_counts[key] = self._observation_counts.get(key, 0) + 1
        recent = list(self._observation_window)[-self._recent_span :]
        count = self._observation_counts[key]
        limit = self._repeat_limit if tool_call.name == "run_tests" else (2 if not result.ok else self._repeat_limit)
        detected = recent.count(key) >= limit
        reason = "same_action_error" if not result.ok else "same_action_observation"
        return count, detected, reason

    @staticmethod
    def _hash(tool_call: ToolCall) -> str:
        payload = {
            "name": tool_call.name,
            "arguments": ToolLoopGuard._canonical_arguments(tool_call),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _observation_hash(tool_call: ToolCall, result: ToolResult) -> str:
        observation = result.metadata.get("observation")
        summary = ""
        if isinstance(observation, dict):
            summary = str(observation.get("summary") or observation.get("target") or "")
        payload = {
            "tool": tool_call.name,
            "arguments": ToolLoopGuard._canonical_arguments(tool_call),
            "ok": result.ok,
            "error_type": result.error_type,
            "summary": summary[:240],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _canonical_arguments(tool_call: ToolCall) -> dict:
        args = tool_call.arguments
        if tool_call.name in {"read_file", "patch_file", "write_file"}:
            keys = ("file_path", "start_line", "end_line")
        elif tool_call.name == "delete_path":
            keys = ("path",)
        elif tool_call.name in {"search_files", "web_search"}:
            keys = ("query", "pattern", "glob")
        elif tool_call.name in {"run_command", "run_tests"}:
            keys = ("command", "cwd")
        elif tool_call.name == "list_directory":
            keys = ("path",)
        else:
            keys = tuple(sorted(args))
        return {key: args.get(key) for key in keys if key in args}


class RecoveryTracker:
    def __init__(self) -> None:
        self.empty_response_retried = False
        self.final_answer_requested = False
        self.mutation_action_requests = 0
        self.validation_action_requested = False
        self.stream_timeout_retried = False
        self.validation_repair_requests = 0
        self.states: list[RecoveryState] = []

    def add_state(
        self,
        reason,
        *,
        attempts: int = 0,
        last_error: str | None = None,
        blocked: bool = False,
    ) -> None:
        self.states.append(
            RecoveryState(
                reason=reason,
                attempts=attempts,
                last_error=last_error,
                blocked=blocked,
            )
        )

    def can_retry_empty_response(self) -> bool:
        if self.empty_response_retried:
            return False
        self.empty_response_retried = True
        return True

    def can_retry_stream_timeout(self) -> bool:
        if self.stream_timeout_retried:
            return False
        self.stream_timeout_retried = True
        return True

    def can_request_final_answer(self) -> bool:
        if self.final_answer_requested:
            return False
        self.final_answer_requested = True
        return True

    def can_request_mutation_action(self, *, max_attempts: int = 4) -> bool:
        if self.mutation_action_requests >= max_attempts:
            return False
        self.mutation_action_requests += 1
        return True

    def can_request_validation_action(self) -> bool:
        if self.validation_action_requested:
            return False
        self.validation_action_requested = True
        return True

    def can_request_validation_repair(self, *, max_attempts: int = 2) -> bool:
        if self.validation_repair_requests >= max_attempts:
            return False
        self.validation_repair_requests += 1
        return True


def needs_validation_repair(routing, evidence: CompletionEvidence) -> bool:
    return bool(routing.requires_validation and evidence.has_file_change() and evidence.validation_passed is False)
