# 💖 Contributing to Boosty Downloader

Thanks for your interest in contributing! This guide will help you get started. For deeper technical details, see the [development docs](docs/development/).

## Table of Contents

- [Getting Started](#-getting-started)
- [Making Changes](#-making-changes)
- [Code Quality](#-code-quality)
- [Commit Messages](#-commit-messages)
- [Releasing (Maintainers)](#-releasing-maintainers)

## 🔧 Getting Started

1. Fork and clone the repository
2. Install the [Task](https://taskfile.dev) runner - per-OS commands are in [Dev Tools](docs/development/01-dev-tools.md)
3. Set up the environment (in-project venv + dependencies + editor settings):
   ```bash
   task setup
   ```
4. Run the project locally:
   ```bash
   uv run python -m boosty_downloader.main
   ```

All available commands are listed via bare `task`.

## 👩‍💻 Making Changes

This project uses **trunk-based development** - all changes go to `main` via short-lived branches and pull requests.

### Branch naming

Use prefixes that describe the type of change:

- `feat/` - new features (`feat/add-download-resume`)
- `fix/` - bug fixes (`fix/corrupted-video-output`)
- `refactor/` - code improvements (`refactor/simplify-api-client`)
- `docs/` - documentation (`docs/update-readme`)
- `chore/` - maintenance (`chore/update-dependencies`)

### Changelog

The project keeps a `CHANGELOG.md` with an `## Unreleased` section at the top. When your PR introduces a user-facing change, add a line there describing what changed.

CI verifies that new lines were **added** to the `## Unreleased` section - simply touching the file or removing entries won't pass. For PRs that don't need a changelog entry (CI fixes, refactoring, docs), add `[skip changelog]` to the PR title or use the `ci/skip-changelog` label.

## 🩺 Code Quality

```bash
task check    # Run all checks (lint + format + types)
task test     # Run unit tests
task fix      # Auto-fix lint and formatting, then type check
task ci       # Everything CI runs: checks + tests + build
```

The project uses:
- **Ruff** for linting and formatting (single quotes, 88 char line length)
- **Pyright** in strict mode for type checking
- **pytest** for testing

## 📝 Commit Messages

PRs are squash-merged, so the PR title becomes the commit on `main`. Write it as `[area] Imperative sentence`:

```
[cli] Add --config to point at a config file
[downloader] Skip a post with a gone external video without retries
[ci] Test matrix for Python 3.10-3.14 and Windows, weekly API canary
```

The area is the part of the project the change is about: `cli`, `downloader`, `html`, `cache`, `application`, `ci`, `tests`, `build`, `docs`, `scripts`. Release PRs keep the `chore: release vX.Y.Z` title that `task release` gives them.

The PR description follows the [PR template](.github/pull_request_template.md).

Describe not only **what** changed, but **why**.

## 🚀 Releasing (Maintainers)

1. Make sure `## Unreleased` in CHANGELOG.md has all changes listed
2. Run the release wizard:
   ```bash
   task release -- patch   # or: minor / major / X.Y.Z
   ```
   It checks the tools and the repo invariants, shows a preview and - after your confirmation - bumps the version, promotes the changelog, pushes the release branch and opens the release PR.
3. Merge the release PR.
4. Tag from fresh main:
   ```bash
   git checkout main
   task release:tag
   ```

The tag triggers the release workflow: build -> PyPI -> GitHub Release. The full flow with every check explained: [Releasing](docs/development/04-releasing.md).
