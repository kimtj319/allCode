"""Model-backed file editor helpers for generation workflow."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from allCode.agent.api_obligation_checker import _extract_file_symbols
from allCode.agent.project_planner import _extract_json_object
from allCode.agent.task_plan import PlannedFile, ProjectPlan
from allCode.agent.workflow_diff import search_replace_repairs
from allCode.core.models import Message, TurnInput
from allCode.core.path_patterns import looks_like_test_path as _looks_test_path
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings

MAX_CONTEXT_FILE_CHARS = 2400
MAX_TOTAL_CONTEXT_CHARS = 12000


class ModelWorkflowEditor:
    """Generate and repair planned files without mutating the workspace directly."""

    def __init__(self, *, llm_client: LLMClient, settings: ModelSettings) -> None:
        self._llm_client = llm_client
        self._settings = settings

    async def generate_file(
        self,
        planned_file: PlannedFile,
        plan: ProjectPlan,
        turn_input: TurnInput,
        *,
        task_digest: str = "",
    ) -> str:
        response = await self._llm_client.complete(
            _editor_messages(planned_file, plan, turn_input, task_digest=task_digest),
            tools=[],
            settings=self._settings,
        )
        content = _strip_markdown_fence(response.final_text)
        if _looks_valid_for_path(planned_file.path, content) and _preserves_planned_public_contract(
            planned_file.path,
            planned_file.content,
            content,
            plan=plan,
        ):
            return content
        return planned_file.content

    async def repair_files(
        self,
        plan: ProjectPlan,
        failure_log: str,
        turn_input: TurnInput,
        *,
        task_digest: str = "",
    ) -> dict[str, str]:
        response = await self._llm_client.complete(
            _repair_messages(plan, failure_log, turn_input, task_digest=task_digest),
            tools=[],
            settings=self._settings,
        )
        allowed_paths = set(plan.required_paths())
        payload = _extract_json_object(response.final_text)
        repaired: dict[str, str] = {}
        if isinstance(payload, dict):
            for raw_path, raw_content in payload.items():
                path = _safe_relative_path(str(raw_path))
                if path is None or path not in allowed_paths:
                    continue
                content = str(raw_content)
                if _looks_valid_for_path(path, content):
                    repaired[path] = content
        if not repaired:
            for path, content in search_replace_repairs(response.final_text, plan, turn_input).items():
                if path in allowed_paths and _looks_valid_for_path(path, content):
                    repaired[path] = content
        return repaired


def _editor_messages(
    planned_file: PlannedFile,
    plan: ProjectPlan,
    turn_input: TurnInput,
    *,
    task_digest: str = "",
) -> list[Message]:
    system_prompt = (
        "You are the file editor component for allCode. "
        "Write exactly one complete file for the accepted project plan. "
        "Return only raw file content, with no markdown fences or explanation. "
        "Preserve the user request, project constraints, imports, and existing generated file contracts."
    )
    user_prompt = "\n".join(
        [
            f"User request: {turn_input.user_prompt}",
            "",
            "Project constraints:",
            *[f"- {constraint}" for constraint in plan.constraints],
            "",
            "Compact task loop state:",
            _compact_text(task_digest, limit=1800) if task_digest else "No task digest was provided.",
            "",
            f"Target root: {plan.target_root}",
            f"Target file: {planned_file.path}",
            f"Purpose: {planned_file.purpose}",
            f"Stage: {planned_file.stage}",
            "",
            "Existing generated file context:",
            _existing_file_context(plan, turn_input, exclude_path=planned_file.path),
            "",
            "Write the full file content now.",
        ]
    )
    return [Message(role="system", content=system_prompt), Message(role="user", content=user_prompt)]


def _repair_messages(
    plan: ProjectPlan,
    failure_log: str,
    turn_input: TurnInput,
    *,
    task_digest: str = "",
) -> list[Message]:
    system_prompt = (
        "You are the file repair component for allCode. "
        "Use the validation or completion failure to update only files from the accepted plan. "
        "Treat tests and public API obligation errors as executable contracts. "
        "If tests import missing functions, classes, attributes, or commands, implement them in source files instead of leaving placeholders. "
        "Public API obligations are literal: Class.method must be defined with that exact method name on that class, and listed functions must be exported with the listed names. "
        "Do not satisfy a listed API only with a renamed helper or a semantically similar wrapper. "
        "For Python, avoid class-definition-time decorators that require an instance; use module-level decorators or explicit registration after instantiation. "
        "When the failure log names preferred repair target files, repair those allowed files first. "
        "If the current implementation is too small to satisfy the listed APIs, replace the full allowed source file content. "
        "Prefer a compact search/replace block when only a small change is needed; otherwise return exactly one JSON object "
        "mapping relative file paths to full corrected file contents. "
        "Search/replace blocks must use: path line, <<<<<<< SEARCH, exact old text, =======, new text, >>>>>>> REPLACE. "
        "Do not include files outside the plan."
    )
    user_prompt = "\n".join(
        [
            f"User request: {turn_input.user_prompt}",
            "",
            "Project constraints:",
            *[f"- {constraint}" for constraint in plan.constraints],
            "",
            "Compact task loop state:",
            _compact_text(task_digest, limit=2200) if task_digest else "No task digest was provided.",
            "",
            "Allowed files:",
            *[f"- {path}" for path in plan.required_paths()],
            "",
            "Failure log:",
            _compact_text(failure_log, limit=5000),
            "",
            "Current generated file context:",
            _existing_file_context(plan, turn_input),
            "",
            'Return either JSON like {"src/pkg/file.py": "complete corrected content"} or a search/replace block for an allowed file.',
        ]
    )
    return [Message(role="system", content=system_prompt), Message(role="user", content=user_prompt)]


def _existing_file_context(plan: ProjectPlan, turn_input: TurnInput, *, exclude_path: str | None = None) -> str:
    root = Path(turn_input.workspace.root).expanduser()
    chunks: list[str] = []
    used = 0
    for file_path in plan.required_paths():
        if file_path == exclude_path:
            continue
        resolved = root / plan.target_root / file_path
        if not resolved.exists() or not resolved.is_file():
            continue
        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError:
            continue
        excerpt = _compact_text(content, limit=MAX_CONTEXT_FILE_CHARS)
        chunk = f"File: {file_path}\n{excerpt}"
        if used + len(chunk) > MAX_TOTAL_CONTEXT_CHARS:
            chunks.append("[additional generated files omitted from editor context]")
            break
        chunks.append(chunk)
        used += len(chunk)
    return "\n\n".join(chunks) if chunks else "No generated files are available yet."


def _looks_valid_for_path(path: str, content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    suffix = Path(path).suffix.lower()
    name = Path(path).name.lower()
    if suffix == ".py":
        try:
            module = ast.parse(stripped)
        except SyntaxError:
            return False
        if not module.body:
            return False
        return not _looks_like_prompt_echo(stripped)
    if suffix in {".toml", ".ini", ".cfg"}:
        return "=" in stripped or "[" in stripped
    if suffix in {".json"}:
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            return False
        return True
    if suffix in {".md", ".rst"} or name in {"readme", "readme.md"}:
        return len(stripped) >= 12
    if "test" in name and suffix == ".py":
        return "def test_" in stripped or "pytest" in stripped
    return len(stripped) >= 8


def _preserves_planned_public_contract(
    path: str,
    planned_content: str,
    generated_content: str,
    *,
    plan: ProjectPlan,
) -> bool:
    suffix = Path(path).suffix.lower()
    if suffix != ".py" or _looks_test_path(path):
        return True
    planned_symbols = _source_contract_symbols(planned_content, suffix)
    obligation_symbols = _contract_symbols_for_path(plan, path)
    planned_symbols.update(obligation_symbols)
    if len(planned_symbols) < 3:
        if obligation_symbols:
            generated_symbols = _source_contract_symbols(generated_content, suffix)
            return all(_contract_symbol_satisfied(generated_symbols, symbol) for symbol in obligation_symbols)
        return True
    generated_symbols = _source_contract_symbols(generated_content, suffix)
    if obligation_symbols and not all(_contract_symbol_satisfied(generated_symbols, symbol) for symbol in obligation_symbols):
        return False
    preserved = planned_symbols.intersection(generated_symbols)
    required = min(4, max(2, len(planned_symbols) // 2))
    return len(preserved) >= required


def _contract_symbols_for_path(plan: ProjectPlan, path: str) -> set[str]:
    symbols: set[str] = set()
    for obligation in plan.api_obligations:
        if obligation.path == path:
            symbols.update(_contract_symbol_variants(obligation.symbol))
    return symbols


def _source_contract_symbols(content: str, suffix: str) -> set[str]:
    symbols: set[str] = set()
    for symbol in _extract_file_symbols(content, suffix):
        symbols.add(symbol)
        symbols.update(_contract_symbol_variants(symbol))
    return symbols


def _contract_symbol_variants(symbol: str) -> set[str]:
    symbols: set[str] = set()
    if not symbol:
        return symbols
    symbols.add(symbol)
    if symbol.startswith("__all__:"):
        symbol = symbol.split(":", 1)[1]
        symbols.add(symbol)
    if "." in symbol:
        owner, _, member = symbol.partition(".")
        symbols.add(owner)
        if len(member) > 2:
            symbols.add(member)
        return symbols
    if len(symbol) > 2:
        symbols.add(symbol)
    return symbols


def _contract_symbol_satisfied(actual_symbols: set[str], expected_symbol: str) -> bool:
    if "." in expected_symbol:
        return expected_symbol in actual_symbols
    return expected_symbol in actual_symbols or any(symbol.endswith(f".{expected_symbol}") for symbol in actual_symbols)



def _looks_like_prompt_echo(text: str) -> bool:
    echo_markers = (
        "User request:",
        "Project constraints:",
        "Existing generated file context:",
        "Write the full file content now.",
        "Target file:",
        "Failure log:",
    )
    return any(marker in text for marker in echo_markers)


def _strip_markdown_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```(?:[a-zA-Z0-9_.+-]+)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _compact_text(text: str, *, limit: int) -> str:
    normalized = "\n".join(line.rstrip() for line in str(text or "").splitlines())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n[truncated]"


def _safe_relative_path(value: str) -> str | None:
    normalized = value.strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    if any(part in {".git", ".venv", "node_modules"} for part in normalized.split("/")):
        return None
    return normalized
