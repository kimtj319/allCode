"""Tool observation cache and per-target budget controls."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from allCode.core.models import ToolCall, ToolResult


READ_OBSERVATION_TOOLS = {"read_file", "search_files", "list_directory"}
MUTATION_TOOLS = {"write_file", "patch_file", "delete_path"}
PATCH_FAILURE_TYPES = {"patch_ambiguous", "patch_not_found", "patch_invalid_request"}


@dataclass(frozen=True)
class ToolBudgetDecision:
    allowed: bool
    reason: str = ""
    count: int = 0


class ObservationCache:
    """Reuses repeated read/search observations without re-running tools."""

    def __init__(self, *, content_limit: int = 1600) -> None:
        self._entries: dict[str, ToolResult] = {}
        self._content_limit = content_limit

    def get(self, tool_call: ToolCall, *, workspace_root: str) -> ToolResult | None:
        if tool_call.name not in READ_OBSERVATION_TOOLS:
            return None
        key = self.key_for(tool_call, workspace_root=workspace_root)
        cached = self._entries.get(key)
        if cached is None:
            return None
        metadata = dict(cached.metadata)
        observation = metadata.get("observation")
        summary = ""
        if isinstance(observation, dict):
            summary = str(observation.get("summary") or observation.get("target") or "")
        content = self._compressed_content(cached, summary=summary)
        metadata.update(
            {
                "cached_observation": True,
                "cache_key": key,
                "original_call_id": cached.call_id,
            }
        )
        return cached.model_copy(
            update={
                "call_id": tool_call.id,
                "content": content,
                "metadata": metadata,
            }
        )

    def store(self, tool_call: ToolCall, result: ToolResult, *, workspace_root: str) -> None:
        if tool_call.name not in READ_OBSERVATION_TOOLS:
            return
        if not result.ok:
            return
        key = self.key_for(tool_call, workspace_root=workspace_root)
        metadata = dict(result.metadata)
        metadata["cache_key"] = key
        self._entries[key] = result.model_copy(update={"metadata": metadata})

    def invalidate_from_result(self, result: ToolResult) -> None:
        if result.name not in MUTATION_TOOLS or not result.ok:
            return
        touched = {
            str(path)
            for field in ("changed_files", "created_files", "deleted_files")
            for path in result.metadata.get(field, [])
        }
        if not touched:
            self._entries.clear()
            return
        for key, cached in list(self._entries.items()):
            file_path = str(cached.metadata.get("file_path") or "")
            if any(path in file_path or file_path in path for path in touched):
                self._entries.pop(key, None)

    def key_for(self, tool_call: ToolCall, *, workspace_root: str) -> str:
        payload = {
            "workspace": workspace_root,
            "tool": tool_call.name,
            "args": self._canonical_arguments(tool_call, workspace_root=workspace_root),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _compressed_content(self, result: ToolResult, *, summary: str) -> str:
        lines = [f"Reusing prior {result.name} observation."]
        if summary:
            lines.append(f"Summary: {summary}")
        detail = (result.content if result.ok else result.error or "").strip()
        if detail:
            if len(detail) > self._content_limit:
                detail = detail[: self._content_limit].rstrip() + "\n[reused observation truncated]"
            lines.append(detail)
        return "\n".join(lines)


    @staticmethod
    def _canonical_arguments(tool_call: ToolCall, *, workspace_root: str) -> dict[str, Any]:
        args = tool_call.arguments
        if tool_call.name == "read_file":
            keys = ("file_path", "start_line", "end_line", "max_bytes")
        elif tool_call.name == "search_files":
            keys = ("query", "path", "glob", "case_sensitive", "context_lines")
        elif tool_call.name == "list_directory":
            keys = ("path",)
        else:
            keys = tuple(sorted(args))
        canonical = {key: args.get(key) for key in keys if key in args}
        for key in ("file_path", "path"):
            value = canonical.get(key)
            if isinstance(value, str):
                canonical[key] = _normalize_path_argument(value, workspace_root=workspace_root)
        if isinstance(canonical.get("query"), str):
            canonical["query"] = " ".join(str(canonical["query"]).lower().split())
        return canonical


class ToolBudgetTracker:
    """Suppresses repeated target-level read/search attempts after cache miss."""

    def __init__(self, *, read_limit: int = 3, search_limit: int = 3) -> None:
        self._counts: dict[str, int] = {}
        self._read_limit = read_limit
        self._search_limit = search_limit
        self._turn_id: str | None = None

    def reset_for_turn(self, turn_id: str) -> None:
        if self._turn_id == turn_id:
            return
        self._turn_id = turn_id
        self._counts.clear()

    def check(self, tool_call: ToolCall, *, workspace_root: str) -> ToolBudgetDecision:
        if tool_call.name not in READ_OBSERVATION_TOOLS:
            return ToolBudgetDecision(allowed=True)
        key = self._budget_key(tool_call, workspace_root=workspace_root)
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        limit = self._search_limit if tool_call.name == "search_files" else self._read_limit
        if count <= limit:
            return ToolBudgetDecision(allowed=True, count=count)
        return ToolBudgetDecision(
            allowed=False,
            reason=f"tool budget exceeded for repeated {tool_call.name} target",
            count=count,
        )

    def reset_for_mutation_attempt(self, result: ToolResult) -> None:
        if result.name in MUTATION_TOOLS:
            self._counts.clear()

    def _budget_key(self, tool_call: ToolCall, *, workspace_root: str) -> str:
        args = tool_call.arguments
        if tool_call.name == "read_file":
            target = {
                "file_path": _normalize_path_argument(str(args.get("file_path") or ""), workspace_root=workspace_root),
                "start_line": args.get("start_line"),
                "end_line": args.get("end_line"),
                "max_bytes": args.get("max_bytes"),
            }
        elif tool_call.name == "list_directory":
            target = {
                "path": _normalize_path_argument(str(args.get("path") or "."), workspace_root=workspace_root),
            }
        elif tool_call.name == "search_files":
            target = {
                "query": " ".join(str(args.get("query") or "").lower().split()),
                "path": _normalize_path_argument(str(args.get("path") or "."), workspace_root=workspace_root),
                "glob": args.get("glob"),
                "case_sensitive": args.get("case_sensitive"),
                "context_lines": args.get("context_lines"),
            }
        else:
            target = dict(sorted(args.items()))
        payload = {"workspace": workspace_root, "turn": self._turn_id, "tool": tool_call.name, "target": target}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class PatchFailureTracker:
    """Tracks failed patch search blocks and recommends a strategy switch."""

    def __init__(self) -> None:
        self._failures: dict[str, int] = {}
        self._failure_files: dict[str, str] = {}
        self._ambiguous_files: set[str] = set()
        self._turn_id: str | None = None

    def reset_for_turn(self, turn_id: str) -> None:
        if self._turn_id == turn_id:
            return
        self._turn_id = turn_id
        self._failures.clear()
        self._failure_files.clear()
        self._ambiguous_files.clear()

    def repeated_failure(self, tool_call: ToolCall, *, workspace_root: str) -> ToolResult | None:
        if tool_call.name != "patch_file":
            return None
        file_path = _normalize_path_argument(str(tool_call.arguments.get("file_path") or ""), workspace_root=workspace_root)
        if file_path in self._ambiguous_files:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                ok=False,
                error=(
                    "Patch search was ambiguous for this file. Read the target range first, "
                    "then use write_file or a narrower patch."
                ),
                error_type="patch_strategy_required",
                metadata={
                    "patch_strategy_required": True,
                    "file_path": file_path,
                    "recommended_next_tools": ["read_file", "write_file"],
                    "must_not_repeat_same_patch": True,
                    "observation": {
                        "kind": "patch_strategy",
                        "target": file_path,
                        "summary": "Ambiguous patch state is active for this file; switch to ranged read or full-file rewrite.",
                        "risk": "low",
                    },
                },
            )
        key = self._key(tool_call, workspace_root=workspace_root)
        count = self._failures.get(key, 0)
        if count <= 0:
            return None
        return ToolResult(
            call_id=tool_call.id,
            name=tool_call.name,
            ok=False,
            error="Repeated patch search failed previously; switch strategy before retrying the same patch.",
            error_type="patch_strategy_required",
            metadata={
                "patch_strategy_required": True,
                "repeat_count": count + 1,
                "recommended_next_tools": ["read_file", "write_file"],
                "must_not_repeat_same_patch": True,
                "observation": {
                    "kind": "patch_strategy",
                    "target": str(tool_call.arguments.get("file_path") or ""),
                    "summary": "Use a ranged read to inspect the exact block, then issue a narrower patch or rewrite the full file.",
                    "risk": "low",
                },
            },
        )

    def record_result(self, tool_call: ToolCall, result: ToolResult, *, workspace_root: str) -> None:
        file_path = _normalize_path_argument(str(tool_call.arguments.get("file_path") or ""), workspace_root=workspace_root)
        if tool_call.name in {"write_file", "patch_file"} and result.ok:
            if file_path:
                self._ambiguous_files.discard(file_path)
                for failure_key, failure_file in list(self._failure_files.items()):
                    if failure_file == file_path:
                        self._failures.pop(failure_key, None)
                        self._failure_files.pop(failure_key, None)
            if tool_call.name == "patch_file":
                self._failures.pop(self._key(tool_call, workspace_root=workspace_root), None)
            return
        if tool_call.name != "patch_file":
            return
        key = self._key(tool_call, workspace_root=workspace_root)
        if result.error_type in PATCH_FAILURE_TYPES:
            self._failures[key] = self._failures.get(key, 0) + 1
            self._failure_files[key] = file_path
        if result.error_type == "patch_ambiguous" and file_path:
            self._ambiguous_files.add(file_path)

    def _key(self, tool_call: ToolCall, *, workspace_root: str) -> str:
        args = tool_call.arguments
        payload = {
            "workspace": workspace_root,
            "file_path": _normalize_path_argument(str(args.get("file_path") or ""), workspace_root=workspace_root),
            "search_hash": self._patch_search_hash(args.get("patches")),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _patch_search_hash(patches: Any) -> str:
        searches: list[str] = []
        if isinstance(patches, list):
            for patch in patches:
                if isinstance(patch, dict):
                    searches.append(str(patch.get("search") or ""))
        encoded = json.dumps(searches, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def suppressed_tool_result(tool_call: ToolCall, *, reason: str, count: int) -> ToolResult:
    return ToolResult(
        call_id=tool_call.id,
        name=tool_call.name,
        ok=False,
        error=reason,
        error_type="tool_budget_exceeded",
        metadata={
            "tool_budget_exceeded": True,
            "repeat_count": count,
            "recommended_next_action": "reuse prior observations or inspect a narrower range before retrying",
            "existing_observation_available": True,
            "allowed_range_read_hint": tool_call.name == "read_file",
            "observation": {
                "kind": "budget",
                "target": str(tool_call.arguments.get("file_path") or tool_call.arguments.get("path") or tool_call.arguments.get("query") or ""),
                "summary": reason,
                "risk": "low",
            },
        },
    )


def _normalize_path_argument(value: str, *, workspace_root: str) -> str:
    stripped = value.strip() or "."
    if stripped.startswith("/workspace/"):
        return stripped[len("/workspace/") :]
    if stripped == "/workspace":
        return "."
    candidate = Path(stripped)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(Path(workspace_root).resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.as_posix()
