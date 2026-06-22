from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "packaging" / "allcode.spec"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a onefile allCode binary.")
    parser.add_argument(
        "--name",
        default="allcode",
        help="Output binary name without any OS-specific suffix.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Keep PyInstaller build cache.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env = os.environ.copy()
    env["ALLCODE_BINARY_NAME"] = args.name

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_PATH),
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
    ]
    if not args.no_clean:
        command.append("--clean")

    return subprocess.call(command, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
