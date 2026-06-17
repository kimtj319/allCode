"""OS-level confinement for agent-run shell commands.

Three modes, mirroring Codex's sandbox tiers:

* ``off`` — no OS sandbox (allCode's path-confinement + approval gate only).
* ``read-only`` — the command may read anywhere and use the network, but may
  only write to temp dirs (never the workspace). For commands that should not
  mutate the project at all.
* ``workspace-write`` — like read-only, but the workspace tree is also writable.

Enforcement backends, by platform:

* macOS: ``sandbox-exec`` (seatbelt) with a generated profile.
* Linux: ``bwrap`` (bubblewrap) with a read-only root bind and writable temp
  (plus the workspace for ``workspace-write``).

When no supported backend is available the wrapper is a no-op (returns None), so
behavior degrades gracefully rather than failing.
"""

from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

_MODES = ("off", "read-only", "workspace-write")
# Always-writable temp/device dirs so interpreters and build tools still work
# even under read-only confinement.
_TEMP_SUBPATHS = ("/tmp", "/private/tmp", "/private/var/folders", "/dev")
_LINUX_TEMP = ("/tmp", "/dev/shm")


def _writable_roots(workspace_root: Path, mode: str) -> list[str]:
    roots = list(_TEMP_SUBPATHS)
    if mode == "workspace-write":
        roots.insert(0, str(workspace_root))
    return roots


def _seatbelt_profile(workspace_root: Path, mode: str) -> str:
    writable = _writable_roots(workspace_root, mode)
    subpaths = "\n".join(f'    (subpath "{path}")' for path in writable)
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny file-write*)\n"
        "(allow file-write*\n"
        f"{subpaths}\n"
        ")\n"
    )


def _macos_command(command: str, workspace_root: Path, mode: str) -> str | None:
    sandbox_exec = shutil.which("sandbox-exec")
    if not sandbox_exec:
        return None
    profile = _seatbelt_profile(workspace_root, mode)
    return f"{shlex.quote(sandbox_exec)} -p {shlex.quote(profile)} /bin/sh -c {shlex.quote(command)}"


def _linux_command(command: str, workspace_root: Path, mode: str) -> str | None:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return None
    # Read-only view of the whole filesystem, with writable temp (and the
    # workspace for workspace-write). Network is shared; only the mount
    # namespace is isolated, so writes outside the allowed paths are blocked.
    args = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    for temp in _LINUX_TEMP:
        args += ["--tmpfs", temp]
    if mode == "workspace-write":
        ws = str(workspace_root)
        args += ["--bind", ws, ws]
    args += ["--share-net", "/bin/sh", "-c", command]
    return " ".join(shlex.quote(part) for part in args)


def sandbox_command(command: str, *, workspace_root: Path, mode: str) -> str | None:
    """Return ``command`` wrapped for OS sandboxing, or None if not applied.

    None means "run the command unchanged" — either sandboxing is off, the mode
    is unknown, or the platform has no supported backend. Callers must treat None
    as no-op.
    """
    if mode not in {"read-only", "workspace-write"}:
        return None
    resolved = workspace_root.expanduser().resolve()
    if sys.platform == "darwin":
        return _macos_command(command, resolved, mode)
    if sys.platform.startswith("linux"):
        return _linux_command(command, resolved, mode)
    return None
