.PHONY: build test posts-example release

# Ensure that all the pipe-like commands work correctly.
export PYTHONIOENCODING = utf-8

help:
	@echo '------------------------- To run locally: ----------------------------'
	@echo 'Run make deps to install dependencies'
	@echo 'And to run current project locally without installation:'
	@echo '   poetry run python -m boosty_downloader.main'
	@echo .                                                                    .
	@echo '------------------------- Available commands: ------------------------'
	@echo 'Building:'
	@echo '   deps             - Install project dependencies using poetry'
	@echo '   build            - Build the project whl file'
	@echo ----------------------------------------------------------------------
	@echo 'Code Health:'
	@echo '   dev-fix          - Try to fix code issues, show problems if any'
	@echo '   ci-check         - Run CI checks (lint/formatter/type checks)'
	@echo '   types            - Code type checks using pyright'
	@echo '   format-check     - Code format check using ruff'
	@echo '   format-fix       - Code format using ruff'
	@echo '   lint-check       - Code linting (only check)'
	@echo '   lint-fix         - Code linting (try to fix if possible)'
	@echo ----------------------------------------------------------------------
	@echo 'Endpoints Analysis (Only work if integration tests config available):'
	@echo '   posts_example    - Show posts json for defined author'
	@echo ----------------------------------------------------------------------
	@echo 'Release:'
	@echo '   release v=X.Y.Z  - Bump version, update changelog, commit and tag'



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
#   4. Commits both files and creates a git tag
#   5. Prints the push command (push is manual for safety)
#
# Before:                        After:
#   ## Unreleased                   ## Unreleased
#   - Fixed something               (empty)
#   ## 2.1.2                        ## 2.1.3
#                                   - Fixed something
#                                   ## 2.1.2

release:
	@if [ -z "$(v)" ]; then echo "Usage: make release v=X.Y.Z"; exit 1; fi
	@echo "📦 Releasing version $(v)..."
	@echo ""
	sed -i 's/^version = ".*"/version = "$(v)"/' pyproject.toml
	sed -i 's/^## Unreleased$$/## $(v)/' CHANGELOG.md
	sed -i '/^## $(v)$$/i ## Unreleased\n' CHANGELOG.md
	@echo "✅ Version bumped and changelog updated."
	@echo ""
	@echo "📋 Next steps:"
	@echo "  1. Review the changes:  git diff"
	@echo "  2. Stage and commit:    git add pyproject.toml CHANGELOG.md && git commit -m 'chore: release v$(v)'"
	@echo "  3. Create tag:          git tag v$(v)"
	@echo "  4. Push:                git push && git push origin v$(v)"

