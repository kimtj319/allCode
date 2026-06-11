"""Validation log parsing and failure-summary construction."""

from __future__ import annotations

import hashlib
import re

from pydantic import Field

from allCode.core.models import CoreModel, ToolResult
from allCode.core.result import RepairTarget


class ValidationFailureSummary(CoreModel):
    failure_type: str = "unknown"
    command: str = ""
    returncode: int | None = None
    failed_files: list[str] = Field(default_factory=list)
    failing_symbols: list[str] = Field(default_factory=list)
    public_api_expectations: list[str] = Field(default_factory=list)
    failing_targets: list[RepairTarget] = Field(default_factory=list)
    traceback_excerpt: str = ""
    assertion_excerpt: str = ""
    suggested_read_targets: list[str] = Field(default_factory=list)
    recommended_tools: list[str] = Field(default_factory=list)
    must_not_repeat: list[str] = Field(default_factory=list)
    error_hash: str = ""
    summary: str = ""


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
    api_expectations = _extract_public_api_expectations(lines)
    failing_targets = _extract_repair_targets(lines)
    if not failing_targets:
        failing_targets = [
            RepairTarget(file_path=path, reason="pytest_failed_file")
            for path in failed_files[:3]
        ]
    failure_type = _classify_failure(lines)
    traceback_excerpt = _excerpt(lines, ("Traceback", "ZeroDivisionError", "Exception", "Error"))
    assertion_excerpt = _excerpt(lines, ("AssertionError", "E       ", "assert ", "FAILED"))
    suggested = sorted(set(failed_files + _path_like_mentions(lines) + _missing_module_paths(lines)))[:8]
    summary = _summary(lines)
    return ValidationFailureSummary(
        failure_type=failure_type,
        command=command,
        returncode=returncode if isinstance(returncode, int) else None,
        failed_files=failed_files,
        failing_symbols=failing_symbols,
        public_api_expectations=api_expectations,
        failing_targets=failing_targets,
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


def _extract_repair_targets(lines: list[str]) -> list[RepairTarget]:
    targets: list[RepairTarget] = []

    traceback_pattern = re.compile(
        r'File\s+"(?P<path>[^"]+\.(?:py|js|ts|tsx|java|go|rs))",\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<symbol>[A-Za-z_][A-Za-z0-9_]*))?'
    )
    path_line_pattern = re.compile(
        r"\b(?P<path>[A-Za-z0-9_./\\-]+\.(?:py|js|jsx|ts|tsx|java|go|rs)):(?P<line>\d+)(?::\d+)?"
    )
    pytest_failed_pattern = re.compile(
        r"\bFAILED\s+(?P<path>[A-Za-z0-9_./\\-]+\.(?:py|js|jsx|ts|tsx|java|go|rs))(?:[:]{2}(?P<symbol>[A-Za-z_][A-Za-z0-9_]*))?"
    )
    missing_module_pattern = re.compile(
        r"(?:No module named|ModuleNotFoundError:\s*No module named)\s+['\"](?P<module>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)['\"]"
    )

    for line in lines[:160]:
        for match in traceback_pattern.finditer(line):
            _add_repair_target(
                targets,
                file_path=match.group("path"),
                line_number=_safe_int(match.group("line")),
                symbol=match.group("symbol") or "",
                reason="traceback",
            )
        for match in path_line_pattern.finditer(line):
            _add_repair_target(
                targets,
                file_path=match.group("path"),
                line_number=_safe_int(match.group("line")),
                reason="path_line",
            )
        for match in pytest_failed_pattern.finditer(line):
            symbol = match.group("symbol") or ""
            _add_repair_target(
                targets,
                file_path=match.group("path"),
                symbol=symbol,
                reason="pytest_failed_item" if symbol else "pytest_failed_file",
            )
        for match in missing_module_pattern.finditer(line):
            _add_repair_target(
                targets,
                file_path=_module_to_path(match.group("module")),
                reason="missing_module",
            )
    return targets[:8]


def _add_repair_target(
    targets: list[RepairTarget],
    *,
    file_path: str,
    line_number: int | None = None,
    symbol: str = "",
    reason: str = "",
) -> None:
    normalized = file_path.replace("\\", "/").strip()
    if not normalized:
        return
    key = (normalized, line_number, symbol)
    if any((target.file_path, target.line_number, target.symbol) == key for target in targets):
        return
    targets.append(
        RepairTarget(
            file_path=normalized,
            line_number=line_number,
            symbol=symbol,
            reason=reason,
        )
    )


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _extract_failing_symbols(lines: list[str]) -> list[str]:
    symbols: list[str] = []
    pattern = re.compile(r"\b(test_[A-Za-z0-9_]+|[A-Za-z_][A-Za-z0-9_]*Error)\b")
    for line in lines:
        for match in pattern.findall(line):
            if match not in symbols:
                symbols.append(match)
    return symbols[:10]


def _extract_public_api_expectations(lines: list[str]) -> list[str]:
    expectations: list[str] = []
    patterns = (
        (
            re.compile(
                r"(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\(\)\s+got an unexpected keyword argument ['\"](?P<arg>[A-Za-z_][A-Za-z0-9_]*)['\"]"
            ),
            lambda match: f"accept keyword argument {match.group('arg')} in {match.group('name')}",
        ),
        (
            re.compile(
                r"(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\(\)\s+missing\s+\d+\s+required positional argument[s]?:\s+(?P<args>.+)"
            ),
            lambda match: f"accept required positional argument(s) {match.group('args')} in {match.group('name')}",
        ),
        (
            re.compile(
                r"cannot import name ['\"](?P<name>[A-Za-z_][A-Za-z0-9_]*)['\"] from ['\"](?P<module>[^'\"]+)['\"]"
            ),
            lambda match: f"export {match.group('name')} from {match.group('module')}",
        ),
        (
            re.compile(
                r"has no attribute ['\"](?P<name>[A-Za-z_][A-Za-z0-9_]*)['\"]"
            ),
            lambda match: f"provide attribute or method {match.group('name')}",
        ),
    )
    for line in lines[:160]:
        for pattern, formatter in patterns:
            for match in pattern.finditer(line):
                value = formatter(match).strip()
                if value and value not in expectations:
                    expectations.append(value)
    return expectations[:8]


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


def _missing_module_paths(lines: list[str]) -> list[str]:
    paths: list[str] = []
    pattern = re.compile(r"No module named ['\"](?P<module>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)['\"]")
    for line in lines[:120]:
        for match in pattern.finditer(line):
            path = _module_to_path(match.group("module"))
            if path and path not in paths:
                paths.append(path)
    return paths[:8]


def _module_to_path(module: str) -> str:
    parts = [part for part in module.split(".") if part]
    if len(parts) < 2:
        return ""
    return "/".join(parts) + ".py"


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
