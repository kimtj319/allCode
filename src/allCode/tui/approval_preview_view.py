"""UI-facing projection for approval preview payloads."""

from __future__ import annotations

from typing import Any

from allCode.core.models import CoreModel


class ApprovalPreviewView(CoreModel):
    kind: str = ""
    summary: str = ""
    preview: str = ""


def approval_preview_from_payload(payload: dict[str, Any], *, fallback_preview: str = "") -> ApprovalPreviewView:
    preview_data = payload.get("approval_preview")
    metadata = payload.get("metadata")
    if not isinstance(preview_data, dict) and isinstance(metadata, dict):
        preview_data = metadata.get("approval_preview")
    if not isinstance(preview_data, dict):
        return ApprovalPreviewView(preview=fallback_preview)
    return ApprovalPreviewView(
        kind=str(preview_data.get("kind") or ""),
        summary=str(preview_data.get("summary") or ""),
        preview=str(preview_data.get("preview") or fallback_preview),
    )
