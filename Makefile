.PHONY: build test posts-example release help setup

# Ensure that all the pipe-like commands work correctly.
export PYTHONIOENCODING = utf-8

help:
	-@chcp 65001 > nul 2>&1
	@echo ''
	@echo '  Boosty Downloader - Development Commands'
	@echo ''
	@echo '  🚀 Quick start:'
	@echo '    make setup                                   first-time dev setup (venv + deps + editor)'
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
	@echo '    make build-install   build and install locally for testing'
	@echo ''
	@echo '  🏷️  Release:'
	@echo '    make release v=patch   auto-bump patch (2.1.2 -> 2.1.3)'
	@echo '    make release v=minor   auto-bump minor (2.1.2 -> 2.2.0)'
	@echo '    make release v=major   auto-bump major (2.1.2 -> 3.0.0)'
	@echo '    make release v=2.2.0   or set version explicitly'
	@echo ''
	@echo '  🔍 Analysis:'
	@echo '    make posts-example   show posts JSON for configured author'
	@echo ''


# ------------------------------------------------------------------------------
# 📦 Distribution

deps:
	poetry sync --no-interaction

# First-time developer setup: the venv lives inside the project (./.venv),
# so editors and CI resolve the same interpreter path. Generates VS Code
# settings pointing at it - the file is gitignored, hence generated here.
setup:
	poetry config virtualenvs.in-project true --local
	poetry sync --no-interaction
	@mkdir -p .vscode
	@if [ -f .vscode/settings.json ]; then \
		echo '.vscode/settings.json exists - check python.defaultInterpreterPath points to .venv'; \
	else \
		printf '{\n    "python.defaultInterpreterPath": "$${workspaceFolder}/.venv/bin/python"\n}\n' > .vscode/settings.json; \
		echo 'Created .vscode/settings.json'; \
	fi
	@echo 'Done. In VS Code: "Python: Select Interpreter" -> ./.venv/bin/python'

build:
	poetry build --no-cache
	@echo Build complete at /dist/

build-install:
	@python scripts/build_install.py

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
# Usage:
#   make release v=patch         auto-bump patch (2.1.2 -> 2.1.3)
#   make release v=minor         auto-bump minor (2.1.2 -> 2.2.0)
#   make release v=major         auto-bump major (2.1.2 -> 3.0.0)
#   make release v=2.2.0         explicit version
#
# The script (scripts/release.py) validates inputs, bumps pyproject.toml,
# promotes the Unreleased changelog section, and prints next steps.

release:
	@python scripts/release.py $(v)
