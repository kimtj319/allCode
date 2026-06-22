# allCode Binary Packaging

allCode is distributed as PyInstaller onefile binaries so end users do not need
to install Python or pip.

## Supported Targets

| Target | Output |
|---|---|
| macOS arm64 | `allcode-macos-arm64.tar.gz` |
| macOS x86_64 | `allcode-macos-x86_64.tar.gz` |
| Windows x86_64 | `allcode-windows-x86_64.exe.zip` |
| Linux x86_64 | `allcode-linux-x86_64.tar.gz` |
| Linux arm64 | `allcode-linux-arm64.tar.gz` |

Windows arm64 is intentionally not built.

Linux binaries target glibc-based distributions. Alpine Linux is not supported
by the default binary because it uses musl libc.

## Local Build

Create a build environment and install packaging dependencies:

```bash
python3.11 -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install ".[source-intelligence,package]"
```

Build a onefile binary:

```bash
python packaging/build_onefile.py --name allcode-linux-x86_64
```

The binary is written to `dist/`.

## Release Build

GitHub Actions builds all supported targets from `.github/workflows/build-binaries.yml`.

Run it manually with `workflow_dispatch`, or create a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Tagged builds publish release assets and `checksums.txt` to the GitHub release.

## Smoke Tests

Each built binary must pass:

```bash
allcode --version
allcode --check
```

`--check` (alias `--diagnose`) validates the local runtime configuration —
config file resolution, model/backend settings, and API-key presence — and exits
without contacting the model backend.
