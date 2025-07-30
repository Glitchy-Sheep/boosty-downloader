.PHONY: build test 

help:
	@echo ------------------------- To run locally: ----------------------------
	@echo Run make deps to install dependencies
	@echo And to run current project locally without installation:
	@echo   poetry run python -m boosty_downloader.main
	@echo .                                                                    .
	@echo ------------------------- Available commands: ------------------------
	@echo Building:
	@echo   deps             - Install project dependencies using poetry
	@echo   build            - Build the project whl file 
	@echo ----------------------------------------------------------------------
	@echo Testing:
	@echo   test             - Run the project unit tests
	@echo   test-verbose     - Run the project unit tests
	@echo   test-api         - Run the project API integration tests
	@echo   test-api-verbose - Run the project API integration tests with verbose output
	@echo ----------------------------------------------------------------------
	@echo Code Health:
	@echo   dev-fix          - Try to fix code issues, show problems if any
	@echo   ci-check         - Run CI checks (linter/formatter/type checks)
	@echo   types            - Code type checks using pyright 
	@echo   format-check     - Code format check using ruff
	@echo   format-fix       - Code format using ruff 
	@echo   lint-check       - Code linting (only check)
	@echo   lint-fix         - Code linting (try to fix)


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
