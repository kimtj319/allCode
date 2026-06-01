"""Project .env loading for allCode runtime configuration."""

from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path

ALLOWED_ENV_PREFIXES = ("ALLCODE_",)


def load_project_env(
    path: Path,
    environ: MutableMapping[str, str],
    *,
    override: bool = False,
) -> dict[str, str]:
    """Load allowed allCode variables from a dotenv file into environ."""

    values = parse_env_file(path)
    loaded: dict[str, str] = {}
    for key, value in values.items():
        if not key.startswith(ALLOWED_ENV_PREFIXES):
            continue
        if override or key not in environ:
            environ[key] = value
            loaded[key] = value
    return loaded


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for raw_line in lines:
        parsed = _parse_env_line(raw_line)
        if parsed is not None:
            key, value = parsed
            values[key] = value
    return values


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    if "=" not in line:
        return None
    key, raw_value = line.split("=", 1)
    key = key.strip()
    if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
        return None
    return key, _clean_value(raw_value.strip())


def _clean_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    return value
