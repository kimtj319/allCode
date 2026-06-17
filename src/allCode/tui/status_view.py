"""Rendering helpers for the /status view: a token-usage gauge and a
multi-column metric layout. Pure string functions (no terminal/IO) so they are
easy to test."""

from __future__ import annotations

# Estimated tokens a heavy developer burns through a full day of agentic coding
# (large contexts × many turns). Used as the gauge's maximum; the bar fills with
# the day's actual usage. Tunable.
DAILY_TOKEN_BUDGET = 1_000_000


def fmt_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(int(value))


_fmt_tokens = fmt_tokens  # backwards-compatible alias


def gauge_fraction(used: int, maximum: int) -> float:
    """Clamped used/maximum ratio in [0, 1] for the token gauge."""
    return min(1.0, max(0, int(used)) / max(1, int(maximum)))


def render_token_gauge(used: int, maximum: int = DAILY_TOKEN_BUDGET, *, width: int = 28) -> str:
    used = max(0, int(used))
    maximum = max(1, int(maximum))
    ratio = min(1.0, used / maximum)
    filled = int(round(ratio * width))
    filled = min(width, max(0, filled))
    if used > 0 and filled == 0:
        filled = 1  # show a sliver once any tokens are spent
    bar = "█" * filled + "░" * (width - filled)
    return (
        "오늘 토큰 사용량 (하루 추정치 대비)\n"
        f"  [{bar}] {ratio * 100:.0f}%\n"
        f"  {_fmt_tokens(used)} / {_fmt_tokens(maximum)} 토큰"
    )


def format_metric_columns(pairs: list[tuple[str, str]], *, columns: int = 2, total_width: int = 100) -> str:
    """Lay out (label, value) metrics into `columns` columns, row-major."""
    if not pairs:
        return ""
    columns = max(1, columns)
    cell_width = max(20, total_width // columns)
    cells = [f"{label}: {value}" for label, value in pairs]
    rows: list[str] = []
    for start in range(0, len(cells), columns):
        chunk = cells[start : start + columns]
        line = "".join(_pad(cell, cell_width) for cell in chunk).rstrip()
        rows.append(line)
    return "\n".join(rows)


def _pad(cell: str, width: int) -> str:
    if len(cell) > width - 1:
        cell = cell[: width - 2] + "…"
    return cell.ljust(width)


def columns_for_width(width: int) -> int:
    """Pick 3 columns on wide terminals, 2 on medium, 1 on narrow."""
    if width >= 110:
        return 3
    if width >= 72:
        return 2
    return 1


def metric_pairs_from_summary(summary: str) -> list[tuple[str, str]]:
    """Parse a "- key: value" diagnostics summary into (key, value) pairs,
    skipping the title line."""
    pairs: list[tuple[str, str]] = []
    for line in summary.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or ": " not in stripped:
            continue
        key, _, value = stripped[2:].partition(": ")
        pairs.append((key.strip(), value.strip()))
    return pairs
