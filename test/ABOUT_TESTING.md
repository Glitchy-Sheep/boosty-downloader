# Structure 

Tests structure doesn't mirror the application structure, but rather groups tests by their functionality or "domain":

```
test/
├── unit         - Unit tests for the application, grouped by "domains"
│   └── ...
│ 
└── integration  - Integration tests against the live Boosty API, grouped by "domains"
    └── analysis - Dumps for exploring known endpoints
```

# Add a new test 

**If you want to add a new test:**
1. *Decide whether it is a unit test or an integration test.*
    - **Integration** tests depends on external services (Boosty) or network, can be configurable.
    - **Unit** tests are isolated and can be run any time without configuration or setup.
2. *Decide which "domain" it belongs to*
    - For example ok_video_ranking is the boosty_downloader's domain.
3. *Create test file, following the naming convention `<filename>_test.py`.*
4. Test some functionality with `test_<functionality>` function name.
    - Use `assert` statements to check expected outcomes.
5. *Run the test using `task test` for unit tests or `task test:api` for integration tests (they need `./.env`, see [Testing](../docs/development/02-testing.md)).*
6. *Make a pull request with your changes.* (see [CONTRIBUTING.md](../CONTRIBUTING.md) for more details)
