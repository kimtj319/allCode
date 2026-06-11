"""Prompt construction for model-backed routing classification."""

from __future__ import annotations

import json
from collections.abc import Sequence

from allCode.agent.context import ContextBundle
from allCode.agent.prompt_constraints import PromptConstraints
from allCode.core.models import Message


def build_routing_messages(
    prompt: str,
    constraints: PromptConstraints,
    context_bundle: ContextBundle | None,
    recent_targets: Sequence[str],
) -> list[Message]:
    context_sources = context_bundle.sources() if context_bundle is not None else []
    context_section_names = [section.name for section in context_bundle.sections] if context_bundle is not None else []
    system = (
        "You are the allCode routing model. Do not answer the user's task. "
        "Return one JSON object only. Decide which tool capabilities the agent should expose.\n"
        'kind must be one of "answer", "inspect", "modify", "operate".\n'
        "Use inspect when the user asks to read, find, search, locate, analyze repository files, "
        "or asks a follow-up that requires workspace evidence.\n"
        "Use answer only when no tool evidence is needed.\n"
        "Use modify for file creation/edit/delete. Use operate for shell/build/test operation.\n"
        "tool_capabilities may include read_file, search_workspace, mutate_file, delete_file, "
        "run_shell, run_validation, web_search.\n"
        "workflow_hint must be none, direct_answer, direct_file_edit, single_file_create, "
        "multi_file_generation, validation_repair, or external_research.\n"
        "Single file creation/edit/delete must not be multi_file_generation. "
        "Existing file edits or fixes with a concrete filename or path must use direct_file_edit, "
        "not multi_file_generation or validation_repair."
    )
    user = {
        "prompt": prompt,
        "constraints": constraints.model_dump(mode="json"),
        "recent_targets": list(recent_targets),
        "context_sources": context_sources[:20],
        "context_sections": context_section_names[:20],
        "required_json_shape": {
            "kind": "answer|inspect|modify|operate",
            "confidence": 0.0,
            "tool_capabilities": ["read_file"],
            "workflow_hint": "none",
            "target_hint": None,
            "requires_validation": False,
            "requires_external_knowledge": False,
            "read_only_requested": False,
            "reason": "short rationale",
        },
    }
    return [Message(role="system", content=system), Message(role="user", content=json.dumps(user, ensure_ascii=False))]
