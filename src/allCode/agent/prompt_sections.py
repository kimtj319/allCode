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


def unified_agent_instruction(routing: RoutingDecision | None = None) -> str:
    """Authoritative guidance for the unified (Codex/Claude-style) loop.

    The model has the full toolset and decides what the request is and which
    tools fit. The route below is advisory; the model may ignore it and switch
    tool types freely. The critical rule fixes the failure where a non-codebase
    question was routed into source inspection and looped probing the repo."""
    lines = [
        "Unified tool use: you have the FULL toolset this turn (read_file, source_probe, "
        "search_files, list_tree, glob_files, write_file, patch_file, delete_path, run_command, "
        "run_tests, web_search, update_plan). Decide for yourself what the request is and use the "
        "tools that fit; you may switch tool types freely within the turn.",
        "Classify the request yourself and act accordingly:",
        "- General / real-time / world-knowledge question (NOT about this repository): answer "
        "directly, or call web_search for fresh or external facts. Do NOT read or probe this "
        "project's source for questions that are not about this codebase.",
        "- Project code analysis: use read_file / source_probe / search_files / list_tree. GROUND every "
        "claim in files you actually read — cite concrete `path/file.py:line` (or at least the file path) "
        "for each component you describe. Do NOT answer a 'how is X implemented / where is Y' question "
        "from a generic package-role summary alone; name the real files and symbols you opened.",
        "- Project code change: edit with write_file / patch_file, then verify with run_tests when applicable.",
        "- Other / operational: use run_command.",
        # Anti-loop: don't re-issue a read/overview that returns what you already
        # have (common on broad 'evaluate/assess' asks over a small codebase) —
        # once you have enough evidence, synthesize the answer instead of probing
        # the same target again.",
        "Do not repeat the same source_overview / source_probe / read_file call "
        "you have already run; if you already have the structure or file contents, "
        "stop gathering and answer from that evidence.",
        # Coverage: for whole-project analysis, use the available rounds to go
        # BROAD, not shallow — partial coverage is the common failure here.
        "Project-wide analysis: when the request is to analyze/evaluate/review the "
        "WHOLE codebase, aim for breadth. After source_overview, probe or read at "
        "least one representative file from EACH major package/module — entry "
        "points, core logic, and tests — across many files rather than deep-reading "
        "only a few. Keep going until the major modules are covered, then synthesize; "
        "do not stop after a couple of files and call the codebase 'analyzed'. If you "
        "must stop early, say which areas were not yet examined.",
        # Grounding & freshness (#3): keep web answers honest.
        "Grounding: when you answer from web_search, cite the source (site or URL) and, for any "
        "time-sensitive value (prices, rates, versions, 'latest', 'today', 'now'), state that it is "
        "as of the search results and may differ from the live value. Never present a fabricated or "
        "stale number as the current value; if the search did not yield a figure, say so plainly.",
        # Edit robustness (#2): precise, safe edits on real/large files.
        "Editing: before changing an existing file, read the exact region first; prefer patch_file "
        "with enough surrounding context to match a unique location. For structural edits to a named "
        "symbol use replace_symbol / apply_edits. After edits, re-read or run_tests to confirm the "
        "change applied as intended; do not assume success.",
        # Verification depth (#6): run the project's real checks.
        "Verification: after changing code, run the project's own tests/lints when present "
        "(run_tests; e.g. pytest / npm test) and iterate until they pass, rather than only "
        "byte-compiling. Ground completion claims in actual command output.",
        # Regression safety: allCode's core promise is that a change must not break
        # what already worked. This guards the #1 failure mode of coding agents.
        "No regressions: a code change must not break functionality that already worked. "
        "Before reporting completion, run the EXISTING tests that cover the area you changed "
        "(not only any new tests you wrote); if a test that was passing now fails because of "
        "your change, fix it or revert that change. Never report success when you have broken "
        "existing functionality. When you edit a shared function/symbol, find its "
        "callers/dependents (search_files / source_probe) and confirm they still work.",
        # Decomposition & delegation (#4): use sub-agents for large work.
        "Large tasks: for a broad analysis or multi-area change, decompose it (update_plan) and "
        "delegate independent sub-investigations with delegate_task instead of doing everything in "
        "one long chain; synthesize their results.",
        # Parallel fan-out: independent read-only investigations run concurrently
        # when emitted together, so prefer breadth-in-one-step over a long chain.
        "Parallel investigation: when several read-only sub-questions are independent, emit multiple "
        "`task` calls in the SAME response — they run concurrently — then synthesize the returned "
        "findings, rather than investigating them one after another.",
        # Skills: load a project skill's instructions on demand when one fits.
        "Skills: if a `skill` tool is available and one of its listed skills fits the task, call "
        "skill(<name>) to load its instructions and follow them before proceeding.",
        # --- Output discipline (derived from head-to-head harness evaluation) ---
        # Completeness: the #1 answer-quality miss was dropping later items.
        "Answer every part: if the prompt lists multiple items (terms to define, sub-questions, "
        "rows, N things), produce one entry for EACH — never stop after the first. Before finishing, "
        "re-scan the prompt's list and confirm each item is covered.",
        # Exact-format adherence: obey output-shape constraints literally.
        "Exact-format requests: when the prompt dictates an output shape (\"X만 출력\", \"only output\", "
        "\"다른 텍스트 금지\", \"N개 불릿\", a strict template), return EXACTLY that with no extra prose, "
        "headings, or preamble. If it asks for a raw value/array/regex/one line, do NOT wrap it in a "
        "code fence.",
        # Enumeration formatting: structure beats run-on prose.
        "Lists: when enumerating or describing multiple items (\"각 …\", \"한 줄씩\", \"목록\", \"N개\"), "
        "render a bulleted list or a markdown table — not one run-on comma sentence.",
        # Honesty on current facts without live evidence.
        "Current-fact honesty: if you answer a \"latest / current / 최신 / 현재 / 요즘\" question from "
        "training knowledge without web_search, say your knowledge is not live and flag which "
        "specifics may be outdated. Never invent citation tags, source handles, or URLs you did not "
        "actually retrieve — answer from knowledge plainly instead.",
        # Terminal-plain output.
        "Plain terminal output: write for a terminal — use ASCII arrows (\"->\") and \"*\"/\"-\" bullets; "
        "never emit LaTeX math markup ($\\rightarrow$, $\\downarrow$).",
        # Scale output to the task — avoid boilerplate dumps on small asks.
        "Match length to the task: for a one-line fact, a single snippet, or a single-file change, "
        "answer concisely. Do not append a full multi-section report, a repository overview, or "
        "status boilerplate the request did not ask for.",
        # Inline-only edits: don't write files when asked for code in the reply.
        "Inline-only edits: when the prompt gives a snippet to refactor/fix and wants the answer in "
        "your reply (or says \"파일은 만들지 말고\" / \"don't create files\"), return the revised code in "
        "your message and do NOT create or modify any workspace file.",
        # Safe scoping for vague/destructive requests.
        "Vague or destructive requests (\"정리해줘\", \"불필요한 파일을 지워줘\", \"최적화\", \"전체를 "
        "리팩터링\", \"필요 없는 의존성을 제거\"): do NOT guess-and-mutate. State your intended scope and "
        "assumptions first; if it is genuinely ambiguous or risky, propose the specific change "
        "(a scoped plan/diff) and ask for confirmation rather than broadly editing or deleting. For a "
        "remove/delete request, check usages and affected tests BEFORE writing; if you cannot verify, "
        "propose the diff instead of applying it.",
    ]
    if routing is not None:
        lines.append(
            f"Advisory routing hint (may be wrong — ignore if it does not fit): {routing.kind}."
        )
    return "\n".join(lines)


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
    if routing.kind in {"inspect", "modify", "operate"}:
        lines.append(
            "Task plan: if the task has 3 or more distinct steps, your FIRST action must be an "
            "update_plan call listing those steps (all pending), then call update_plan again to mark "
            "progress (exactly one step in_progress, finished steps completed) before each new phase. "
            "This is the only way the user sees progress, so do not skip it for a genuinely multi-step "
            "task; skip it only for a trivial single-step request."
        )
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
                "Before finalizing, confirm the change did not break previously-passing tests or the callers of any symbol you edited; if it did, fix or revert rather than reporting success.",
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
