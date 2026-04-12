# Releasing

Releases are handled by a two-part process: a local script that bumps versions and updates the changelog, and a GitHub Actions workflow that publishes to PyPI and creates a GitHub Release.

## Step by Step

### 1. Verify the Changelog

Make sure `## Unreleased` in `CHANGELOG.md` has all changes for this release listed. This is the content that will appear in the GitHub Release notes.

### 2. Run the Release Script

```bash
make release v=patch    # 2.1.2 -> 2.1.3
make release v=minor    # 2.1.2 -> 2.2.0
make release v=major    # 2.1.2 -> 3.0.0
make release v=2.2.0    # explicit version
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

### 3. Review, Commit, Tag, Push

```bash
git diff                                  # review changes
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release v2.2.0"
git tag v2.2.0
git push && git push origin v2.2.0
```

### 4. Automated Publishing

Pushing the tag triggers `.github/workflows/release.yaml`, which:

1. **Validates** the release:
   - Tag version matches `pyproject.toml` version
   - `CHANGELOG.md` contains a `## X.Y.Z` heading for this version
   - Version doesn't already exist on PyPI
2. **Builds** the wheel and source distribution
3. **Publishes** to PyPI using trusted publishing (no API tokens needed)
4. **Creates a GitHub Release** with the changelog section as release notes and the dist artifacts attached

## Safety Checks

The release script prevents common mistakes:

| Check | Error |
|-------|-------|
| Invalid format | `expected major/minor/patch or X.Y.Z` |
| Version not higher than current | `must be higher than current X.Y.Z` |
| Version already in changelog | `version X.Y.Z already exists` |
| Missing `## Unreleased` heading | `section not found` |
| Empty `## Unreleased` section | `section is empty - nothing to release` |

Running the script twice with the same version is safe - it will refuse with an error.
