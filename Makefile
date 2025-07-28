.PHONY: build test 

help:
	@echo ------------------------- Available commands: ------------------------
	@echo deps            - Install project dependencies using poetry
	@echo build           - Build the project whl file 
	@echo ----------------------------------------------------------------------
	@echo test            - Run the project unit tests
	@echo test-verbose    - Run the project unit tests
	@echo ----------------------------------------------------------------------
	@echo dev-fix         - Try to fix code issues, show problems if any
	@echo ci-check        - Run CI checks (linter/formatter/type checks)
	@echo format          - Code format using ruff 
	@echo types           - Code type checks using pyright 
	@echo lint-check      - Code linting (only check)
	@echo lint-fix        - Code linting (try to fix)


# ------------------------------------------------------------------------------
# 📦 Distribution 

deps:
	poetry sync --no-interaction

build:
	poetry build 
	@echo Build complete at /dist/

# ------------------------------------------------------------------------------
# 🩺 Code Health Checks

dev-fix: lint-fix format types
ci-check: lint-check types format 

lint-check:
	poetry run ruff check .

lint-fix:
	poetry run ruff check --fix .

format:
	poetry run ruff format .
	
types:
	poetry run pyright


# ------------------------------------------------------------------------------
# 🧪 Testing 

test:
	poetry run pytest . 

test-verbose:
	poetry run pytest -v . 
