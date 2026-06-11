"""Provider-facing source analysis brief construction."""

from __future__ import annotations

from allCode.agent.language import ResponseLanguage
from allCode.agent.prompt_builder_helpers import tool_results_from_messages
from allCode.agent.source_answer_synthesis import (
    build_source_analysis_brief,
    render_compact_source_analysis_brief,
    render_source_analysis_brief,
    source_answer_needs_compact_brief,
)
from allCode.core.models import Message
from allCode.core.result import CompletionEvidence


def source_final_evidence_brief(
    messages: list[Message],
    *,
    evidence: CompletionEvidence,
    user_prompt: str,
    language: ResponseLanguage,
) -> str:
    brief = build_source_analysis_brief(
        tool_results_from_messages(messages),
        evidence=evidence,
        user_prompt=user_prompt,
    )
    if source_answer_needs_compact_brief(user_prompt):
        return render_compact_source_analysis_brief(brief, language=language)
    return render_source_analysis_brief(brief, language=language)
