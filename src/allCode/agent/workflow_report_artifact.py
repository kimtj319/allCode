"""Optional report artifact planning for explicit report requests."""

from __future__ import annotations

import re

from allCode.agent.task_plan import PlannedFile


def ensure_requested_report_artifact(files: list[PlannedFile], *, prompt: str) -> list[PlannedFile]:
    if not report_artifact_requested(prompt) or _has_report_file(files):
        return files
    return [
        *files,
        PlannedFile(
            path="REPORT.md",
            purpose="Result report artifact explicitly requested by the prompt.",
            stage="implementation",
            content="# Result Report\n\n- Implementation summary will be updated after validation.\n",
            required=True,
        ),
    ]


def report_artifact_requested(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    english = any(term in lowered for term in ("report artifact", "result report", "write a report", "include a report"))
    korean = any(term in compact for term in ("보고서파일", "결과보고서", "리포트파일", "보고서문서", "결과정리문서"))
    return english or korean


def _has_report_file(files: list[PlannedFile]) -> bool:
    for file in files:
        name = file.path.rsplit("/", 1)[-1].lower()
        if name in {"report.md", "result_report.md", "results.md"}:
            return True
    return False
