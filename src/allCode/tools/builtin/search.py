"""Builtin workspace search tool."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_ops import resolve_under_root

IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", "build", "target", "__pycache__"}


class SearchFilesTool:
    definition = ToolDefinition(
        name="search_files",
        description="Search UTF-8 workspace files for a literal query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "max_results": {"type": "integer"},
                "context_lines": {"type": "integer"},
                "glob": {"type": "string"},
                "case_sensitive": {"type": "boolean"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        read_only=True,
        group="search",
        aliases=["rg"],
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            query = str(call.arguments["query"])
            max_results = int(call.arguments.get("max_results", 50))
            root = resolve_under_root(context.workspace.root, str(call.arguments.get("path", ".")))
            if not query.strip():
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    error="search_files requires a non-empty query.",
                    error_type="invalid_query",
                    metadata={
                        "invalid_query": True,
                        "query": query,
                        "required_next_action": (
                            "Use glob_files, list_tree, or source_overview for file inventory, "
                            "or provide a non-empty literal search query."
                        ),
                        "observation": {
                            "kind": "search_invalid",
                            "target": str(root),
                            "summary": "search_files requires a non-empty query",
                            "risk": "low",
                        },
                    },
                )
            if root.is_file():
                rg_result = None
            else:
                rg_result = self._run_rg(query, root, call.arguments, max_results)
            if rg_result:
                return self._result(call, rg_result)
            if rg_result == [] and not root.is_file():
                return self._result(call, rg_result)
            rows: list[dict[str, object]] = []
            for path in self._iter_files(root):
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if query in line:
                        rows.append({"path": str(path), "line": line_number, "preview": line})
                        if len(rows) >= max_results:
                            return self._result(call, rows)
            return self._result(call, rows)
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

    def _iter_files(self, root: Path):
        if root.is_file():
            yield root
            return
        for path in root.rglob("*"):
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            if path.is_file():
                yield path

    def _run_rg(self, query: str, root: Path, arguments: dict, max_results: int) -> list[dict[str, object]] | None:
        rg = shutil.which("rg")
        if rg is None:
            return None
        command = [rg, "--line-number", "--color", "never", "--no-ignore", "--max-count", str(max_results)]
        context_lines = int(arguments.get("context_lines", 0))
        if context_lines > 0:
            command.extend(["--context", str(min(context_lines, 5))])
        if not bool(arguments.get("case_sensitive", True)):
            command.append("--ignore-case")
        glob = arguments.get("glob")
        if isinstance(glob, str) and glob.strip():
            command.extend(["--glob", glob.strip()])
        for ignored in sorted(IGNORED_DIRS):
            command.extend(["--glob", f"!{ignored}/**"])
        command.extend([query, str(root)])
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode not in {0, 1}:
            return None
        rows: list[dict[str, object]] = []
        for line in completed.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            path, line_no, preview = parts
            try:
                parsed_line = int(line_no)
            except ValueError:
                continue
            rows.append({"path": path, "line": parsed_line, "preview": preview})
            if len(rows) >= max_results:
                break
        return rows

    def _result(self, call: ToolCall, rows: list[dict[str, object]]) -> ToolResult:
        query = str(call.arguments.get("query", ""))
        search_path = str(call.arguments.get("path", "."))
        symbol_like = _symbol_like_tokens(query)
        ranked_rows = self._annotate_rows(rows, symbol_like)
        content = "\n".join(f"{row['path']}:{row['line']}: {row['preview']}" for row in rows)
        if not content:
            content = f"No matches found for query {query!r} under {search_path!r}. 검색 결과 없음."
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=content,
            metadata={
                "query": query,
                "evidence_count": len(rows),
                "matches": ranked_rows,
                "symbol_like_tokens": symbol_like,
                "repo_map_rank_hint": bool(symbol_like),
                "observation": {
                    "kind": "search",
                    "target": search_path,
                    "summary": f"Found {len(rows)} match(es) for {query!r}",
                    "risk": "low",
                },
            },
        )

    def _annotate_rows(self, rows: list[dict[str, object]], symbol_like: list[str]) -> list[dict[str, object]]:
        annotated: list[dict[str, object]] = []
        lowered_symbols = [token.lower() for token in symbol_like]
        for row in rows:
            preview = str(row.get("preview", "")).lower()
            path = str(row.get("path", "")).lower()
            symbol_hit = any(token in preview or token in path for token in lowered_symbols)
            ranked = dict(row)
            ranked["symbol_hit"] = symbol_hit
            ranked["rank_reason"] = "symbol_or_path_match" if symbol_hit else "literal_match"
            annotated.append(ranked)
        return sorted(annotated, key=lambda item: 0 if item.get("symbol_hit") else 1)


def _symbol_like_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for raw in query.replace("(", " ").replace(")", " ").replace(".", " ").split():
        token = raw.strip("_:-")
        if len(token) < 3:
            continue
        if "_" in token or any(char.isupper() for char in token[1:]) or token.endswith(("Manager", "Service", "Controller")):
            tokens.append(token)
    return tokens[:8]
