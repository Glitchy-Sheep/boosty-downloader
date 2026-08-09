# Releasing

One release = one PR with the version bump, then a tag on main. The tag triggers the workflow that publishes to PyPI and creates the GitHub Release.

## Step by step

### 1. Check the changelog

`## Unreleased` in `CHANGELOG.md` must list everything for this release - these lines become the GitHub Release notes.

### 2. Branch and bump

```bash
git checkout -b release/vX.Y.Z
task release -- minor   # or: patch / major / X.Y.Z
```

The script (`scripts/release.py`) does two things:
- Updates `version` in `pyproject.toml`
- Promotes `## Unreleased` entries to a new `## X.Y.Z` heading and adds a fresh empty `## Unreleased` above it

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

### 3. Commit and open a PR

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release vX.Y.Z"
git push -u origin release/vX.Y.Z
```

Open the PR, wait for the four CI checks, merge. The ruleset lets changes into main only through PRs - the tag comes next, not a direct push.

### 4. Tag the merge commit on main

```bash
git checkout main && git pull
git tag vX.Y.Z
git push origin vX.Y.Z
```

Tag after the merge, on a fresh main: squash creates a new commit, so your local release commit is not the one on main.

### 5. The workflow does the rest

The `v*` tag triggers `.github/workflows/release.yaml`:

- **validate** - the tag matches `pyproject.toml`, the changelog has the `## X.Y.Z` section, the version is free on PyPI
- **build** - wheel and sdist
- **release** - publish to PyPI (trusted publishing, no tokens stored) and create the GitHub Release with the changelog section as notes

### 6. Verify

- [PyPI](https://pypi.org/project/boosty-downloader/) shows the new version
- The GitHub Releases page has `vX.Y.Z` with notes
- A fresh `pipx install boosty-downloader` gets the new version
