# Testing

The project uses [pytest](https://docs.pytest.org/) with [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) for async test support.

## Unit Tests

Located in `test/unit/`. Fast, no network access or credentials needed.

```bash
task test            # quick run
task test -- -v      # verbose output
```

### Running a Single Test

```bash
# specific file
poetry run pytest test/unit/download_manager/ok_video_ranking_test.py

# specific test function
poetry run pytest test/unit/path_test.py::test_specific_function -v
```

### File Naming Convention

Test files use the `_test.py` suffix (not `test_` prefix):

```
test/unit/
  download_manager/
    ok_video_ranking_test.py
  path_test.py
  filtering_test.py
```

## Integration Tests

Located in `test/integration/`. These hit the real Boosty API.

```bash
task test:api            # quick run
task test:api -- -v      # verbose output
```

Before pytest starts, a preflight script checks the config and makes one cheap live request. A missing `.env`, an unfilled key, or a stale token stops the run with a single hint on how to fix it.

### Credentials Setup

1. Copy the example env file:
   ```bash
   cp .env.example .env
   ```
2. Fill in your Boosty API credentials in `.env`

The `.env` file is gitignored. CI skips integration tests automatically when it's missing, so fork PRs pass without API access.

## Lint Relaxations

Tests have relaxed ruff rules (configured in `ruff.toml`):

| Rule | Why |
|------|-----|
| `D` (docstrings) | Tests are self-documenting by name |
| `S101` (assert) | pytest relies on assert statements |
| `PLR2004` (magic numbers) | Test values are used inline |
| `INP001` (__init__.py) | Test directories don't need it |

## API Analysis

A dev helper that dumps the raw posts JSON of the configured author - useful for debugging the Boosty API:

```bash
task posts-example
```
