"""Command line entrypoint for allCode."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from allCode.config.manager import ConfigError, ConfigManager, ConfigOverrides
from allCode.config.schema import ConfigSourceReport
from allCode.config.defaults import DEFAULT_CONFIG_DIR
from allCode.headless import run_headless_sync
from allCode.llm.factory import uses_live_llm
from allCode.agent.context_factory import build_runtime_context_builder
from allCode.memory.commands import MemoryCommandService
from allCode.memory.inbox import MemoryInbox
from allCode.memory.session_store import SessionStore
from allCode.memory.store import MemoryStore
from allCode.runtime import make_tui_turn_runner, runtime_tool_registry
from allCode.telemetry import AgentSessionLogger
from allCode.tui.runtime import run_interactive_session
from allCode.tui.slash_commands import SlashCommandHandler
from allCode.tui.status_commands import RuntimeStatusCommandService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="allcode")
    parser.add_argument("--headless", nargs="?", const="", metavar="PROMPT")
    parser.add_argument("--workspace")
    parser.add_argument("--config")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--approval", choices=["ask", "auto", "rules"])
    parser.add_argument(
        "--diagnose",
        "--check",
        action="store_true",
        dest="diagnose",
        help="Print redacted runtime configuration diagnostics and exit.",
    )
    parser.add_argument("--textual", action="store_true", help="Use the optional Textual TUI instead of the Codex-like terminal UI.")
    parser.add_argument("--plain-terminal", action="store_true", help="Compatibility alias for the default terminal-native UI.")
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
        load_result = ConfigManager().load_with_report(
            ConfigOverrides(
                config_path=args.config,
                workspace=args.workspace,
                model=args.model,
                base_url=args.base_url,
                approval=args.approval,
            )
        )
        config = load_result.config
        if args.diagnose:
            _write_diagnostics(load_result.report, stdout)
            return 0
        if args.headless is not None:
            prompt = args.headless or sys.stdin.read()
            return run_headless_sync(prompt, config=config, out=stdout, err=stderr)
        if out is None and err is None:
            _validate_interactive_model_config(config)
            context_builder = build_runtime_context_builder(config)
            session_logger = AgentSessionLogger.create(config=config)
            return run_interactive_session(
                turn_runner=make_tui_turn_runner(
                    config=config,
                    context_builder=context_builder,
                    session_logger=session_logger,
                ),
                app_info=_tui_app_info(config),
                slash_handler=_slash_handler(config, session_log_path=session_logger.path),
                stdin=sys.stdin,
                stdout=stdout,
                stderr=stderr,
                cwd=Path(config.workspace.root).expanduser().resolve(),
                plain_terminal=args.plain_terminal,
                textual=args.textual,
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


def _write_diagnostics(report: ConfigSourceReport, out: TextIO) -> None:
    out.write("allCode configuration diagnostics\n")
    out.write(f"- workspace: {report.workspace_root}\n")
    out.write(f"- model: {report.model_name}\n")
    out.write(f"- base_url: {report.base_url or 'default'}\n")
    out.write(f"- api_key_env: {report.api_key_env} ({'set' if report.api_key_present else 'not set'})\n")
    out.write(f"- approval: {report.approval_mode}\n")
    out.write(f"- web: {report.web_backend}")
    if report.web_search_host:
        out.write(f" · {report.web_search_host}")
    out.write("\n")
    out.write("- config files:\n")
    for source in report.config_files:
        status = "loaded" if source.loaded else "missing"
        suffix = " · launch fallback" if source.source_type == "launch" and report.launch_config_fallback_used else ""
        out.write(f"  - {source.source_type}: {source.path} ({status}{suffix})\n")
    if report.dotenv_files:
        out.write("- dotenv files:\n")
        for source in report.dotenv_files:
            keys = ", ".join(source.loaded_keys) if source.loaded_keys else "no new ALLCODE_ keys"
            out.write(f"  - {source.path}: {keys}\n")
    if report.env_overrides:
        out.write("- env override groups: " + ", ".join(report.env_overrides) + "\n")
    if report.cli_overrides:
        out.write("- cli overrides: " + ", ".join(report.cli_overrides) + "\n")


def _slash_handler(config, *, session_log_path: Path | None = None) -> SlashCommandHandler:
    project_root = Path(config.workspace.root).expanduser().resolve()
    store = MemoryStore(project_root, DEFAULT_CONFIG_DIR)
    inbox = MemoryInbox(project_root / ".allCode" / "memory" / "inbox", store)
    tools = runtime_tool_registry(config)
    service = MemoryCommandService(
        store=store,
        inbox=inbox,
        session_store=SessionStore(project_root),
        cwd=project_root,
    )
    return SlashCommandHandler(
        memory_backend=service,
        status_backend=RuntimeStatusCommandService(config=config, tools=tools, session_log_path=session_log_path),
        workspace_root=str(project_root),
    )
