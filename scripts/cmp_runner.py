"""Run the 100 single-turn prompts through allCode and codex, save both answers.

For each scenario both agents run headless in an isolated workspace:
  - "none"  -> fresh empty temp dir (no files expected)
  - "build" -> fresh empty temp dir (files expected in cwd)
  - "."     -> a throwaway `git archive HEAD` snapshot of THIS repo (tracked
               files only) so analysis prompts see a faithful tree while neither
               agent can dirty the real working tree.

allCode: `python -m allCode --headless P --output-format json` (clean JSON with
final_answer/status/created_files/token_usage).
codex:   `codex exec --ephemeral -m gpt-5.5` (final answer parsed from the block
before "tokens used"); read-only sandbox except "build" (workspace-write).

Both run with the SAME prompt. The comparison (separate judging step) scores
harness-attributable quality while discounting raw model capability.

Results stream into cmp_results.json after every scenario (resumable).

Usage:
  python scripts/cmp_runner.py --batch 10
  python scripts/cmp_runner.py --ids C001,C051
  python scripts/cmp_runner.py --only allcode   # run just one side
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYBIN = str(ROOT / ".venv/bin/python")
MATRIX = ROOT / "cmp_matrix.json"
RESULTS = ROOT / "cmp_results.json"
ENV_FILE = ROOT / ".env"
ENDPOINT = "http://211.39.140.164:30100/v1"
CODEX_MODEL = "gpt-5.5"
CODEX_EFFORT = "medium"
AGENT_TIMEOUT = 420  # seconds per agent per prompt

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]|\r")


def _load_env() -> dict:
    env = dict(os.environ)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _snapshot_repo(dest: Path) -> None:
    """Faithful, safe copy of the repo (tracked files) via git archive."""
    dest.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", "HEAD"], cwd=str(ROOT), capture_output=True, check=True
    ).stdout
    tar = subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, capture_output=True)
    if tar.returncode != 0:
        raise RuntimeError(f"tar extract failed: {tar.stderr.decode(errors='replace')}")


def _make_ws(policy: str) -> Path:
    ws = Path(tempfile.mkdtemp(prefix="cmp_"))
    if policy == ".":
        _snapshot_repo(ws)
    return ws


def _list_py(ws: Path) -> list[str]:
    return sorted(
        str(p.relative_to(ws)) for p in ws.rglob("*.py") if "__pycache__" not in str(p)
    )


def run_allcode(prompt: str, policy: str, env: dict) -> dict:
    ws = _make_ws(policy)
    before = set(_list_py(ws))
    t0 = time.time()
    try:
        proc = subprocess.run(
            [PYBIN, "-m", "allCode", "--headless", prompt,
             "--output-format", "json", "--workspace", str(ws), "--approval", "auto"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=AGENT_TIMEOUT, env=env,
        )
        elapsed = round(time.time() - t0, 1)
        out = proc.stdout.strip()
        obj = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        new_py = sorted(set(_list_py(ws)) - before)
        if obj is None:
            return {"ok": False, "answer": out[-2000:], "status": "parse_error",
                    "elapsed_s": elapsed, "created_py": new_py, "error": (proc.stderr or "")[-400:]}
        return {
            "ok": obj.get("status") == "success",
            "answer": obj.get("final_answer") or "",
            "status": obj.get("status"),
            "created_files": obj.get("created_files", []),
            "modified_files": obj.get("modified_files", []),
            "created_py": new_py,
            "validation_passed": obj.get("validation_passed"),
            "tokens": (obj.get("token_usage") or {}).get("total_tokens"),
            "elapsed_s": elapsed,
            "error": obj.get("error_message"),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "answer": "", "status": "timeout",
                "elapsed_s": AGENT_TIMEOUT, "created_py": sorted(set(_list_py(ws)) - before)}
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _parse_codex(out: str) -> str:
    """Extract the final assistant message: the block before 'tokens used'."""
    text = _ANSI.sub("", out)
    lines = text.split("\n")
    # find last 'tokens used' marker
    tok_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "tokens used":
            tok_idx = i
            break
    end = tok_idx if tok_idx is not None else len(lines)
    # walk back to the preceding lone 'codex' marker
    start = None
    for i in range(end - 1, -1, -1):
        if lines[i].strip() == "codex":
            start = i + 1
            break
    if start is None:
        # fallback: everything after the prompt echo
        return "\n".join(lines[-40:]).strip()
    return "\n".join(lines[start:end]).strip()


def run_codex(prompt: str, policy: str, env: dict) -> dict:
    ws = _make_ws(policy)
    before = set(_list_py(ws))
    sandbox = "workspace-write" if policy == "build" else "read-only"
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--color", "never",
             "-C", str(ws), "-s", sandbox, "-m", CODEX_MODEL,
             "-c", f"model_reasoning_effort={CODEX_EFFORT}", prompt],
            cwd=str(ws), capture_output=True, text=True, timeout=AGENT_TIMEOUT, env=env,
        )
        elapsed = round(time.time() - t0, 1)
        answer = _parse_codex(proc.stdout)
        new_py = sorted(set(_list_py(ws)) - before)
        err = ("ERROR" in proc.stdout) or proc.returncode != 0
        return {
            "ok": bool(answer) and not err,
            "answer": answer,
            "status": "error" if err else "success",
            "created_py": new_py,
            "elapsed_s": elapsed,
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "")[-300:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "answer": "", "status": "timeout",
                "elapsed_s": AGENT_TIMEOUT, "created_py": sorted(set(_list_py(ws)) - before)}
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def load_results() -> dict:
    if RESULTS.exists():
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    return {"results": {}}


def save_results(data: dict) -> None:
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--ids", default="")
    ap.add_argument("--only", choices=["allcode", "codex", "both"], default="both")
    args = ap.parse_args()

    env = _load_env()
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    scen = {s["id"]: s for s in matrix["scenarios"]}
    data = load_results()
    done = data["results"]

    if args.ids:
        todo = [scen[i] for i in args.ids.split(",") if i in scen]
    else:
        todo = [s for s in matrix["scenarios"] if s["id"] not in done][: args.batch]

    print(f"running {len(todo)} scenario(s); {len(done)}/{len(scen)} done; only={args.only}")
    for s in todo:
        sid, prompt, policy = s["id"], s["prompt"], s["workspace"]
        rec = done.get(sid, {"id": sid, "category": s["category"], "dimension": s["dimension"],
                             "workspace": policy, "prompt": prompt})
        if args.only in ("both", "allcode"):
            rec["allcode"] = run_allcode(prompt, policy, env)
        if args.only in ("both", "codex"):
            rec["codex"] = run_codex(prompt, policy, env)
        done[sid] = rec
        save_results(data)
        a = rec.get("allcode", {}); c = rec.get("codex", {})
        print(f"  {sid} {s['category']:16} ac[{a.get('status','-'):7} {a.get('elapsed_s','-')}s] "
              f"cx[{c.get('status','-'):7} {c.get('elapsed_s','-')}s]")
    print(f"progress: {len(done)}/{len(scen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
