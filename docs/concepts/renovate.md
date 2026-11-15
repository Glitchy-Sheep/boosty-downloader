# Renovate: how we work with the dependency bot

Renovate watches every dependency of this repo and turns "a new version is out" into a pull request. CI proves the update is safe; the bot merges the safe categories itself.

## What merges itself (on green CI only)

- Python dev tools (ruff, pyright, pytest, ...) - they never reach users. Grouped into one "dev tools" PR.
- GitHub Actions updates - they only change CI.
- Lockfile-only bumps - users already get these versions on install, the PR only aligns dev/CI.
- Security fixes - created immediately, ignoring the schedule.
- `yt-dlp` - CalVer that fixes YouTube weekly; its range widens instead of getting capped.

## What waits for a human

- Range changes in `pyproject.toml` (except `yt-dlp`): they change what users install.
- Routine viewer package version changes: npm groups organize the PRs without enabling new automerge categories.
- Majors: they don't even open a PR until you tick their checkbox in the dependency dashboard.

## Viewer updates

Direct dependencies and development tools in `viewer-ui/package.json` use exact versions. An npm-only `pin` strategy preserves that policy while updating both the package file and lockfile. Node engine ranges are excluded from this rule. The global `update-lockfile` strategy continues to govern Python dependencies.

Related npm updates arrive in three groups: TanStack, Radix and shadcn, and Vite with its plugins. Other viewer packages retain their normal Renovate grouping. The final major-version rule still requires dashboard approval and disables automerge, including for these groups.

Renovate targets `main` only. Viewer updates start after the frontend and its configuration reach that branch; the bot does not maintain `feat/v5` separately.

## The dashboard

Issue [#37](https://github.com/Glitchy-Sheep/boosty-downloader/issues/37) is the bot's control panel: rate-limited updates wait there with checkboxes, majors sit there until approved. Tick a checkbox - the bot opens the PR.

## Day-to-day

- A bot PR is green but didn't merge itself? That category wants your eyes: review the version delta and merge.
- Need a PR refreshed after main moved? Tick the "rebase" checkbox in the PR body.
- The config lives in `.github/renovate.json5` - json5, so every choice carries an inline comment. Validate changes with `npx --yes --package renovate -- renovate-config-validator --no-global .github/renovate.json5`.

## The safety chain

Automerge fires only after the CI checks on the PR pass. The branch ruleset should also require the CI checks, including the viewer job, so nobody can merge red by hand either.
