"""Reusable prompt section renderers for agent instructions."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.answer_prompt import answer_route_instruction
from allCode.agent.context import ContextBundle
from allCode.agent.router import RoutingDecision
from allCode.core.result import RepairTarget


def feature_objective_instruction(objectives: Sequence[str]) -> str:
    compact = ", ".join(list(dict.fromkeys(objective for objective in objectives if objective))[:8])
    return (
        "Active feature objectives for this turn: "
        f"{compact}.\n"
        "Treat these as implementation and validation obligations, not as final-answer keywords. "
        "When modifying code, implement visible behavior/API and tests for the objectives. "
        "For non-English domain objectives, use conventional code-facing English identifiers when appropriate "
        "for the target language, and keep the original user-facing meaning intact."
    )


def routing_instruction(routing: RoutingDecision) -> str:
    lines = [
        f"Routing decision: {routing.kind} (confidence {routing.confidence:.2f}).",
        f"Reason: {routing.reason}",
        f"Allowed tool capabilities: {', '.join(sorted(routing.tool_capabilities)) or 'none'}.",
        f"Workflow hint: {routing.workflow_hint}.",
    ]
    if routing.target_hint:
        lines.append(f"Target hint: {routing.target_hint}.")
    answer_instruction = answer_route_instruction(routing)
    if answer_instruction:
        lines.append(answer_instruction)
    if routing.read_only_requested:
        lines.extend(
            [
                "Read-only constraint: do not call mutation, shell, validation, or file deletion tools.",
                "Return summaries, reports, and analysis directly in the final answer; do not create README, SUMMARY, report, or other document files.",
                "Use only read/search/source overview evidence tools when workspace evidence is needed.",
                "파일로 생성하지 말고 최종 답변에 직접 작성하십시오.",
                "파일 생성, 수정, 삭제, 포맷팅, 커밋, 테스트 실행 도구를 호출하지 마십시오.",
            ]
        )
    if routing.kind == "inspect":
        lines.extend(
            [
                "For source tree, directory structure, module inventory, or package-role inspection, start with source_overview, list_tree, or glob_files.",
                "Do not call search_files with an empty query; search_files is only for non-empty literal content search.",
                "For file-grounded inspection, use search_files or read_file before answering when the user names a file, asks to actually read/verify evidence, or requests a source filename.",
                "Do not answer from workspace context alone when the prompt asks for file evidence; create an observable tool result first.",
                "If the user asks for directory structure, file layout, module inventory, or file list, verify with source_overview, list_tree, glob_files, or list_directory before answering.",
                "After source_overview suggests representative files, prefer source_probe before read_file so only symbol/range evidence is added.",
                "For symbols, classes, functions, or project-name evidence, prefer source_probe on known candidate files; use search_files only to locate missing candidates.",
                "After enough bounded source_overview/source_probe evidence is available, stop calling tools and provide the final answer.",
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
    return "\n".join(lines)


def context_instruction(context_bundle: ContextBundle) -> str:
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


def format_repair_targets(repair_targets: Sequence[RepairTarget]) -> list[str]:
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


def join_prompt_parts(instruction: str, details: str = "") -> str:
    detail = details.strip()
    if not detail:
        return instruction
    return f"{instruction}\n\n{detail}"
