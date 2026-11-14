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

## Viewer development

The React viewer uses Node 24 LTS, pinned in `.nvmrc`. With nvm installed, run `nvm install` and `nvm use` in the repository. Node is needed for viewer tasks, `task build` and `task ci`. Python dependency installation, checks and tests remain independent of it; an editable `uv sync` does not need Node or built viewer assets.

- `task ui:install` installs the exact npm lockfile in `viewer-ui/`.
- `task ui:types` generates the tracked `viewer-ui/src/lib/api.gen.ts` from Python API models.
- `task ui:check` runs TypeScript, oxlint and Vitest.
- `task ui:build` writes static assets and Brotli/gzip copies of JavaScript and CSS to `boosty_downloader/viewer/static/app/`.
- `task ui:e2e` builds the viewer and checks it in isolated Chromium and Firefox sessions against a temporary library served by the real `view` command.
- `task build` builds the viewer first, then the wheel and source distribution. Both include the offline assets.

Commit `viewer-ui/package-lock.json` with dependency changes. Generated assets and `node_modules` are ignored. The source under `viewer-ui/src/lib/` is tracked despite the repository's general Python `lib/` ignore rule.

The JSON contract lives in `boosty_downloader/viewer/api_models.py`. After changing it, run `task ui:types` and `task ui:check`, then commit the Python changes together with the generated TypeScript file. Do not edit `api.gen.ts` by hand. The Viewer CI job regenerates it and rejects missing, untracked or stale declarations. Python-only checks and tests do not invoke Node.

`scripts/viewer_schema.py` exports every concrete request and response model as a deterministic serialization schema. Its root bundles definitions for generation; it is not an HTTP response envelope. Responses include nullable fields explicitly, and API failures use `{ "error": { "code": "...", "message": "..." } }`. The schema also defines the later marks, media and opener contracts; those routes are connected in subsequent stages.

A standard wheel build without `viewer/static/app/index.html` fails with a `task ui:build` hint. Direct `uv build` therefore requires that frontend step first; use `task build` for the complete pipeline. The generated UI also travels in the source distribution, so building a wheel from a released source archive does not need Node. Installing a published wheel does not need Node either.

The frontend shows authors, indexed media storage and a virtual author timeline through the `view` server. Search and filters live in the URL; the selected post currently shows saved metadata. Full post reading and Media controls are connected in subsequent stages.

Install the browser binaries once from `viewer-ui/` with `npx playwright install chromium firefox`. On Linux, add `--with-deps` to install the required system libraries. Then run `task ui:e2e` from the repository root. The harness generates its own synthetic library without ffmpeg, starts a viewer on an available local port and removes its temporary files after stopping the server. It sets the recording opener hook, so browser tests cannot launch desktop applications. HTML reports, screenshots and failure traces stay in the ignored `viewer-ui/playwright-report/` and `viewer-ui/test-results/` directories.

Start the Python backend on an explicit port and the Vite dev server in another terminal:

```bash
uv run python -m boosty_downloader.main view -o .sample/library --port 8314 --no-open
task ui:dev
```

The dev page is at `http://127.0.0.1:5174`. It binds localhost only and proxies `/api/`, `/media/` and `/thumbs/` to `http://127.0.0.1:8314`, rewriting Host and Origin for the backend's request guards. To use another backend port, set `BOOSTY_VIEWER_BACKEND` to the matching URL when starting `task ui:dev`. Use an explicit `view --port` so a busy default port cannot move the backend away from the proxy target.

After Ctrl+C, a fixed port can remain temporarily unavailable while the OS closes prior connections. Wait, or choose another `--port` and update `BOOSTY_VIEWER_BACKEND` to match.

## Ruff (lint + format)

[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting. Configuration: `ruff.toml`.

- **All lint rules enabled** (`ALL`) with selective ignores
- **Single quotes**, line length **88**
- Per-file relaxations: `test/*` allows `assert`, magic numbers, no docstrings; `scripts/*` allows `print()`

## Pyright (types)

[Pyright](https://github.com/microsoft/pyright) in **strict mode**, targeting Python 3.10.

The codebase uses `from __future__ import annotations` and `TYPE_CHECKING` blocks for type imports.

## Import Linter (layer boundaries)

[Import Linter](https://import-linter.readthedocs.io/) checks the layers `cli -> viewer -> application -> infrastructure -> domain`: a layer may import the layers below it, never the ones above. An additional contract forbids viewer imports from infrastructure; the viewer uses application ports and receives adapters from the CLI. Contracts live under `[tool.importlinter]` in `pyproject.toml`. Imports under `TYPE_CHECKING` count too.

## Command Reference

Tasks are grouped by the dev cycle: `setup` → `fix` → `check` → `test` → `build`. Run bare `task` for the grouped list.

| Command | What it does |
|---------|-------------|
| `task setup` | First-time dev setup (venv + deps + editor settings) |
| `task deps` | Install/sync dependencies (alias of `setup:deps`) |
| `task ci` | Python and UI checks, unit tests and package build |
| `task ui:e2e` | Browser checks against a temporary local viewer |
| `task fix` | Auto-fix lint and formatting, then type-check |
| `task lint` | Lint with auto-fix (alias of `fix:lint`) |
| `task format` | Apply formatting (alias of `fix:format`) |
| `task check` | Run all CI checks: lint + format + types + imports |
| `task check:lint` | Lint only, no fixes |
| `task check:format` | Check formatting without changes |
| `task check:types` | Type check |
| `task check:imports` | Check layer boundaries |
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
- The build backend is `hatchling`; package inclusion is configured under `[tool.hatch.build.targets]` in `pyproject.toml`.
