# Structure

Tests are grouped by functionality ("domain"), not by the application structure:

```
test/
├── unit         - Unit tests, one folder per domain (boosty_api, mappers, use_cases, cli/views, ...)
├── e2e          - Whole download runs against a local Boosty-shaped server, no network
├── integration  - Tests against the live Boosty API with credentials from ./.env
│   └── flows    - End-to-end paths: credentials + author name -> domain-ready posts
├── canary       - The live Boosty API without credentials: does the client still understand it
└── support      - Shared helpers: the synthetic Boosty post, checked against docs/api/boosty-api.yaml
```

`task test` runs unit and e2e tests. Integration and canary tests need the network: `task test:api` and `CANARY_AUTHOR=<blog> task test:canary`. Details: [Testing](../docs/development/02-testing.md).

To explore raw API responses, run the `task posts-example` dev helper.

# Add a new test

1. Decide where it belongs:
    - **Unit**: one function or class, no network, no disk beyond `tmp_path`. Most tests live here.
    - **e2e**: a whole run through the real client, downloader, cache and renderer against the local server in `test/e2e/download_flow_test.py`. For behaviour that only shows when the parts work together.
    - **Integration**: the live API with credentials. Only for what the local server cannot prove.
2. Decide which "domain" it belongs to - for example, `ok_video_ranking`.
3. Create the test file, following the naming convention `<filename>_test.py`.
4. Name the test function `test_<what it proves>` and check outcomes with `assert`. A test needs a failure story: which bug would turn it red.
5. Run it: `task test` for unit and e2e tests, `task test:api` for integration tests.
6. Make a pull request (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
