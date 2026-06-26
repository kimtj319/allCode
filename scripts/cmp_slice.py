"""Slice cmp_results.json into focused per-chunk markdown files for judging."""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_NAME = os.environ.get("MT_RESULTS", "cmp_results.json")
OUT = ROOT / "output" / (os.environ.get("MT_SLICE_DIR") or "cmp_slices")


def fmt(x: dict) -> str:
    a, c = x["allcode"], x["codex"]
    def block(tag, d):
        meta = f"status={d.get('status')} created_py={d.get('created_py')} elapsed={d.get('elapsed_s')}s"
        if tag == "allCode":
            meta += f" validation_passed={d.get('validation_passed')} created_files={d.get('created_files')}"
        return f"**{tag}** ({meta}):\n\n{(d.get('answer') or '(empty)').strip()}\n"
    return (
        f"### {x['id']} — category={x['category']} | dimension={x['dimension']} | workspace={x['workspace']}\n\n"
        f"**PROMPT:** {x['prompt']}\n\n"
        f"{block('allCode', a)}\n---\n\n{block('codex', c)}\n\n======\n"
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    r = json.load(open(ROOT / RESULTS_NAME))["results"]
    ids = sorted(r.keys())
    chunks = [ids[i:i + 20] for i in range(0, len(ids), 20)]
    for n, chunk in enumerate(chunks, start=1):
        body = "".join(fmt(r[i]) for i in chunk)
        (OUT / f"chunk_{n}.md").write_text(body, encoding="utf-8")
        print(f"chunk_{n}.md: {chunk[0]}..{chunk[-1]} ({len(body)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
