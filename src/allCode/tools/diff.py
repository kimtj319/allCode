"""Diff and edit transaction helpers."""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

from allCode.core.models import CoreModel


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def unified_diff(before: str, after: str, *, fromfile: str, tofile: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


class EditTransaction(CoreModel):
    file_path: str
    action: str
    before_hash: str
    after_hash: str
    diff: str
    rollback_payload: str

    @classmethod
    def from_contents(
        cls,
        *,
        path: Path,
        before: str,
        after: str,
        action: str,
    ) -> "EditTransaction":
        return cls(
            file_path=str(path),
            action=action,
            before_hash=sha256_text(before),
            after_hash=sha256_text(after),
            diff=unified_diff(before, after, fromfile=f"{path} (before)", tofile=f"{path} (after)"),
            rollback_payload=before,
        )
