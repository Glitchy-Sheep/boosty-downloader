# Structure

Tests are grouped by functionality ("domain"), not by the application structure:

```
test/
├── unit         - Unit tests for the application, grouped by "domains"
│   └── ...
│ 
└── integration  - Integration tests against the live Boosty API, grouped by "domains"
    └── flows    - End-to-end paths: credentials + author name -> domain-ready posts
```

To explore raw API responses, run the `task posts-example` dev helper.

# Add a new test

1. Decide whether it is a unit test or an integration test:
    - **Unit** tests are isolated and run anytime without setup.
    - **Integration** tests hit the live Boosty API and need `./.env` (see [Testing](../docs/development/02-testing.md)).
2. Decide which "domain" it belongs to - for example, `ok_video_ranking`.
3. Create the test file, following the naming convention `<filename>_test.py`.
4. Name the test function `test_<functionality>` and check outcomes with `assert`.
5. Run it: `task test` for unit tests, `task test:api` for integration tests.
6. Make a pull request (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
