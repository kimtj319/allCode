"""Explicit phase-to-tool gate for model/tool rounds."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence

PhaseName = Literal[
    "normal",
    "inspection_required",
    "mutation_required",
    "test_authoring_required",
    "validation_required",
    "validation_failed",
    "repair_mutation_required",
    "revalidation_required",
    "repair_exhausted",
]

INSPECTION_TOOLS = {"read_file", "search_files", "list_directory"}
MUTATION_TOOLS = {"patch_file", "write_file"}
VALIDATION_TOOLS = {"run_tests"}


class PhaseToolGate(CoreModel):
    phase: PhaseName = "normal"
    allowed_tool_names: set[str] = Field(default_factory=set)
    required_next_action: str = ""
    deny_hidden_tools: bool = True
    reason: str = ""

    @property
    def active(self) -> bool:
        return self.phase != "normal" and bool(self.allowed_tool_names)


def test_artifact_required(prompt: str, evidence: CompletionEvidence, *, workspace_root: str) -> bool:
    if not _prompt_requests_tests(prompt):
        return False
    changed = [*evidence.changed_files, *evidence.created_files]
    return not any(looks_like_test_artifact(path, workspace_root=workspace_root) for path in changed)


def build_phase_tool_gate(
    *,
    prompt: str,
    routing,
    evidence: CompletionEvidence,
    workspace_root: str,
    inspection_budget_available: bool,
    mutation_action_pending: bool,
    validation_action_pending: bool,
    validation_repair_pending: bool,
    awaiting_revalidation_after_mutation: bool,
    repair_exhausted: bool = False,
) -> PhaseToolGate:
    if repair_exhausted:
        return PhaseToolGate(
            phase="repair_exhausted",
            allowed_tool_names=set(),
            required_next_action="Summarize the failed validation and repair attempts.",
            reason="repair attempts are exhausted",
        )
    if getattr(routing, "read_only_requested", False) or getattr(routing, "requires_external_knowledge", False):
        return PhaseToolGate()
    if validation_action_pending or awaiting_revalidation_after_mutation:
        return PhaseToolGate(
            phase="validation_required" if validation_action_pending else "revalidation_required",
            allowed_tool_names=set(VALIDATION_TOOLS),
            required_next_action="Run validation with run_tests.",
            reason="validation is required after file mutation",
        )
    if validation_repair_pending:
        return PhaseToolGate(
            phase="validation_failed",
            allowed_tool_names={*INSPECTION_TOOLS, *MUTATION_TOOLS},
            required_next_action="Inspect the failure if needed, then repair with patch_file or write_file.",
            reason="validation failed and must be repaired before revalidation",
        )
    if getattr(routing, "requires_mutation", False) and test_artifact_required(prompt, evidence, workspace_root=workspace_root):
        return PhaseToolGate(
            phase="test_authoring_required",
            allowed_tool_names={*INSPECTION_TOOLS, *MUTATION_TOOLS},
            required_next_action="Create or update a relevant test file with write_file or patch_file before validation.",
            reason="the prompt requests tests but no test artifact has changed yet",
        )
    if mutation_action_pending:
        allowed = {"read_file", *MUTATION_TOOLS} if inspection_budget_available else set(MUTATION_TOOLS)
        return PhaseToolGate(
            phase="mutation_required",
            allowed_tool_names=allowed,
            required_next_action="Apply the requested file mutation with patch_file or write_file.",
            reason="a mutation request has not produced file-change evidence yet",
        )
    return PhaseToolGate()


def looks_like_test_artifact(path: str, *, workspace_root: str) -> bool:
    try:
        candidate = Path(path).resolve()
        root = Path(workspace_root).resolve()
        relative = candidate.relative_to(root).as_posix().lower()
    except (OSError, ValueError):
        relative = Path(path).as_posix().lower()
    parts = [part for part in relative.split("/") if part]
    if any(part in {"test", "tests", "__tests__"} for part in parts[:-1]):
        return True
    name = parts[-1] if parts else relative
    if name in {"test.py", "tests.py"}:
        return True
    return (
        name.startswith("test_")
        or name.endswith(("_test.py", "_test.go", ".test.js", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts", ".spec.tsx"))
        or "spec" in name
    )


def _prompt_requests_tests(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = prompt.replace(" ", "")
    english_patterns = (
        r"\b(?:add|write|create|update|implement|include)\s+(?:unit\s+)?tests?\b",
        r"\btests?\s+(?:for|covering|that\s+cover)\b",
    )
    if any(re.search(pattern, lowered) for pattern in english_patterns):
        return True
    korean_patterns = (
        "테스트도추가",
        "테스트를추가",
        "테스트추가",
        "테스트포함",
        "테스트를포함",
        "테스트도포함",
        "테스트도작성",
        "테스트를작성",
        "테스트작성",
        "테스트도만들",
        "테스트를만들",
        "테스트로만들",
        "테스트만들",
        "테스트를나눠",
        "테스트로나눠",
        "테스트분리",
        "테스트도보강",
        "테스트를보강",
        "테스트보강",
        "관련테스트를추가",
    )
    if any(marker in compact for marker in korean_patterns):
        return True
    return "테스트" in compact and any(marker in compact for marker in ("추가", "작성", "포함", "만들", "보강", "나눠", "분리"))
