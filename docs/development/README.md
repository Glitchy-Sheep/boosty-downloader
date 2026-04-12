# Development Guide

Detailed documentation on the project's tooling, CI, and release process. For a quick onboarding, start with [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Reading Order

Start here, then follow the documents in order - each builds on the previous:

1. **[Dev Tools](01-dev-tools.md)** - setup your environment and learn the commands
2. **[Testing](02-testing.md)** - run and write tests
3. **[CI Pipeline](03-ci.md)** - understand what happens when you open a PR
4. **[Releasing](04-releasing.md)** - how versions get published (maintainers)

## Project Structure

```
boosty_downloader/
  main.py                    # Entry point
  src/
    domain/                  # Pure data models (Post, PostDataChunks)
    application/             # Business logic, use cases, DI
    infrastructure/          # API client, caching, HTML rendering, yt-dlp
    cli/                     # Typer CLI options, progress reporter
scripts/
  release.py                 # Release automation script
test/
  unit/                      # Fast tests, no network
  integration/               # API tests, require .env credentials
```

Architecture diagram: [general_project_structure.excalidraw.svg](../general_project_structure.excalidraw.svg)
