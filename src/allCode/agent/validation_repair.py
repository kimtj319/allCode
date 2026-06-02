"""Validation failure summaries and repair-phase helpers."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum

from pydantic import Field

from allCode.core.models import CoreModel, ToolResult
from allCode.core.result import CompletionEvidence


class RepairPhaseState(StrEnum):
    NORMAL = "normal"
    VALIDATION_FAILED = "validation_failed"
    REPAIR_REQUIRED = "repair_required"
    MUTATION_DONE = "mutation_done"
    REVALIDATION_REQUIRED = "revalidation_required"
    REPAIR_EXHAUSTED = "repair_exhausted"


class ValidationFailureSummary(CoreModel):
    failure_type: str = "unknown"
    command: str = ""
    returncode: int | None = None
    failed_files: list[str] = Field(default_factory=list)
    failing_symbols: list[str] = Field(default_factory=list)
    traceback_excerpt: str = ""
    assertion_excerpt: str = ""
    suggested_read_targets: list[str] = Field(default_factory=list)
    recommended_tools: list[str] = Field(default_factory=list)
    must_not_repeat: list[str] = Field(default_factory=list)
    error_hash: str = ""
    summary: str = ""


def validation_repair_needed(routing, evidence: CompletionEvidence) -> bool:
    return bool(
        routing.requires_validation
        and routing.requires_mutation
        and evidence.validation_passed is False
    )


def summarize_validation_tool_result(result: ToolResult) -> ValidationFailureSummary | None:
    if result.name != "run_tests" or result.metadata.get("validation_passed") is not False:
        return None
    stdout = str(result.metadata.get("stdout") or result.content or "")
    stderr = str(result.metadata.get("stderr") or result.error or "")
    log = stderr or stdout or result.error or result.content or ""
    lines = [line.rstrip() for line in log.splitlines() if line.strip()]
    command = str(result.metadata.get("command") or "")
    returncode = result.metadata.get("returncode")
    failed_files = _extract_failed_files(lines)
    failing_symbols = _extract_failing_symbols(lines)
    failure_type = _classify_failure(lines)
    traceback_excerpt = _excerpt(lines, ("Traceback", "ZeroDivisionError", "Exception", "Error"))
    assertion_excerpt = _excerpt(lines, ("AssertionError", "E       ", "assert ", "FAILED"))
    suggested = sorted(set(failed_files + _path_like_mentions(lines)))[:8]
    summary = _summary(lines)
    return ValidationFailureSummary(
        failure_type=failure_type,
        command=command,
        returncode=returncode if isinstance(returncode, int) else None,
        failed_files=failed_files,
        failing_symbols=failing_symbols,
        traceback_excerpt=traceback_excerpt,
        assertion_excerpt=assertion_excerpt,
        suggested_read_targets=suggested,
        recommended_tools=_recommended_tools(failure_type, suggested),
        must_not_repeat=[command] if command else [],
        error_hash=_hash_log(log),
        summary=summary,
    )


def attach_validation_failure_summary(result: ToolResult) -> ToolResult:
    summary = summarize_validation_tool_result(result)
    if summary is None:
        return result
    metadata = dict(result.metadata)
    metadata["validation_failure"] = summary.model_dump(mode="json")
    content = result.content
    if not content.strip() and result.error:
        content = result.error
    if summary.summary and summary.summary not in content:
        content = f"{content.rstrip()}\n\nValidation failure summary:\n{summary.summary}".strip()
    return result.model_copy(update={"content": content, "metadata": metadata})


def _extract_failed_files(lines: list[str]) -> list[str]:
    found: list[str] = []
    patterns = (
        re.compile(r"([A-Za-z0-9_./-]+\.py):\d+"),
        re.compile(r"FAILED\s+([A-Za-z0-9_./-]+\.py)"),
    )
    for line in lines:
        for pattern in patterns:
            for match in pattern.findall(line):
                if match not in found:
                    found.append(match)
    return found[:8]


def _extract_failing_symbols(lines: list[str]) -> list[str]:
    symbols: list[str] = []
    pattern = re.compile(r"\b(test_[A-Za-z0-9_]+|[A-Za-z_][A-Za-z0-9_]*Error)\b")
    for line in lines:
        for match in pattern.findall(line):
            if match not in symbols:
                symbols.append(match)
    return symbols[:10]


def _classify_failure(lines: list[str]) -> str:
    text = "\n".join(lines[:120])
    lowered = text.lower()
    if "syntaxerror" in lowered or "indentationerror" in lowered:
        return "syntax_error"
    if "modulenotfounderror" in lowered or "importerror" in lowered or "no module named" in lowered:
        return "import_path_error"
    if "assertionerror" in lowered or "assert " in lowered or "e       " in lowered:
        return "assertion_mismatch"
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)\b", text):
        return "runtime_exception"
    if "not found" in lowered or "no such file" in lowered or "can't open file" in lowered:
        return "command_or_cwd_error"
    if "failed" in lowered or "error" in lowered:
        return "test_failure"
    return "unknown"


def _recommended_tools(failure_type: str, targets: list[str]) -> list[str]:
    tools = ["read_file" if targets else "search_files"]
    if failure_type in {"syntax_error", "assertion_mismatch", "runtime_exception", "import_path_error"}:
        tools.append("patch_file")
    if failure_type == "command_or_cwd_error":
        tools.append("list_directory")
    tools.append("run_tests")
    seen: list[str] = []
    for tool in tools:
        if tool not in seen:
            seen.append(tool)
    return seen


def _path_like_mentions(lines: list[str]) -> list[str]:
    mentions: list[str] = []
    pattern = re.compile(r"\b([A-Za-z0-9_./-]+\.(?:py|js|ts|java|go|rs))\b")
    for line in lines[:80]:
        for match in pattern.findall(line):
            if match not in mentions:
                mentions.append(match)
    return mentions[:8]


def _excerpt(lines: list[str], markers: tuple[str, ...], *, limit: int = 1200) -> str:
    focused = [line for line in lines if any(marker in line for marker in markers)]
    text = "\n".join(focused[:20])
    if len(text) > limit:
        return text[:limit].rstrip() + "\n[truncated]"
    return text


def _summary(lines: list[str], *, limit: int = 1600) -> str:
    focused = [
        line
        for line in lines
        if any(marker in line for marker in ("FAILED", "ERROR", "Traceback", "AssertionError", "ZeroDivisionError", "E       ", "assert "))
    ]
    selected = focused[:20] + [line for line in lines[:30] if line not in focused[:20]]
    text = "\n".join(selected[:40])
    if len(text) > limit:
        return text[:limit].rstrip() + "\n[truncated]"
    return text


def _hash_log(log: str) -> str:
    normalized = "\n".join(line.strip() for line in log.splitlines() if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
