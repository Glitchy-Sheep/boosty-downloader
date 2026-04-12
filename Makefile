.PHONY: build test posts-example release help

# Ensure that all the pipe-like commands work correctly.
export PYTHONIOENCODING = utf-8

help:
	-@chcp 65001 > nul 2>&1
	@echo ''
	@echo '  Boosty Downloader - Development Commands'
	@echo ''
	@echo '  🚀 Quick start:'
	@echo '    make deps                                    install dependencies'
	@echo '    poetry run python -m boosty_downloader.main  run locally'
	@echo ''
	@echo '  🩺 Code quality:'
	@echo '    make ci-check        run all CI checks (lint + types + format)'
	@echo '    make dev-fix         auto-fix lint and formatting issues'
	@echo '    make lint-check      lint only (ruff)'
	@echo '    make lint-fix        lint and fix (ruff)'
	@echo '    make format-check    check formatting (ruff)'
	@echo '    make format-fix      fix formatting (ruff)'
	@echo '    make types           type check (pyright)'
	@echo ''
	@echo '  🧪 Testing:'
	@echo '    make test            run unit tests'
	@echo '    make test-verbose    run unit tests (verbose)'
	@echo '    make test-api        run integration tests (requires .env)'
	@echo ''
	@echo '  📦 Building:'
	@echo '    make build           build wheel and source distribution'
	@echo ''
	@echo '  🏷️  Release:'
	@echo '    make release v=X.Y.Z    bump version, update changelog'
	@echo ''
	@echo '  🔍 Analysis:'
	@echo '    make posts-example   show posts JSON for configured author'
	@echo ''


# ------------------------------------------------------------------------------
# 📦 Distribution

deps:
	poetry sync --no-interaction

build:
	poetry build --no-cache
	@echo Build complete at /dist/

# ------------------------------------------------------------------------------
# 🩺 Code Health Checks

dev-fix: lint-fix format-fix types
ci-check: lint-check types format-check

lint-check:
	poetry run ruff check .

lint-fix:
	poetry run ruff check --fix .

format-check:
	poetry run ruff format --check .

format-fix:
	poetry run ruff format .

types:
	poetry run pyright


# ------------------------------------------------------------------------------
# 🧪 Testing

test:
	poetry run pytest test/unit/

test-verbose:
	poetry run pytest -v test/unit/

test-api:
	poetry run pytest test/integration/

test-api-verbose:
	poetry run pytest -v test/integration/

# ------------------------------------------------------------------------------
# 🔍 Endpoints analysis

posts-example:
	poetry run pytest ./test/integration/analysis/get_author_posts_test.py::test_get_author_posts -s -q

# ------------------------------------------------------------------------------
# 🚀 Release
#
# Usage: make release v=2.1.3
#
# What it does:
#   1. Updates version in pyproject.toml (e.g. version = "2.1.2" -> "2.1.3")
#   2. Renames "## Unreleased" heading in CHANGELOG.md to the new version
#   3. Adds a fresh empty "## Unreleased" section above it
#   4. Prints next steps (commit, tag, push are manual)
#
# Before:                        After:
#   ## Unreleased                   ## Unreleased
#   - Fixed something               (empty)
#   ## 2.1.2                        ## 2.1.3
#                                   - Fixed something
#                                   ## 2.1.2

release:
	@if [ -z "$(v)" ]; then echo "Usage: make release v=X.Y.Z"; exit 1; fi
	@echo ""
	@echo   Releasing version $(v)...
	@echo ""
	@sed -i 's/^version = ".*"/version = "$(v)"/' pyproject.toml
	@sed -i 's/^## Unreleased$$/## $(v)/' CHANGELOG.md
	@sed -i '/^## $(v)$$/i ## Unreleased\n' CHANGELOG.md
	@echo   Version bumped and changelog updated.
	@echo ""
	@echo   Next steps:
	@echo     1. Review the changes:  git diff
	@echo     2. Stage and commit:    git add pyproject.toml CHANGELOG.md
	@echo                             git commit -m "chore: release v$(v)"
	@echo     3. Create tag:          git tag v$(v)
	@echo     4. Push:                git push && git push origin v$(v)
	@echo ""
