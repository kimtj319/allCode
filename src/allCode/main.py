"""Command line entrypoint for allCode."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from allCode.config.manager import ConfigError, ConfigManager, ConfigOverrides
from allCode.config.defaults import DEFAULT_CONFIG_DIR
from allCode.headless import run_headless_sync
from allCode.llm.factory import uses_live_llm
from allCode.memory.commands import MemoryCommandService
from allCode.memory.inbox import MemoryInbox
from allCode.memory.session_store import SessionStore
from allCode.memory.store import MemoryStore
from allCode.runtime import make_tui_turn_runner
from allCode.tui.runtime import run_interactive_session
from allCode.tui.slash_commands import SlashCommandHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="allcode")
    parser.add_argument("--headless", nargs="?", const="", metavar="PROMPT")
    parser.add_argument("--workspace")
    parser.add_argument("--config")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--approval", choices=["ask", "auto", "rules"])
    parser.add_argument("--plain-terminal", action="store_true", help="Use the raw terminal fallback instead of the Textual TUI.")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    stdout = out or sys.stdout
    stderr = err or sys.stderr
    parser = build_parser()

    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        config = ConfigManager().load(
            ConfigOverrides(
                config_path=args.config,
                workspace=args.workspace,
                model=args.model,
                base_url=args.base_url,
                approval=args.approval,
            )
        )
        if args.headless is not None:
            prompt = args.headless or sys.stdin.read()
            return run_headless_sync(prompt, config=config, out=stdout, err=stderr)
        if out is None and err is None:
            _validate_interactive_model_config(config)
            return run_interactive_session(
                turn_runner=make_tui_turn_runner(config=config),
                app_info=_tui_app_info(config),
                slash_handler=_slash_handler(config),
                stdin=sys.stdin,
                stdout=stdout,
                stderr=stderr,
                cwd=Path(config.workspace.root).expanduser().resolve(),
                plain_terminal=args.plain_terminal,
            )
        stdout.write("allCode interactive UI requires a real TTY. Use allcode --headless for captured runs.\n")
        return 0
    except ConfigError as exc:
        stderr.write(f"Configuration error: {exc}\n")
        return 2
    except KeyboardInterrupt:
        stderr.write("Interrupted.\n")
        return 130


def _tui_app_info(config) -> str:
    workspace = Path(config.workspace.root).expanduser().resolve().name or str(config.workspace.root)
    return f"model: {config.model.model_name} | workspace: {workspace} | approval: {config.approval.mode}"


def _validate_interactive_model_config(config) -> None:
    if uses_live_llm(config) and not os.environ.get(config.model.api_key_env):
        raise ConfigError(
            "Model API key is not configured. "
            f"Set {config.model.api_key_env} or add it to the project .env before running allCode."
        )


def _slash_handler(config) -> SlashCommandHandler:
    project_root = Path(config.workspace.root).expanduser().resolve()
    store = MemoryStore(project_root, DEFAULT_CONFIG_DIR)
    inbox = MemoryInbox(project_root / ".allCode" / "memory" / "inbox", store)
    service = MemoryCommandService(
        store=store,
        inbox=inbox,
        session_store=SessionStore(project_root),
        cwd=project_root,
    )
    return SlashCommandHandler(memory_backend=service)
