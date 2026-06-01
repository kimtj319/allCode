"""Routing helper for generation workflow handoff."""

from __future__ import annotations

import re

from allCode.agent.router import RoutingDecision

GENERATION_MARKERS = (
    "new project",
    "create a project",
    "generate project",
    "scaffold",
    "bootstrap",
    "프로젝트 생성",
    "새 프로젝트",
    "프로젝트를 생성",
)
GENERATION_ACTIONS = ("create", "generate", "scaffold", "bootstrap", "생성", "만들")
PROJECT_TERMS = ("project", "프로젝트")
EXISTING_PROJECT_TERMS = ("existing project", "existing python project", "기존 프로젝트", "기존")
ENGLISH_GENERATION_ACTION = re.compile(r"\b(create|generate|scaffold|bootstrap)\b")


def should_use_generation_workflow(prompt: str, routing: RoutingDecision) -> bool:
    if routing.kind != "modify" or routing.read_only_requested:
        return False
    lowered = prompt.lower()
    if any(marker in lowered for marker in GENERATION_MARKERS):
        return True
    if any(term in lowered for term in EXISTING_PROJECT_TERMS):
        return False
    english_action = ENGLISH_GENERATION_ACTION.search(lowered) is not None
    korean_action = any(action in lowered for action in ("생성", "만들"))
    return (english_action or korean_action) and any(term in lowered for term in PROJECT_TERMS)
