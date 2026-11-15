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

Changes use short-lived task branches and pull requests, with two integration branches:

- `main` maintains the current 4.x downloader. Start maintenance work from `main` and target it in the PR.
- `feat/v5` combines the new library storage and viewer. Start v5 tasks from `feat/v5` and target it in the PR.

Shared fixes and dependency updates land in `main` first, then merge into `feat/v5`. When v5 is complete, it returns to `main` through a final reviewed PR.

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

PRs are squash-merged, so the PR title becomes the commit on the target branch. Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) with the area of the project in parentheses:

```
feat(cli): add --config to point at a config file
fix(downloader): skip a post with a gone external video without retries
refactor(application): declare ports and build the app in a composition root
```

- Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `ci`, `build`, `chore`.
- Areas: `cli`, `downloader`, `html`, `cache`, `application`, `api`, `config`, `scripts`, `deps`. Skip the area when the change has none, e.g. `ci: test on Windows`.
- Release PRs keep the `chore: release vX.Y.Z` title that `task release` gives them.

The PR description follows the [PR template](.github/pull_request_template.md).

Describe not only **what** changed, but **why**.

## 🚀 Releasing (Maintainers)

Releases are cut from `main`. Merge the completed `feat/v5` branch into `main` before starting the v5.0.0 release.

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
