"""Headless runner for non-TUI execution.

Supports three output formats for scripting/CI use, mirroring Codex/Claude
Code's ``exec`` modes:

- ``text`` (default): the final answer on stdout, errors on stderr.
- ``json``: a single JSON object with the final answer, status, changed files
  and token usage — for piping into other tools.
- ``stream-json``: one JSON object per line; each agent event as it happens,
  then a terminating ``{"type": "result", ...}`` line.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TextIO

from allCode.config.schema import AppConfig
from allCode.core.events import AgentEvent
from allCode.core.result import TurnResult
from allCode.runtime import run_agent_turn
from allCode.tools.registry import ToolRegistry

OutputFormat = str  # "text" | "json" | "stream-json"


async def run_headless(
    prompt: str,
    *,
    config: AppConfig,
    llm_client=None,
    tools: ToolRegistry | None = None,
    event_handler=None,
    images: list[str] | None = None,
) -> TurnResult:
    return await run_agent_turn(
        prompt,
        config=config,
        llm_client=llm_client,
        tools=tools,
        event_handler=event_handler,
        images=images,
    )


def _result_payload(result: TurnResult) -> dict:
    return {
        "type": "result",
        "turn_id": result.turn_id,
        "status": result.status,
        "final_answer": result.final_answer,
        "created_files": result.created_files,
        "modified_files": result.modified_files,
        "deleted_files": result.deleted_files,
        "validation_passed": result.validation_passed,
        "token_usage": result.token_usage.model_dump(mode="json"),
        "error_message": result.error_message,
    }


def _event_payload(event: AgentEvent) -> dict:
    return {
        "type": "event",
        "event_type": event.event_type,
        "message": getattr(event, "message", ""),
        "data": getattr(event, "data", None),
    }


def run_headless_sync(
    prompt: str,
    *,
    config: AppConfig,
    out: TextIO | None = None,
    err: TextIO | None = None,
    llm_client=None,
    tools: ToolRegistry | None = None,
    output_format: OutputFormat = "text",
    images: list[str] | None = None,
) -> int:
    stdout = out or sys.stdout
    stderr = err or sys.stderr

    stream = output_format == "stream-json"
    event_handler = None
    if stream:
        async def _emit(event: AgentEvent) -> None:
            stdout.write(json.dumps(_event_payload(event), ensure_ascii=False) + "\n")
            stdout.flush()

        event_handler = _emit

    try:
        result = asyncio.run(
            run_headless(
                prompt,
                config=config,
                llm_client=llm_client,
                tools=tools,
                event_handler=event_handler,
                images=images,
            )
        )
    except Exception as exc:
        if output_format in {"json", "stream-json"}:
            stdout.write(json.dumps({"type": "result", "status": "failed", "error_message": str(exc)}, ensure_ascii=False) + "\n")
        else:
            stderr.write(f"Headless execution failed: {exc}\n")
        return 1

    ok = result.status in {"success", "partial"}
    if output_format in {"json", "stream-json"}:
        stdout.write(json.dumps(_result_payload(result), ensure_ascii=False) + "\n")
        return 0 if ok else 1

    # text
    if ok and result.final_answer:
        stdout.write(result.final_answer.rstrip() + "\n")
    if ok:
        return 0
    if result.final_answer:
        stderr.write(result.final_answer.rstrip() + "\n")
    if result.error_message:
        stderr.write(result.error_message.rstrip() + "\n")
    return 1
