"""Quality scenario runner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import yaml

from allCode.core.events import AgentEvent
from allCode.quality.scoring import QualityObservation, QualityScenario, QualityScore, QualityScorer
from allCode.tui.renderers import EventRenderer

ObservationFactory = Callable[[QualityScenario], Awaitable[QualityObservation]]


class QualityRunner:
    def __init__(self, *, scorer: QualityScorer | None = None, renderer: EventRenderer | None = None) -> None:
        self.scorer = scorer or QualityScorer()
        self.renderer = renderer or EventRenderer()

    def load_matrix(self, path: Path) -> list[QualityScenario]:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        scenarios = raw.get("scenarios", []) if isinstance(raw, dict) else []
        return [QualityScenario.model_validate(item) for item in scenarios]

    async def run(self, scenarios: list[QualityScenario], factory: ObservationFactory) -> dict[str, QualityScore]:
        scores: dict[str, QualityScore] = {}
        for scenario in scenarios:
            observation = await factory(scenario)
            scores[scenario.name] = self.scorer.score(scenario, observation)
        return scores

    def observation_from_result(self, *, result, events: list[AgentEvent]) -> QualityObservation:
        tool_names: list[str] = []
        mutation_tools: list[str] = []
        statuses: list[str] = []
        for event in events:
            rendered = self.renderer.render(event)
            if rendered.status:
                statuses.append(rendered.status)
            if event.event_type == "tool_execution_finished":
                tool_result = getattr(event, "result", None)
                if tool_result is not None:
                    tool_names.append(tool_result.name)
                    if tool_result.name in {"write_file", "patch_file"}:
                        mutation_tools.append(tool_result.name)
            elif event.event_type == "tool_execution_started":
                tool_call = getattr(event, "tool_call", None)
                if tool_call is not None and tool_call.name not in tool_names:
                    tool_names.append(tool_call.name)
                    if tool_call.name in {"write_file", "patch_file"}:
                        mutation_tools.append(tool_call.name)
        return QualityObservation(
            result=result,
            event_types=[event.event_type for event in events],
            tool_names=tool_names,
            mutation_tools=mutation_tools,
            rendered_statuses=statuses,
        )

    def run_sync(self, scenarios: list[QualityScenario], factory: ObservationFactory) -> dict[str, QualityScore]:
        return asyncio.run(self.run(scenarios, factory))
