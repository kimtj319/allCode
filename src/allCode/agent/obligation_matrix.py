"""Prompt-derived obligation coverage summaries for generation workflow."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from allCode.agent.task_plan import ProjectPlan
from allCode.agent.validation_runner import ValidationResult
from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence


class ObligationMatrix(CoreModel):
    source_obligations: list[str] = Field(default_factory=list)
    test_obligations: list[str] = Field(default_factory=list)
    doc_obligations: list[str] = Field(default_factory=list)
    validation_obligations: list[str] = Field(default_factory=list)
    coverage_status: list[str] = Field(default_factory=list)

    def render(self, *, language: str = "en") -> list[str]:
        if not any((self.source_obligations, self.test_obligations, self.doc_obligations, self.validation_obligations, self.coverage_status)):
            return []
        if language == "ko":
            lines = ["요구사항 충족 매트릭스:"]
            lines.extend(_section("소스", self.source_obligations))
            lines.extend(_section("테스트", self.test_obligations))
            lines.extend(_section("문서", self.doc_obligations))
            lines.extend(_section("검증", self.validation_obligations))
            lines.extend(_section("상태", self.coverage_status))
            return lines
        lines = ["Obligation coverage matrix:"]
        lines.extend(_section("source", self.source_obligations))
        lines.extend(_section("tests", self.test_obligations))
        lines.extend(_section("docs", self.doc_obligations))
        lines.extend(_section("validation", self.validation_obligations))
        lines.extend(_section("status", self.coverage_status))
        return lines


def build_obligation_matrix(
    *,
    plan: ProjectPlan,
    completion_evidence: CompletionEvidence,
    validation_results: list[ValidationResult],
) -> ObligationMatrix:
    changed = _changed_relative_paths(plan, completion_evidence)
    source_obligations = _source_obligations(plan)
    test_obligations = _test_obligations(plan)
    doc_obligations = _doc_obligations(plan)
    validation_obligations = [command.command for command in plan.validation_commands[:6]]
    coverage = _coverage_status(
        plan=plan,
        changed=changed,
        completion_evidence=completion_evidence,
        validation_results=validation_results,
        source_obligations=source_obligations,
        test_obligations=test_obligations,
        doc_obligations=doc_obligations,
        validation_obligations=validation_obligations,
    )
    return ObligationMatrix(
        source_obligations=source_obligations[:10],
        test_obligations=test_obligations[:10],
        doc_obligations=doc_obligations[:8],
        validation_obligations=validation_obligations[:6],
        coverage_status=coverage[:12],
    )


def _source_obligations(plan: ProjectPlan) -> list[str]:
    rows: list[str] = []
    for obligation in plan.api_obligations:
        label = f"{obligation.path}:{obligation.symbol}"
        if obligation.reason:
            label = f"{label} ({obligation.reason})"
        rows.append(label)
    for file in plan.files:
        if file.required and _is_source_file(file.path):
            rows.append(f"{file.path} ({file.purpose})")
    return _dedupe(rows)


def _test_obligations(plan: ProjectPlan) -> list[str]:
    return _dedupe(f"{file.path} ({file.purpose})" for file in plan.files if file.required and _is_test_file(file.path))


def _doc_obligations(plan: ProjectPlan) -> list[str]:
    return _dedupe(f"{file.path} ({file.purpose})" for file in plan.files if file.required and _is_doc_file(file.path))


def _coverage_status(
    *,
    plan: ProjectPlan,
    changed: set[str],
    completion_evidence: CompletionEvidence,
    validation_results: list[ValidationResult],
    source_obligations: list[str],
    test_obligations: list[str],
    doc_obligations: list[str],
    validation_obligations: list[str],
) -> list[str]:
    status: list[str] = []
    for path in plan.required_paths():
        marker = "covered" if path in changed else "planned"
        status.append(f"{marker}: {path}")
    if source_obligations and test_obligations:
        status.append(f"tests planned for public/source obligations: {len(test_obligations)} file(s)")
    if doc_obligations:
        status.append(f"docs planned: {len(doc_obligations)} file(s)")
    if validation_obligations:
        validation_status = "passed" if completion_evidence.validation_passed is True else "pending_or_failed"
        status.append(f"validation {validation_status}: {validation_obligations[-1]}")
    if validation_results:
        last = validation_results[-1]
        status.append(f"latest validation detail: {'passed' if last.ok else 'failed'} {last.command}")
    if completion_evidence.web_unavailable_queries:
        status.append("external web evidence unavailable: conditional limitation, not a generation repair blocker")
    return _dedupe(status)


def _changed_relative_paths(plan: ProjectPlan, evidence: CompletionEvidence) -> set[str]:
    root = plan.target_root.rstrip("/") + "/"
    changed: set[str] = set()
    for path in [*evidence.created_files, *evidence.changed_files]:
        normalized = str(path).replace("\\", "/")
        if root in normalized:
            normalized = normalized.split(root, 1)[1]
        changed.add(normalized)
    return changed


def _is_source_file(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java"} and not _is_test_file(path)


def _is_test_file(path: str) -> bool:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    return lowered.startswith("tests/") or "/tests/" in lowered or name.startswith("test_") or ".test." in name or ".spec." in name


def _is_doc_file(path: str) -> bool:
    return Path(path).suffix.lower() in {".md", ".rst", ".txt"}


def _section(name: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [f"- {name}: " + "; ".join(items[:6])]


def _dedupe(values) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen
