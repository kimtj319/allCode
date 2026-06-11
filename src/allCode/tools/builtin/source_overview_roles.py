"""Package role inference helpers for source overview metadata."""

from __future__ import annotations

import re
from pathlib import Path

ARCHITECTURE_FILE_STEMS = {
    "__init__",
    "__main__",
    "main",
    "cli",
    "app",
    "runtime",
    "loop",
    "runner",
    "router",
    "workflow",
    "registry",
    "executor",
    "manager",
    "service",
    "client",
    "parser",
    "schema",
    "models",
    "events",
    "indexer",
    "store",
}


def package_roles(groups: list[dict[str, object]]) -> list[dict[str, object]]:
    roles: list[dict[str, object]] = []
    for group in groups[:12]:
        definitions = group.get("definitions") if isinstance(group.get("definitions"), list) else []
        imports = group.get("imports") if isinstance(group.get("imports"), list) else []
        path = str(group.get("path") or "")
        file_count = int(group.get("file_count") or 0)
        role, confidence = infer_role(path, definitions, imports, file_count=file_count)
        roles.append({"path": path, "role": role, "confidence": confidence})
    return roles


def infer_role(path: str, definitions: list, imports: list, *, file_count: int) -> tuple[str, float]:
    path_tokens = _path_tokens(path)
    filenames = _definition_filenames(definitions)
    symbol_names = " ".join(_definition_symbol_name(item).lower() for item in definitions[:12])
    if path_tokens & {"tests", "test", "spec", "specs"} or any(_looks_test_filename(name) for name in filenames):
        return "test or verification support", 0.7
    keyword_role = _role_from_path_keywords(path_tokens)
    if keyword_role is not None:
        return keyword_role
    if any(name in filenames for name in ("main.py", "__main__.py", "cli.py")):
        return "entrypoint or command/runtime wiring", 0.75
    if any(token in symbol_names for token in ("command", "runtime", "runner", "application")):
        return "runtime orchestration or command wiring", 0.7
    if definitions and imports:
        return "public code surface coordinating imported dependencies", 0.68
    if definitions:
        return "source module defining public classes or functions", 0.62
    if imports:
        return "integration or dependency wiring module", 0.58
    if file_count > 1:
        return "source package group", 0.5
    return "source file group", 0.45


def role_evidence(groups: list[dict[str, object]]) -> list[str]:
    evidence: list[str] = []
    for group in groups[:12]:
        path = str(group.get("path") or "")
        definitions = group.get("definitions") if isinstance(group.get("definitions"), list) else []
        imports = group.get("imports") if isinstance(group.get("imports"), list) else []
        if definitions:
            evidence.append(f"{path}: definitions: {', '.join(str(item) for item in definitions[:3])}")
        elif imports:
            evidence.append(f"{path}: imports: {', '.join(str(item) for item in imports[:3])}")
        elif path:
            evidence.append(f"{path}: file_count={group.get('file_count')}")
    return evidence[:12]


def _path_tokens(path: str) -> set[str]:
    tokens: set[str] = set()
    for part in Path(path).parts:
        tokens.update(token for token in re.split(r"[^A-Za-z0-9]+", part.lower()) if token)
    return tokens


def _definition_filenames(definitions: list) -> set[str]:
    filenames: set[str] = set()
    for item in definitions:
        text = str(item)
        if ":" not in text:
            continue
        filenames.add(Path(text.split(":", 1)[0]).name.lower())
    return filenames


def _definition_symbol_name(definition: object) -> str:
    text = str(definition)
    tail = text.split(":", 1)[-1].strip()
    for marker in ("async def ", "def ", "class ", "function ", "const ", "let ", "var "):
        if marker in tail:
            tail = tail.split(marker, 1)[1]
            break
    return tail.split("(", 1)[0].split("=", 1)[0].strip()


def _looks_test_filename(filename: str) -> bool:
    return filename.startswith("test_") or filename.endswith("_test.py") or filename.endswith(".spec.ts")


def _role_from_path_keywords(tokens: set[str]) -> tuple[str, float] | None:
    if "agent" in tokens or "agents" in tokens:
        return "agent loop, routing, planning, and completion orchestration", 0.82
    if "tool" in tokens or "tools" in tokens:
        return "tool registry, policy, approval, and builtin tool execution", 0.82
    if "memory" in tokens or "context" in tokens:
        return "workspace context, session memory, and repo map state", 0.8
    if "llm" in tokens or "model" in tokens or "models" in tokens:
        return "provider-neutral model adapter, streaming, and response parsing", 0.8
    if "core" in tokens or "common" in tokens:
        return "shared provider-neutral contracts, events, errors, and results", 0.78
    if "config" in tokens or "settings" in tokens:
        return "configuration schema, defaults, and environment loading", 0.78
    if "tui" in tokens or "ui" in tokens or "terminal" in tokens:
        return "terminal UI rendering, input handling, and status presentation", 0.78
    if "workspace" in tokens or "project" in tokens:
        return "workspace roots, indexing, path policy, and source intelligence", 0.78
    if "generation" in tokens or "workflow" in tokens:
        return "project generation workflow and language strategies", 0.76
    if "telemetry" in tokens or "logging" in tokens:
        return "session logging, runtime metrics, and diagnostics", 0.76
    return None

