"""Headless runner for non-TUI execution."""

from __future__ import annotations

import asyncio
import sys
from typing import TextIO

from allCode.config.schema import AppConfig
from allCode.core.result import TurnResult
from allCode.runtime import run_agent_turn
from allCode.tools.registry import ToolRegistry


async def run_headless(
    prompt: str,
    *,
    config: AppConfig,
    llm_client=None,
    tools: ToolRegistry | None = None,
) -> TurnResult:
    return await run_agent_turn(
        prompt,
        config=config,
        llm_client=llm_client,
        tools=tools,
    )


def run_headless_sync(
    prompt: str,
    *,
    config: AppConfig,
    out: TextIO | None = None,
    err: TextIO | None = None,
    llm_client=None,
    tools: ToolRegistry | None = None,
) -> int:
    stdout = out or sys.stdout
    stderr = err or sys.stderr
    try:
        result = asyncio.run(run_headless(prompt, config=config, llm_client=llm_client, tools=tools))
    except Exception as exc:
        stderr.write(f"Headless execution failed: {exc}\n")
        return 1
    if result.final_answer:
        stdout.write(result.final_answer.rstrip() + "\n")
    if result.status in {"success", "partial"}:
        return 0
    if result.error_message:
        stderr.write(result.error_message.rstrip() + "\n")
    return 1
