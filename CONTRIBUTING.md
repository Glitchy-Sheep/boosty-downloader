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
2. Install dependencies:
   ```bash
   make deps
   ```
3. Run the project locally:
   ```bash
   poetry run python -m boosty_downloader.main
   ```

All available commands are listed via `make help`.

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
make ci-check    # Run all checks (lint + types + format)
make test        # Run unit tests
make dev-fix     # Auto-fix lint and formatting issues
```

The project uses:
- **Ruff** for linting and formatting (single quotes, 88 char line length)
- **Pyright** in strict mode for type checking
- **pytest** for testing

## 📝 Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
feat: add audio downloading support
fix: handle posts with missing titles
chore: update dependencies
```

Describe not only **what** changed, but **why**.

## 🚀 Releasing (Maintainers)

1. Make sure `## Unreleased` in CHANGELOG.md has all changes listed
2. Run:
   ```bash
   make release v=patch   # 2.1.2 -> 2.1.3
   make release v=minor   # 2.1.2 -> 2.2.0
   make release v=major   # 2.1.2 -> 3.0.0
   make release v=2.2.0   # explicit version
   ```
3. Review the diff, stage and commit:
   ```bash
   git diff
   git add pyproject.toml CHANGELOG.md
   git commit -m "chore: release vX.Y.Z"
   ```
4. Tag and push:
   ```bash
   git tag vX.Y.Z
   git push && git push origin vX.Y.Z
   ```

The release workflow will automatically publish to PyPI and create a GitHub Release.

The script validates that the new version is higher than the current one, the `## Unreleased` section exists and is not empty, and prevents releasing the same version twice.
