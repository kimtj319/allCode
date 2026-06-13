"""Mutable state shared by one model/tool round loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from allCode.core.models import Message


MUTATION_TOOL_NAMES = {"patch_file", "write_file", "delete_path"}
INSPECTION_TOOL_NAMES = {
    "read_file",
    "search_files",
    "list_directory",
    "glob_files",
    "list_tree",
    "source_overview",
    "source_probe",
}


@dataclass
class RoundRuntime:
    messages: list[Message]
    pseudo_tool_retry_used: bool = False
    validation_repair_pending: bool = False
    validation_action_pending: bool = False
    mutation_action_pending: bool = False
    awaiting_revalidation_after_mutation: bool = False
    phase_block_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    repair_context_read_paths: set[str] = field(default_factory=set)
    mutation_attempted_after_failed_validation: bool = False
    mutation_succeeded_after_failed_validation: bool = False
    malformed_tool_retries: int = 0
    inspection_actions: int = 0
    inspection_rounds: int = 0
    final_answer_after_change_requested: bool = False
    inspect_final_answer_requested: bool = False
    external_final_answer_requested: bool = False
    last_inspect_stage: str = ""
    last_phase_prompt: str = ""
