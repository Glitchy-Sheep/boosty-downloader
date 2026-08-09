# Dev Tools

## Prerequisites

- [uv](https://docs.astral.sh/uv/) - Python, dependencies and builds in one binary:
  - macOS: `brew install uv`
  - Windows: `winget install --id=astral-sh.uv -e` (or `scoop install uv`)
  - Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [Task](https://taskfile.dev) - the command runner:
  - macOS: `brew install go-task/tap/go-task`
  - Windows: `winget install Task.Task` (or `scoop install task` / `choco install go-task`)
  - Linux: `sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d` (or `sudo snap install task --classic`)

Python itself comes from uv: `.python-version` pins the dev version, and uv downloads that exact standalone CPython on the first `uv sync`.

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

## uv for Poetry users

uv is one binary that manages Python itself, the venv, the lockfile and builds.

### Command map

| Poetry | uv |
|--------|----|
| `poetry install` / `poetry sync` | `uv sync` |
| `poetry add aiohttp` | `uv add aiohttp` |
| `poetry add --group dev ruff` | `uv add --dev ruff` |
| `poetry remove aiohttp` | `uv remove aiohttp` |
| `poetry update` | `uv lock --upgrade && uv sync` |
| `poetry run pytest` | `uv run pytest` |
| `poetry build` | `uv build` |
| `poetry shell` | not needed - `uv run <cmd>` works from any shell |
| `poetry version patch` | the release wizard does this: `task release -- patch` |

### Concepts

- `uv lock` resolves the ranges from `pyproject.toml` into exact versions in `uv.lock`. `uv sync` makes `.venv` match the lockfile exactly: installs what's missing, removes what doesn't belong.
- `uv run X` runs `X` inside the project venv from any shell state - no activation, and it re-syncs the venv automatically when the lockfile changed.
- `uvx X` runs a tool in a throwaway environment without touching the project (like `pipx run`).
- uv manages Python: `.python-version` pins the dev version, uv downloads that exact standalone CPython. System package updates cannot break the venv.

### Typical scenarios

- **Add a dependency:** `uv add aiohttp` - updates `pyproject.toml`, `uv.lock` and `.venv` in one step.
- **Update everything within ranges:** `uv lock --upgrade && uv sync`, commit `uv.lock`.
- **Fresh machine:** install uv and Task, `git clone`, `task setup` - uv brings its own Python.
- **Broken venv:** `rm -rf .venv && uv sync` - seconds, fully reproducible from `uv.lock`.

### Gotchas

- Don't activate the venv by habit: a stale `VIRTUAL_ENV` makes tools fail in confusing ways, and `uv run` / `task` never need activation.
- `uv sync` removes packages installed into `.venv` by hand - declare everything in `pyproject.toml`.
- The lockfile is `uv.lock` - commit it with every dependency change.
- The build backend stays `poetry-core`: the `[tool.poetry] packages` block in `pyproject.toml` is required for packaging, keep it.
