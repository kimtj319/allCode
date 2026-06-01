"""Command line entrypoint for allCode."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from allCode.config.manager import ConfigError, ConfigManager, ConfigOverrides
from allCode.config.defaults import DEFAULT_CONFIG_DIR
from allCode.headless import run_headless_sync
from allCode.memory.commands import MemoryCommandService
from allCode.memory.inbox import MemoryInbox
from allCode.memory.session_store import SessionStore
from allCode.memory.store import MemoryStore
from allCode.runtime import make_tui_turn_runner
from allCode.tui.app import TEXTUAL_AVAILABLE, create_app
from allCode.tui.slash_commands import SlashCommandHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ac")
    parser.add_argument("--headless", nargs="?", const="", metavar="PROMPT")
    parser.add_argument("--workspace")
    parser.add_argument("--config")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--approval", choices=["ask", "auto", "rules"])
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
        if TEXTUAL_AVAILABLE and out is None and err is None:
            create_app(
                turn_runner=make_tui_turn_runner(config=config),
                app_info=_tui_app_info(config),
                slash_handler=_slash_handler(config),
            ).run()
            return 0
        stdout.write("allCode TUI requires Textual in this environment. Use ac --headless.\n")
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
