# Releasing

One release = one PR with the version bump, then a tag on main. The tag triggers the workflow that publishes to PyPI and creates the GitHub Release.

## Step by step

### 1. Check the changelog

`## Unreleased` in `CHANGELOG.md` must list everything for this release - these lines become the GitHub Release notes, word for word.

The section fills up during development: the 📝 Changelog CI job requires every PR to add its entries (infra PRs skip it with the `ci/skip-changelog` label). Write entries about the effect for the user, not the mechanics, and group them under `### Added` / `### Fixed` / `### Security` - the grouping survives all the way to the release page.

### 2. Run the wizard

```bash
task release -- minor   # or: patch / major / X.Y.Z
```

Start from `main` (the wizard fast-forwards it) or from an existing `release/vX.Y.Z` branch - on any other branch the wizard offers to switch to `main` itself (only when the tree is clean, so no local edits travel between branches). Before touching anything the wizard verifies: `git` and `gh` present and authorized, clean tree (only `CHANGELOG.md` edits are allowed - they ride in the release commit), non-empty `## Unreleased`, the version is free on PyPI, the tag does not exist. Then it shows a preview panel and, after your confirmation:

- Creates `release/vX.Y.Z` (when starting from `main`)
- Updates `version` in `pyproject.toml`
- Promotes `## Unreleased` entries to a new `## X.Y.Z` heading and adds a fresh empty `## Unreleased` above it
- Commits, pushes and opens the release PR (assignee: you, label `ci/skip-changelog` - the release PR empties `Unreleased` instead of adding to it)

**Before:**
```markdown
## Unreleased

- Add audio downloading support
- Fix crash on empty posts

## 2.1.2
...
```

**After:**
```markdown
## Unreleased

## 2.2.0

- Add audio downloading support
- Fix crash on empty posts

## 2.1.2
...
```

### 3. Merge the PR

Wait for the CI checks, merge. The ruleset lets changes into main only through PRs - the tag comes next, not a direct push.

### 4. Tag the merge commit on main

```bash
task release:tag
```

The wizard offers to switch to `main` when you are still on another branch, pulls fresh main, verifies the version, the changelog section and the tag, shows what will be tagged and pushes `vX.Y.Z` after confirmation. After the push it prints the direct link to the workflow run it has just started (or the runs list, when GitHub is slow to spawn it). Tagging happens on fresh main because squash creates a new commit - your local release commit is not the one on main.

### 5. The workflow does the rest

The `v*` tag triggers `.github/workflows/release.yaml`:

- **validate** - the tag matches `pyproject.toml`, the changelog has the `## X.Y.Z` section, the version is free on PyPI
- **build** - wheel and sdist
- **release** - publish to PyPI (trusted publishing, no tokens stored) and create the GitHub Release with the changelog section as notes

### 6. Verify

- [PyPI](https://pypi.org/project/boosty-downloader/) shows the new version
- The GitHub Releases page has `vX.Y.Z` with notes
- A fresh `pipx install boosty-downloader` gets the new version
