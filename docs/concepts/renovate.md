# Renovate: how we work with the dependency bot

Renovate watches every dependency of this repo and turns "a new version is out" into a pull request. CI proves the update is safe; the bot merges the safe categories itself.

## What merges itself (on green CI only)

- Dev tools (ruff, pyright, pytest, ...) - they never reach users. Grouped into one "dev tools" PR.
- GitHub Actions updates - they only change CI.
- Lockfile-only bumps - users already get these versions on install, the PR only aligns dev/CI.
- Security fixes - created immediately, ignoring the schedule.
- `yt-dlp` - CalVer that fixes YouTube weekly; its range widens instead of getting capped.

## What waits for a human

- Range changes in `pyproject.toml` (except `yt-dlp`): they change what users install.
- Majors: they don't even open a PR until you tick their checkbox in the dependency dashboard.

## The dashboard

Issue [#37](https://github.com/Glitchy-Sheep/boosty-downloader/issues/37) is the bot's control panel: rate-limited updates wait there with checkboxes, majors sit there until approved. Tick a checkbox - the bot opens the PR.

## Day-to-day

- A bot PR is green but didn't merge itself? That category wants your eyes: review the version delta and merge.
- Need a PR refreshed after main moved? Tick the "rebase" checkbox in the PR body.
- The config lives in `.github/renovate.json5` - json5, so every choice carries an inline comment. Validate changes with `npx --package renovate -- renovate-config-validator`.

## The safety chain

Automerge fires only after the CI checks on the PR pass. The branch ruleset should also require the four CI jobs, so nobody can merge red by hand either.
