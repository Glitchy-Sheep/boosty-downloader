# Dev Tools

## Prerequisites

- Python 3.10+
- [Poetry](https://python-poetry.org/)
- GNU Make (on Windows: Git Bash or `choco install make`)

## Ruff (lint + format)

[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting. Configuration: `ruff.toml`.

- **All lint rules enabled** (`ALL`) with selective ignores
- **Single quotes**, line length **88**
- Per-file relaxations: `test/*` allows `assert`, magic numbers, no docstrings; `scripts/*` allows `print()`

## Pyright (types)

[Pyright](https://github.com/microsoft/pyright) in **strict mode**, targeting Python 3.10.

The codebase uses `from __future__ import annotations` and `TYPE_CHECKING` blocks for type imports.

## Command Reference

| Command | What it does |
|---------|-------------|
| `make deps` | Install/sync dependencies |
| `make ci-check` | Run all CI checks: lint + types + format |
| `make dev-fix` | Auto-fix lint and formatting, then type-check |
| `make lint-check` | Lint only |
| `make lint-fix` | Lint with auto-fix |
| `make format-check` | Check formatting |
| `make format-fix` | Apply formatting |
| `make types` | Type check |
| `make test` | Unit tests |
| `make test-verbose` | Unit tests (verbose) |
| `make test-api` | Integration tests |
| `make build` | Build wheel + sdist |
| `make release v=...` | Bump version and update changelog |
| `make posts-example` | Dump raw API response for debugging |
