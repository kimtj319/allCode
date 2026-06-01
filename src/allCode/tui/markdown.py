"""Markdown presentation helpers for TUI transcript blocks."""

from __future__ import annotations

ROLE_TITLES = {
    "ALLCODE": "allCode",
    "TOOL": "Tool",
    "APPROVAL": "Approval",
    "ERROR": "Error",
    "STATUS": "Status",
}

KNOWN_ROLES = set(ROLE_TITLES) | {"USER"}

def logo_text(info: str = "") -> str:
    """Build a plain terminal header that reliably fits in a fixed TUI band."""

    parts = _parse_info(info)
    model = parts.get("model", "default")
    workspace = parts.get("workspace", ".")
    approval = parts.get("approval", "ask")
    return "\n".join(
        [
            "╭─────────────────────────────────────────────────────────╮",
            _boxed_line(">_ allCode"),
            _boxed_line(""),
            _boxed_line(f"model:     {model} · approval: {approval}"),
            _boxed_line(f"directory: {workspace}"),
            "╰─────────────────────────────────────────────────────────╯",
        ]
    )


def transcript_to_markdown(blocks: list[str]) -> str:
    """Convert role-prefixed transcript blocks to Markdown for display."""

    sections = [_block_to_markdown(block) for block in blocks if block.strip()]
    return "\n\n---\n\n".join(section for section in sections if section)


def _block_to_markdown(block: str) -> str:
    role, content = _split_block(block)
    title = ROLE_TITLES.get(role, role.title())
    if role == "USER":
        return _quote(content)
    if role == "TOOL":
        return f"**{title}**\n\n```text\n{content}\n```"
    if role == "ERROR":
        return f"**{title}**\n\n> {content}"
    if role in {"STATUS", "APPROVAL"}:
        return f"*{title}: {content}*"
    return f"**{title}**\n\n{content}"


def _split_block(block: str) -> tuple[str, str]:
    lines = block.strip("\n").splitlines()
    if not lines:
        return "STATUS", ""
    role = lines[0].strip().upper()
    if role not in KNOWN_ROLES:
        return "STATUS", block.strip()
    content = "\n".join(_strip_body_indent(line) for line in lines[1:]).strip()
    return role, content


def _strip_body_indent(line: str) -> str:
    return line[2:] if line.startswith("  ") else line


def _quote(content: str) -> str:
    if not content:
        return "> "
    return "\n".join(f"> {line}" if line else ">" for line in content.splitlines())


def _parse_info(info: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in info.split(" | "):
        key, separator, value = part.partition(":")
        if separator:
            parsed[key.strip().lower()] = value.strip()
    return parsed


def _boxed_line(content: str) -> str:
    width = 55
    text = content if len(content) <= width else content[: width - 1] + "…"
    return f"│ {text:<{width}} │"
