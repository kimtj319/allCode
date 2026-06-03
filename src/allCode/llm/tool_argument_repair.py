"""Tolerant native tool argument repair helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Literal

RepairConfidence = Literal["high", "medium"]


@dataclass(frozen=True)
class ToolArgumentRepair:
    arguments: dict[str, Any]
    confidence: RepairConfidence
    reason: str


class ToolArgumentRepairer:
    """Repairs narrowly-scoped malformed native tool argument streams.

    The repairer never bypasses policy, approval, or path checks. It only
    reconstructs argument dictionaries when the target tool and required fields
    are unambiguous.
    """

    def repair(self, *, tool_name: str | None, text: str) -> ToolArgumentRepair | None:
        if not tool_name or not text.strip():
            return None
        if tool_name == "write_file":
            return self._repair_write_file(text)
        if tool_name == "patch_file":
            return self._repair_patch_file(text)
        if tool_name == "run_tests":
            return self._repair_run_tests(text)
        return None

    def normalize_valid_arguments(self, *, tool_name: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "run_tests":
            normalized = dict(arguments)
            if "command" not in normalized:
                for alias in ("cmd", "test_command", "validation_command"):
                    if alias in normalized:
                        normalized["command"] = normalized.pop(alias)
                        break
            if "cwd" not in normalized:
                for alias in ("path", "working_directory", "workdir"):
                    if alias in normalized:
                        normalized["cwd"] = normalized.pop(alias)
                        break
            return normalized
        if tool_name == "write_file":
            normalized = dict(arguments)
            if "file_path" not in normalized and "path" in normalized:
                normalized["file_path"] = normalized.pop("path")
            return normalized
        if tool_name == "patch_file":
            normalized = dict(arguments)
            if "file_path" not in normalized and "path" in normalized:
                normalized["file_path"] = normalized.pop("path")
            if "patches" not in normalized and "edits" in normalized:
                normalized["patches"] = normalized.pop("edits")
            if "patches" not in normalized and "patch" in normalized:
                patch = normalized.pop("patch")
                if isinstance(patch, dict):
                    normalized["patches"] = [patch]
            return normalized
        return arguments

    def _repair_write_file(self, text: str) -> ToolArgumentRepair | None:
        file_path = self._string_field(text, "file_path") or self._string_field(text, "path")
        content, content_confidence = self._content_field(text)
        if not file_path or content is None:
            return None
        repaired: dict[str, Any] = {"file_path": file_path, "content": content}
        for key in ("create_only", "overwrite"):
            value = self._bool_field(text, key)
            if value is not None:
                repaired[key] = value
        expected_hash = self._string_field(text, "expected_hash")
        if expected_hash:
            repaired["expected_hash"] = expected_hash
        return ToolArgumentRepair(
            arguments=repaired,
            confidence=content_confidence,
            reason="repaired malformed write_file arguments",
        )

    def _repair_patch_file(self, text: str) -> ToolArgumentRepair | None:
        file_path = self._string_field(text, "file_path") or self._string_field(text, "path")
        if not file_path:
            return None
        patches = self._patch_pairs(text)
        if not patches:
            return None
        return ToolArgumentRepair(
            arguments={"file_path": file_path, "patches": patches},
            confidence="medium",
            reason="repaired malformed patch_file arguments",
        )

    def _repair_run_tests(self, text: str) -> ToolArgumentRepair | None:
        command = (
            self._string_field(text, "command")
            or self._string_field(text, "cmd")
            or self._string_field(text, "test_command")
            or self._string_field(text, "validation_command")
        )
        cwd = (
            self._string_field(text, "cwd")
            or self._string_field(text, "path")
            or self._string_field(text, "working_directory")
            or self._string_field(text, "workdir")
        )
        timeout = self._int_field(text, "timeout_seconds")
        if not command and not cwd and timeout is None:
            stripped = text.strip()
            if stripped in {"{}", "{ }"}:
                return ToolArgumentRepair(arguments={}, confidence="high", reason="run_tests default command requested")
            return None
        repaired: dict[str, Any] = {}
        if command:
            repaired["command"] = command
        if cwd:
            repaired["cwd"] = cwd
        if timeout is not None:
            repaired["timeout_seconds"] = timeout
        return ToolArgumentRepair(
            arguments=repaired,
            confidence="high" if command else "medium",
            reason="repaired run_tests argument aliases",
        )

    def _content_field(self, text: str) -> tuple[str | None, RepairConfidence]:
        marker = re.search(r'"content"\s*:\s*"', text)
        if marker is None:
            return None, "medium"
        start = marker.end()
        end, confidence = self._field_string_end(text, start)
        if end is None:
            return None, "medium"
        return self._decode_lenient_string(text[start:end]), confidence

    def _field_string_end(self, text: str, start: int) -> tuple[int | None, RepairConfidence]:
        suffix_pattern = re.compile(
            r'"\s*,\s*"(?:create_only|overwrite|expected_hash|file_path|path)"\s*:',
            re.DOTALL,
        )
        suffix_match = suffix_pattern.search(text, start)
        if suffix_match is not None:
            return suffix_match.start(), "medium"
        for index in range(len(text) - 1, start - 1, -1):
            if text[index] != '"':
                continue
            suffix = text[index + 1 :].strip()
            if suffix in {"", "}", "}]", "},"} or suffix.startswith("}"):
                return index, "medium"
        return None, "medium"

    def _patch_pairs(self, text: str) -> list[dict[str, str]]:
        pair_pattern = re.compile(
            r'"(?:search|old)"\s*:\s*"(?P<search>(?:\\.|[^"\\])*)".*?'
            r'"(?:replace|new)"\s*:\s*"(?P<replace>(?:\\.|[^"\\])*)"',
            re.DOTALL,
        )
        patches: list[dict[str, str]] = []
        for match in pair_pattern.finditer(text):
            search = self._decode_lenient_string(match.group("search"))
            replace = self._decode_lenient_string(match.group("replace"))
            if search:
                patches.append({"search": search, "replace": replace})
        return patches

    def _string_field(self, text: str, key: str) -> str | None:
        pattern = rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"'
        match = re.search(pattern, text, re.DOTALL)
        if match is None:
            return None
        return self._decode_lenient_string(match.group(1))

    def _bool_field(self, text: str, key: str) -> bool | None:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*(true|false)', text, re.IGNORECASE)
        if match is None:
            return None
        return match.group(1).lower() == "true"

    def _int_field(self, text: str, key: str) -> int | None:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*(-?\d+)', text)
        if match is None:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _decode_lenient_string(value: str) -> str:
        try:
            return json.loads(f'"{value}"')
        except json.JSONDecodeError:
            return (
                value.replace(r"\"", '"')
                .replace(r"\\", "\\")
                .replace(r"\n", "\n")
                .replace(r"\t", "\t")
            )
