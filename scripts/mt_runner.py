"""Stage 2: PTY/TTY interactive multi-turn stress-test runner (resumable).

Drives `python -m allCode` in a real PTY for each scenario in
allcode_test_matrix.json, injects the initial prompt, waits for the turn to go
quiescent, then injects the follow-up turns — verifying the interactive TTY path
and multi-turn context. Results stream into test_progress.json after every
scenario so a re-run continues where it left off. Full transcripts are saved
under output/mt_logs/ for the report / debugging.

Usage:
  python scripts/mt_runner.py --batch 5            # run up to 5 pending scenarios
  python scripts/mt_runner.py --ids S001,S051      # run specific scenarios
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYBIN = str(ROOT / ".venv/bin/python")
MATRIX = ROOT / "allcode_test_matrix.json"
PROGRESS = ROOT / "test_progress.json"
LOGDIR = ROOT / "output" / "mt_logs"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]|\r")

STARTUP_IDLE = 4.0      # wait for banner/composer before first prompt
IDLE_DONE = 6.0         # quiet seconds that mark a turn complete
MIN_TURN = 2.0          # never declare done before this
MAX_TURN = 210.0        # per-turn ceiling → possible hang


def _strip(t: str) -> str:
    return _ANSI.sub("", t)


def _winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _resolve_ws(policy: str) -> tuple[Path, bool]:
    """Return (workspace_path, is_temp). 'none'→fresh temp, '.'→repo, else→fresh dir."""
    if policy == "none":
        return Path(tempfile.mkdtemp(prefix="acmt_")), True
    if policy == ".":
        return ROOT, False
    ws = ROOT / policy
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)
    return ws, False


def _drain_until_quiescent(master: int, proc: subprocess.Popen, sink: list[str]) -> tuple[bool, bool]:
    """Read until the turn goes quiet. Returns (saw_output, hit_max)."""
    start = time.time()
    last = start
    saw = False
    while True:
        if proc.poll() is not None:
            return saw, False
        now = time.time()
        if now - start > MAX_TURN:
            return saw, True
        if saw and (now - last) > IDLE_DONE and (now - start) > MIN_TURN:
            return saw, False
        r, _, _ = select.select([master], [], [], 0.5)
        if r:
            try:
                data = os.read(master, 65536)
            except OSError:
                return saw, False
            if data:
                sink.append(data.decode(errors="replace"))
                saw = True
                last = time.time()


def _inject(master: int, text: str) -> None:
    os.write(master, text.encode() + b"\r")


def _evaluate(turns: list[dict]) -> tuple[str, str]:
    """Classify the scenario from its per-turn captures."""
    for t in turns:
        if t.get("hang"):
            return "hang", f"turn {t['index']} exceeded {MAX_TURN:.0f}s without quiescence"
        body = t.get("text", "")
        low = body.lower()
        if "traceback (most recent call last)" in low or "unhandledexception" in low:
            return "error", f"traceback in turn {t['index']}"
        if not t.get("saw_output") or len(body.strip()) < 2:
            return "empty", f"turn {t['index']} produced no visible output"
    return "ok", "all turns produced output without crash/hang"


def run_scenario(sc: dict) -> dict:
    LOGDIR.mkdir(parents=True, exist_ok=True)
    ws, is_temp = _resolve_ws(sc["workspace"])
    env = dict(os.environ, TERM="xterm-256color", PYTHONUNBUFFERED="1", ALLCODE_APPROVAL_MODE="auto")
    m, s = pty.openpty()
    _winsize(s, 50, 120)
    proc = subprocess.Popen(
        [PYBIN, "-m", "allCode", "--workspace", str(ws), "--approval", "auto"],
        stdin=s, stdout=s, stderr=s, cwd=str(ROOT), env=env, close_fds=True, start_new_session=True,
    )
    os.close(s)
    started = time.time()
    turns: list[dict] = []
    full: list[str] = []
    try:
        boot: list[str] = []
        _drain_until_quiescent_boot(m, proc, boot)
        full.extend(boot)
        prompts = [sc["prompt"], *sc.get("follow_ups", [])]
        for i, p in enumerate(prompts):
            if proc.poll() is not None:
                turns.append({"index": i, "prompt": p, "saw_output": False, "text": "", "hang": False, "note": "process exited early"})
                break
            _inject(m, p)
            sink: list[str] = []
            saw, hit_max = _drain_until_quiescent(m, proc, sink)
            full.extend(sink)
            turns.append({
                "index": i,
                "prompt": p[:120],
                "saw_output": saw,
                "hang": hit_max,
                "text": _strip("".join(sink))[-4000:],
            })
        # graceful exit
        if proc.poll() is None:
            try:
                _inject(m, "/exit")
            except OSError:
                pass
            t0 = time.time()
            while proc.poll() is None and time.time() - t0 < 8:
                r, _, _ = select.select([m], [], [], 0.3)
                if r:
                    try:
                        os.read(m, 65536)
                    except OSError:
                        break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except Exception:
                proc.kill()
        try:
            os.close(m)
        except OSError:
            pass
        if is_temp:
            shutil.rmtree(ws, ignore_errors=True)

    status, note = _evaluate(turns)
    # Project genres: independently run the generated tests for a real quality signal.
    tests_result = None
    if sc["genre"] in {"1_project_impl", "6_web_impl"} and not is_temp and ws != ROOT:
        tests_result = _verify_project(ws)
        if status == "ok" and tests_result == "no_files":
            status, note = "empty", "no source files were generated"
        elif status == "ok" and tests_result and tests_result.startswith("fail"):
            status, note = "weak", f"generated but tests not passing ({tests_result})"
    (LOGDIR / f"{sc['id']}.log").write_text("".join(full), encoding="utf-8")
    return {
        "id": sc["id"],
        "genre": sc["genre"],
        "status": status,
        "note": note,
        "tests_result": tests_result,
        "elapsed_s": round(time.time() - started, 1),
        "turns": [{k: t[k] for k in ("index", "saw_output", "hang")} for t in turns],
        "turn_count": len(turns),
    }


def _verify_project(ws: Path) -> str:
    """Run the generated project's pytest; return 'pass:N' / 'fail:...' / 'no_files'."""
    py_files = [p for p in ws.rglob("*.py") if "__pycache__" not in str(p)]
    if not py_files:
        return "no_files"
    try:
        proc = subprocess.run(
            [PYBIN, "-m", "pytest", "-q", str(ws)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "fail:timeout"
    out = (proc.stdout + proc.stderr).strip().splitlines()
    last = out[-1] if out else ""
    if " passed" in last and " failed" not in last and "error" not in last.lower():
        return "pass:" + last.strip()
    if "no tests ran" in last:
        return "fail:no_tests"
    return "fail:" + last.strip()[:80]


def _drain_until_quiescent_boot(master: int, proc: subprocess.Popen, sink: list[str]) -> None:
    start = time.time()
    last = start
    while True:
        if proc.poll() is not None:
            return
        now = time.time()
        if now - start > 30:
            return
        if (now - last) > STARTUP_IDLE:
            return
        r, _, _ = select.select([master], [], [], 0.5)
        if r:
            try:
                data = os.read(master, 65536)
            except OSError:
                return
            if data:
                sink.append(data.decode(errors="replace"))
                last = time.time()


def load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    return {"results": {}}


def save_progress(prog: dict) -> None:
    PROGRESS.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=5)
    ap.add_argument("--ids", default="")
    args = ap.parse_args()

    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    scenarios = {s["id"]: s for s in matrix["scenarios"]}
    prog = load_progress()
    done = set(prog["results"].keys())

    if args.ids:
        todo = [scenarios[i] for i in args.ids.split(",") if i in scenarios]
    else:
        todo = [s for s in matrix["scenarios"] if s["id"] not in done][: args.batch]

    print(f"running {len(todo)} scenario(s); {len(done)}/{len(scenarios)} already done")
    for sc in todo:
        res = run_scenario(sc)
        prog["results"][sc["id"]] = res
        save_progress(prog)  # resumable: persist after each scenario
        print(f"  [{res['status']:5}] {res['id']} {res['genre']:16} {res['elapsed_s']}s turns={res['turn_count']} :: {res['note']}")
    n = len(prog["results"])
    by = {}
    for r in prog["results"].values():
        by[r["status"]] = by.get(r["status"], 0) + 1
    print(f"progress: {n}/{len(scenarios)} | {by}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
