"""Focused prompt contracts for answer routes."""

from __future__ import annotations

from allCode.agent.router import RoutingDecision


# Shared style guidance for every answer route. Calibrating length to the
# question and preferring bullet lists over wide tables keeps answers readable in
# the terminal — the weak model otherwise over-explains simple questions and emits
# malformed Markdown tables that leak raw "|" characters.
_ANSWER_STYLE_GUIDANCE = (
    "Match the response length to the question: answer a simple or conceptual "
    "question with a focused short paragraph or a few bullets, and reserve long, "
    "multi-section answers for genuinely broad or complex requests. Do not pad a "
    "small question with exhaustive edge cases, repeated examples, or large "
    "comparison tables. Prefer short bullet lists over Markdown tables for "
    "comparisons, since wide tables render poorly in the terminal."
)


def answer_route_instruction(routing: RoutingDecision) -> str:
    if routing.kind != "answer":
        return ""
    if routing.requires_external_knowledge:
        return "\n".join(
            [
                "Answer route: external evidence only.",
                _ANSWER_STYLE_GUIDANCE,
                "Only use web_search or web_fetch for external evidence; do not call file, shell, mutation, or validation tools.",
                "Use the registered native web_search or web_fetch tool only to collect external evidence.",
                "If web_search reports web_search_unavailable or backend disabled, state that the web backend is not configured and cite the setting to configure.",
                "When explaining unavailable web evidence in Korean, include the term 검색 so the user can recognize the web-search failure.",
                "Never print tool-call plans, action JSON, or raw search results as the final answer.",
                "After web evidence is observed, write a natural-language answer grounded in that evidence.",
            ]
        )
    lines = [
        "Answer route: direct natural-language response only.",
        "Do not call tools for this turn; answer from the prompt and supplied context.",
        "If the answer depends on unavailable current facts, say what is missing instead of inventing evidence.",
        _ANSWER_STYLE_GUIDANCE,
    ]
    if "external_knowledge_suppressed" in routing.flags:
        lines.extend(
            [
                "The user asked for stable/general principles rather than latest or current figures.",
                "Keep the answer qualitative and decision-oriented; do not invent concrete benchmark values, percentages, prices, model sizes, dates, or latency/cost figures unless the user supplied them.",
            ]
        )
    if "stdlib_only_requested" in routing.flags:
        lines.extend(
            [
                "The user requested a strict standard-library-only or no-third-party-dependency answer.",
                "Do not recommend third-party packages, package installs, or dependency files unless the user explicitly asked to compare rejected alternatives.",
                "For Python examples and tests, prefer standard-library modules such as argparse, json, pathlib, sqlite3, unittest, tempfile, and subprocess.",
            ]
        )
    if "refused" in routing.reason.lower() or "disallowed" in routing.reason.lower():
        lines.append("For safety refusals, explicitly mention that the request is 위험 and cannot proceed without proper 승인.")
    return "\n".join(lines)
