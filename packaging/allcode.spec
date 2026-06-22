# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


ROOT = Path.cwd()
BINARY_NAME = os.environ.get("ALLCODE_BINARY_NAME", "allcode")

# allCode generates its runtime config (.allCode/config.yaml) and AGENTS.md from
# code rather than from packaged template files, so there are no bundled data
# files to ship with the binary.
datas = []
binaries = []
hiddenimports = collect_submodules("allCode")

# Optional source-intelligence backend (tree-sitter). When installed, bundle its
# native grammars and shared libraries so code analysis works in the binary; when
# absent, allCode degrades gracefully and the binary still builds.
for package in ("tree_sitter", "tree_sitter_language_pack"):
    try:
        datas += collect_data_files(package)
        binaries += collect_dynamic_libs(package)
        hiddenimports += collect_submodules(package)
    except Exception:
        pass


a = Analysis(
    [str(ROOT / "src" / "allCode" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=BINARY_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
