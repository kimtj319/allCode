"""Graceful partial result for modify turns that inspected but did not edit.

When a modification turn ends without any file change but the model did inspect
the relevant files, returning a bare block-reason failure is unhelpful. This
renders a grounded change plan (clearly marked as not yet applied) from the
observed files, so the user still gets actionable next steps instead of an empty
failure.
"""

from __future__ import annotations

import re

from allCode.agent.language import ResponseLanguage
from allCode.core.result import CompletionEvidence


def has_modify_plan_evidence(evidence: CompletionEvidence) -> bool:
    if evidence.has_file_change():
        return False
    return bool(evidence.inspected_paths or evidence.representative_read_paths)


def modify_change_plan_fallback(
    *,
    prompt: str,
    evidence: CompletionEvidence,
    language: ResponseLanguage,
) -> str:
    observed: list[str] = []
    for path in [*evidence.inspected_paths, *evidence.representative_read_paths]:
        if path and path not in observed:
            observed.append(path)
    observed = observed[:10]
    request = _compact(prompt)
    if language == "en":
        lines = [
            "## Change plan (not yet applied)",
            "",
            "I inspected the relevant files but did not apply a file change in this turn, "
            "so this is a grounded plan rather than a completed edit.",
            "",
            f"**Request:** {request}",
            "",
            "**Files observed:**",
        ]
        lines.extend(f"- `{path}`" for path in observed)
        lines.extend(
            [
                "",
                "**Suggested change sites (from observed files):**",
                *[f"- `{path}` — apply the requested change here if it owns this concern." for path in observed],
                "",
                "No files were modified. Re-run with a specific target file (or approve edits) to apply the change.",
            ]
        )
        return "\n".join(lines)
    lines = [
        "## 변경 계획 (아직 적용 안 됨)",
        "",
        "관련 파일을 확인했지만 이번 턴에서 실제 파일 변경을 적용하지는 못했습니다. "
        "따라서 아래는 완료된 수정이 아니라 관찰 근거 기반 변경 계획입니다.",
        "",
        f"**요청:** {request}",
        "",
        "**관찰한 파일:**",
    ]
    lines.extend(f"- `{path}`" for path in observed)
    lines.extend(
        [
            "",
            "**변경 위치 후보 (관찰한 파일 기준):**",
            *[f"- `{path}` — 이 관심사를 담당한다면 여기에 요청한 변경을 적용." for path in observed],
            "",
            "실제 파일은 변경되지 않았습니다. 구체적 대상 파일을 지정하거나 편집을 승인해 다시 요청하면 적용합니다.",
        ]
    )
    return "\n".join(lines)


def _compact(text: str, *, limit: int = 200) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"
