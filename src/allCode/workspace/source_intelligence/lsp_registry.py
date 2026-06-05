"""Language server discovery helpers for optional LSP enrichment."""

from __future__ import annotations

from pathlib import Path
import shutil


DEFAULT_LSP_COMMANDS: dict[str, list[str]] = {
    "python": ["pyright-langserver", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "go": ["gopls"],
    "rust": ["rust-analyzer"],
    "java": ["jdtls"],
}


def language_for_path(path: str | Path) -> str:
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
    }.get(Path(path).suffix.lower(), "")


def discover_lsp_command(language: str, configured: dict[str, list[str]] | None = None) -> list[str]:
    command = (configured or {}).get(language) or DEFAULT_LSP_COMMANDS.get(language, [])
    if not command:
        return []
    executable = shutil.which(command[0])
    if executable is None:
        return []
    return [executable, *command[1:]]
