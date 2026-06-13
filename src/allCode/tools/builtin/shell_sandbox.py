"""OS-level confinement for agent-run shell commands.

On macOS, ``workspace-write`` wraps a command in ``sandbox-exec`` (seatbelt) with
a profile that allows reads and network but blocks filesystem writes outside the
workspace and the usual temp directories. This is the OS-enforced backstop behind
allCode's path-confinement + approval gate, mirroring Codex's workspace-write
sandbox. On other platforms (or when ``sandbox-exec`` is missing) it is a no-op
so behavior degrades gracefully rather than failing.
"""

from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

_WRITABLE_SUBPATHS = ("/tmp", "/private/tmp", "/private/var/folders", "/dev")


def _seatbelt_profile(workspace_root: Path) -> str:
    writable = [str(workspace_root), *(_WRITABLE_SUBPATHS)]
    subpaths = "\n".join(f'    (subpath "{path}")' for path in writable)
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny file-write*)\n"
        "(allow file-write*\n"
        f"{subpaths}\n"
        ')\n'
    )


def sandbox_command(command: str, *, workspace_root: Path, mode: str) -> str | None:
    """Return ``command`` wrapped for OS sandboxing, or None if not applied.

    None means "run the command unchanged" — either sandboxing is off or the
    platform has no supported sandbox. Callers must treat None as no-op.
    """
    if mode != "workspace-write":
        return None
    if sys.platform != "darwin":
        return None
    sandbox_exec = shutil.which("sandbox-exec")
    if not sandbox_exec:
        return None
    profile = _seatbelt_profile(workspace_root.expanduser().resolve())
    return f"{shlex.quote(sandbox_exec)} -p {shlex.quote(profile)} /bin/sh -c {shlex.quote(command)}"
