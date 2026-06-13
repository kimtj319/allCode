"""Path classification helpers for model-authored project plans."""

from __future__ import annotations


def looks_like_planned_file_path(path: str, *, purpose: str = "") -> bool:
    """Reject command-like path fragments that are not credible file artifacts."""

    normalized = path.strip().replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return False
    basename = parts[-1]
    if "." in basename and not basename.endswith("."):
        return True
    if basename.lower() in _ALLOWED_EXTENSIONLESS_FILENAMES:
        return True
    if len(parts) > 1 and parts[-2].lower() in {"bin", "scripts"}:
        lowered_purpose = purpose.lower()
        executable_terms = ("executable", "entrypoint", "script", "실행", "진입점", "스크립트")
        return any(term in lowered_purpose for term in executable_terms)
    return False


_ALLOWED_EXTENSIONLESS_FILENAMES = frozenset(
    {
        "readme",
        "license",
        "copying",
        "notice",
        "makefile",
        "dockerfile",
        "procfile",
        "justfile",
        "rakefile",
        "gemfile",
    }
)
