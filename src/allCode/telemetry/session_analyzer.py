"""Session JSONL diagnostics for agent traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field

from allCode.core.models import CoreModel


class SessionDiagnostics(CoreModel):
    path: str
    logical_tool_actions: int = 0
    event_tool_records: int = 0
    model_requested_tools: int = 0
    executed_tools: int = 0
    reused_observations: int = 0
    suppressed_tools: int = 0
    policy_denied_tools: int = 0
    schema_denied_tools: int = 0
    repeated_targets: dict[str, int] = Field(default_factory=dict)
    schema_denied_count: int = 0
    suppressed_count: int = 0
    reused_observation_count: int = 0
    validation_failures: int = 0
    validation_failures_without_later_mutation: int = 0
    request_chars_by_round: list[int] = Field(default_factory=list)
    large_file_suppressed_count: int = 0
    source_overview_count: int = 0
    list_tree_count: int = 0
    glob_files_count: int = 0
    empty_search_denied_count: int = 0
    inspect_round_count: int = 0
    logical_read_action_count: int = 0
    repeated_inspect_target_count: int = 0
    paste_marker_stripped_count: int = 0
    tool_rows_suppressed_count: int = 0
    source_analysis_coverage_ratio: float | None = None
    representative_read_count: int = 0
    fallback_internal_reason_hidden: int = 0
    final_answer_language: str | None = None
    final_status: str | None = None

    def summary(self) -> str:
        lines = [
            "최근 세션 진단:",
            f"- logical_tool_actions: {self.logical_tool_actions}",
            f"- event_tool_records: {self.event_tool_records}",
            f"- model_requested_tools: {self.model_requested_tools}",
            f"- executed_tools: {self.executed_tools}",
            f"- reused_observations: {self.reused_observations}",
            f"- suppressed_tools: {self.suppressed_tools}",
            f"- policy_denied_tools: {self.policy_denied_tools}",
            f"- schema_denied_tools: {self.schema_denied_tools}",
            f"- schema_denied: {self.schema_denied_count}",
            f"- suppressed: {self.suppressed_count}",
            f"- reused_observations: {self.reused_observation_count}",
            f"- validation_failures: {self.validation_failures}",
            f"- validation_failures_without_later_mutation: {self.validation_failures_without_later_mutation}",
            f"- request_chars_by_round: {self.request_chars_by_round}",
            f"- large_file_suppressed: {self.large_file_suppressed_count}",
            f"- source_overview_count: {self.source_overview_count}",
            f"- list_tree_count: {self.list_tree_count}",
            f"- glob_files_count: {self.glob_files_count}",
            f"- empty_search_denied_count: {self.empty_search_denied_count}",
            f"- inspect_round_count: {self.inspect_round_count}",
            f"- logical_read_action_count: {self.logical_read_action_count}",
            f"- repeated_inspect_target_count: {self.repeated_inspect_target_count}",
            f"- paste_marker_stripped_count: {self.paste_marker_stripped_count}",
            f"- tool_rows_suppressed_count: {self.tool_rows_suppressed_count}",
            f"- representative_read_count: {self.representative_read_count}",
            f"- fallback_internal_reason_hidden: {self.fallback_internal_reason_hidden}",
        ]
        if self.source_analysis_coverage_ratio is not None:
            lines.append(f"- source_analysis_coverage_ratio: {self.source_analysis_coverage_ratio}")
        if self.final_answer_language:
            lines.append(f"- final_answer_language: {self.final_answer_language}")
        if self.repeated_targets:
            repeated = ", ".join(f"{target} x{count}" for target, count in sorted(self.repeated_targets.items()))
            lines.append(f"- repeated_targets: {repeated}")
        if self.final_status:
            lines.append(f"- final_status: {self.final_status}")
        return "\n".join(lines)


class SessionAnalyzer:
    """Reads session JSONL and computes human-readable diagnostics."""

    def analyze(self, path: str | Path) -> SessionDiagnostics:
        log_path = Path(path).expanduser()
        actions: dict[str, str] = {}
        target_counts: dict[str, int] = {}
        mutation_after_validation_failure = False
        validation_failed_open = False
        source_overview_tool_count = 0
        source_overview_event_count = 0
        empty_search_tool_count = 0
        empty_search_event_count = 0
        diagnostics = SessionDiagnostics(path=str(log_path))

        for record in self._records(log_path):
            event_type = str(record.get("event_type") or "")
            record_kind = str(record.get("record_kind") or "")
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            normalized = payload.get("normalized") if isinstance(payload.get("normalized"), dict) else {}
            if event_type.startswith("tool_") or record_kind in {"action", "observation"}:
                diagnostics.event_tool_records += 1
            if event_type == "tool_call_requested":
                action_id = str(normalized.get("action_id") or self._payload_tool_id(payload) or "")
                tool_name = str(normalized.get("tool_name") or self._payload_tool_name(payload) or "")
                if action_id:
                    actions[action_id] = tool_name
                if tool_name in {"read_file", "search_files", "list_directory", "glob_files", "list_tree", "source_overview"}:
                    diagnostics.logical_read_action_count += 1
                target = str(normalized.get("target") or self._payload_target(payload) or "")
                if target:
                    target_counts[target] = target_counts.get(target, 0) + 1
            elif event_type == "inspect_stage_selected":
                diagnostics.inspect_round_count += 1
            elif event_type == "user_prompt_submitted":
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                if data.get("paste_marker_stripped") is True:
                    diagnostics.paste_marker_stripped_count += 1
            elif event_type == "source_overview_collected":
                source_overview_event_count += 1
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
                ratio = coverage.get("coverage_ratio")
                if isinstance(ratio, int | float):
                    diagnostics.source_analysis_coverage_ratio = float(ratio)
                representative_reads = data.get("representative_reads") if isinstance(data.get("representative_reads"), list) else []
                diagnostics.representative_read_count = max(
                    diagnostics.representative_read_count,
                    len([path for path in representative_reads if isinstance(path, str) and path]),
                )
            elif event_type == "empty_search_denied":
                empty_search_event_count += 1
            elif event_type == "tool_call_schema_denied":
                diagnostics.model_requested_tools += 1
                diagnostics.schema_denied_count += 1
                diagnostics.schema_denied_tools += 1
            elif event_type == "tool_policy_checked":
                diagnostics.model_requested_tools += 1
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                if data.get("allowed") is False:
                    diagnostics.policy_denied_tools += 1
            elif event_type == "tool_call_suppressed":
                diagnostics.suppressed_count += 1
                diagnostics.suppressed_tools += 1
            elif event_type == "tool_observation_reused":
                diagnostics.reused_observation_count += 1
                diagnostics.reused_observations += 1
            elif event_type == "tool_execution_finished":
                diagnostics.executed_tools += 1
                result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                tool_name = str(result.get("name") or normalized.get("tool_name") or "")
                metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
                if result.get("ok") and tool_name in {
                    "read_file",
                    "search_files",
                    "list_directory",
                    "glob_files",
                    "list_tree",
                    "source_overview",
                }:
                    diagnostics.tool_rows_suppressed_count += 1
                if tool_name == "list_tree":
                    diagnostics.list_tree_count += 1
                elif tool_name == "glob_files":
                    diagnostics.glob_files_count += 1
                elif tool_name == "source_overview":
                    source_overview_tool_count += 1
                    coverage = metadata.get("coverage") if isinstance(metadata.get("coverage"), dict) else {}
                    ratio = coverage.get("coverage_ratio")
                    if isinstance(ratio, int | float):
                        diagnostics.source_analysis_coverage_ratio = float(ratio)
                    representative_reads = metadata.get("representative_reads")
                    if isinstance(representative_reads, list):
                        diagnostics.representative_read_count = max(
                            diagnostics.representative_read_count,
                            len([path for path in representative_reads if isinstance(path, str) and path]),
                        )
                elif tool_name == "search_files" and result.get("error_type") == "invalid_query":
                    empty_search_tool_count += 1
                if result.get("ok") and result.get("name") in {"write_file", "patch_file", "delete_path"}:
                    if validation_failed_open:
                        mutation_after_validation_failure = True
            elif event_type == "model_request_prepared":
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                value = data.get("message_chars")
                if isinstance(value, int):
                    diagnostics.request_chars_by_round.append(value)
            elif event_type == "context_built":
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                sections = data.get("sections") if isinstance(data.get("sections"), list) else []
                diagnostics.large_file_suppressed_count += sum(
                    1
                    for section in sections
                    if isinstance(section, dict) and section.get("section_type") == "active_file_metadata"
                )
            elif event_type == "validation_finished":
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                if data.get("passed") is False:
                    diagnostics.validation_failures += 1
                    validation_failed_open = True
                    mutation_after_validation_failure = False
            elif event_type == "turn_result_ready":
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                status = data.get("status")
                diagnostics.final_status = str(status) if isinstance(status, str) else diagnostics.final_status
                final_answer = str(data.get("final_answer") or "")
                if final_answer:
                    diagnostics.final_answer_language = "ko" if any("\uac00" <= ch <= "\ud7a3" for ch in final_answer) else "en"
                recovery_states = data.get("recovery_states") if isinstance(data.get("recovery_states"), list) else []
                hidden_reasoning = any(
                    isinstance(state, dict) and "reasoning_only" in str(state.get("reason") or state.get("last_error") or "")
                    for state in recovery_states
                )
                visible_internal = "reasoning_only" in final_answer or "model_returned_reasoning_only" in final_answer
                if hidden_reasoning and final_answer and not visible_internal:
                    diagnostics.fallback_internal_reason_hidden = 1

        if validation_failed_open and not mutation_after_validation_failure:
            diagnostics.validation_failures_without_later_mutation = 1
        diagnostics.logical_tool_actions = len(actions)
        diagnostics.source_overview_count = source_overview_event_count or source_overview_tool_count
        diagnostics.empty_search_denied_count = empty_search_event_count or empty_search_tool_count
        diagnostics.repeated_targets = {target: count for target, count in target_counts.items() if count > 1}
        diagnostics.repeated_inspect_target_count = sum(
            count - 1
            for target, count in diagnostics.repeated_targets.items()
            if target and not target.startswith("run_tests")
        )
        return diagnostics

    def _records(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
        return records

    @staticmethod
    def _payload_tool_id(payload: dict[str, Any]) -> str | None:
        tool_call = payload.get("tool_call")
        if isinstance(tool_call, dict):
            return str(tool_call.get("id") or "")
        return None

    @staticmethod
    def _payload_tool_name(payload: dict[str, Any]) -> str | None:
        tool_call = payload.get("tool_call")
        if isinstance(tool_call, dict):
            return str(tool_call.get("name") or "")
        return None

    @staticmethod
    def _payload_target(payload: dict[str, Any]) -> str | None:
        tool_call = payload.get("tool_call")
        args = tool_call.get("arguments") if isinstance(tool_call, dict) else None
        if not isinstance(args, dict):
            return None
        for key in ("file_path", "path", "query", "command", "url"):
            value = args.get(key)
            if isinstance(value, str) and value:
                return value
        return None
