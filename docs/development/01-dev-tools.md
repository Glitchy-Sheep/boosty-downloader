# Dev Tools

## Prerequisites

- Python 3.10+
- [Poetry](https://python-poetry.org/)
- [Task](https://taskfile.dev) - the command runner (replaces make):
  - macOS: `brew install go-task/tap/go-task`
  - Windows: `winget install Task.Task` (or `scoop install task` / `choco install go-task`)
  - Linux: `sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d` (or `sudo snap install task --classic`)

## Ruff (lint + format)

[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting. Configuration: `ruff.toml`.

- **All lint rules enabled** (`ALL`) with selective ignores
- **Single quotes**, line length **88**
- Per-file relaxations: `test/*` allows `assert`, magic numbers, no docstrings; `scripts/*` allows `print()`

## Pyright (types)

[Pyright](https://github.com/microsoft/pyright) in **strict mode**, targeting Python 3.10.

The codebase uses `from __future__ import annotations` and `TYPE_CHECKING` blocks for type imports.

## Command Reference

Tasks are grouped by the dev cycle: `setup` → `fix` → `check` → `test` → `build`. Run bare `task` for the grouped list.

| Command | What it does |
|---------|-------------|
| `task setup` | First-time dev setup (venv + deps + editor settings) |
| `task deps` | Install/sync dependencies (alias of `setup:deps`) |
| `task ci` | Everything CI runs: checks + tests + build |
| `task fix` | Auto-fix lint and formatting, then type-check |
| `task lint` | Lint with auto-fix (alias of `fix:lint`) |
| `task format` | Apply formatting (alias of `fix:format`) |
| `task check` | Run all CI checks: lint + format + types |
| `task check:lint` | Lint only, no fixes |
| `task check:format` | Check formatting without changes |
| `task check:types` | Type check |
| `task test` | Unit tests |
| `task test -- -v` | Unit tests (verbose) |
| `task test:api` | Integration tests (with a credentials preflight) |
| `task build` | Build wheel + sdist |
| `task release -- ...` | Bump version and update changelog |
| `task posts-example` | Dump raw API response for debugging |
