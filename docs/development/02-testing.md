# Testing

The project uses [pytest](https://docs.pytest.org/) with [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) in auto mode: async tests need no marker.

## Layout

| Folder | What runs there | Needs | Command |
|--------|-----------------|-------|---------|
| `test/unit/` | Unit tests, one folder per domain (`boosty_api`, `mappers`, `use_cases`, `cli/views`, ...) | nothing | `task test` |
| `test/e2e/` | Whole download runs against a local Boosty-shaped server: the real client, downloader, cache and renderer | nothing | `task test` |
| `test/integration/` | The live Boosty API with your credentials | `./.env` | `task test:api` |
| `test/canary/` | The live Boosty API without credentials: does the client still understand the answer | `CANARY_AUTHOR` | `task test:canary` |
| `test/support/` | Shared helpers: the synthetic Boosty post | - | - |

`task test` runs unit and e2e tests (pytest's `testpaths`); `task test:cov` adds a coverage report. Integration and canary tests need the network and run only when their path is given.

## Running a Single Test

```bash
# one file
uv run pytest test/unit/path_sanitizer/path_sanitizer_test.py

# one test function
uv run pytest test/unit/path_sanitizer/path_sanitizer_test.py::test_long_cyrillic_title_fits_the_byte_limit -v
```

Test files use the `_test.py` suffix (not the `test_` prefix), one folder per domain under `test/unit/`.

## Test Data

The test tree holds no data captured from the live API and no golden files.

- `test/support/synthetic_post.py` builds a post with every chunk kind in code. Unit and e2e tests use it.
- `test/unit/synthetic_data/` checks it against `docs/api/boosty-api.yaml`, the observed shape of the API: every key must exist there with the observed type and values. When Boosty changes, regenerate the schema (see [docs/api](../api/README.md)) and the check shows what the synthetic post must follow.
- The same folder fails on real post ids and real Boosty links anywhere in the tests.
- Rendered pages and console views are checked by the lines that matter, not byte by byte.

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

## Canary

`test/canary/` reads one page of a public blog without credentials and checks that every post parses, nothing in the answer is unknown to the client, and an open post carries content. CI runs it weekly and opens an issue when it fails (see [CI](03-ci.md)). Locally:

```bash
CANARY_AUTHOR=<blog> task test:canary
```

## Lint Relaxations

Tests have relaxed ruff rules (configured in `ruff.toml`):

| Rule | Why |
|------|-----|
| `D` (docstrings) | Tests are self-documenting by name |
| `ANN201` (return annotation) | Test functions always return None |
| `S101` (assert) | pytest relies on assert statements |
| `PLR2004` (magic numbers) | Test values are used inline |
| `INP001` (__init__.py) | Test directories don't need it |
| `SLF001` (private access) | Tests exercise private helpers directly |

## API Analysis

A dev helper that dumps the raw posts JSON of the configured author - useful for debugging the Boosty API:

```bash
task posts-example
```
