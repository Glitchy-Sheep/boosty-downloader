## Unreleased

### Fixed

- Rendered posts look right in the browser and in the editor: the tab shows the post title instead of "HTML Report", numbered lists keep their numbering instead of turning into bullets, and post.html itself is ~2.5x smaller with properly indented markup instead of walls of blank lines
- A file whose name contains HTML markup (like `report <final>.zip`) no longer breaks the post page - names are escaped now
- External videos saved as webm/mkv get a matching MIME type in the player instead of a hardcoded mp4 one
- Already downloaded posts keep their old HTML: the new rendering applies to new and updated posts (a full re-render command is planned separately)

- Long runs no longer die on expired download links: when the CDN rejects a link that lived past its ~24-hour signature, the post is re-fetched from the API once and the download retries with fresh links - no manual rerun needed
- New Boosty video url types `ondemand_dash` / `ondemand_hls` no longer trigger the "please report this at GitHub" warning - the client knows them now
- A video that offers only streaming manifests (hls/dash/live) is skipped with an honest "streams are not supported yet" warning and retried on the next run; a manifest can no longer end up on disk pretending to be a video file

### Changed

- The app now exits with code 1 on every handled error (author not found, bad credentials, network failure, stopped run) and 130 on Ctrl+C - scripts and cron jobs can finally tell a failed run from a successful one
- `--post-url` finds the post with one direct API request instead of walking the whole blog page by page - instant start and download links that are always fresh; a paywalled post without access now says so instead of saving an empty preview

## 3.4.0

### Added

- Debug log now tells what happened to every request, not only that it started: outcome lines with status and timing (`-> 200 in 0.31s`) or the error chain (`-> FAIL ClientConnectorError <- ConnectionResetError in 12.1s`), dns/connect phase timings, retry attempt numbers (`attempt 2/5`), and a live `connecting...` line - a hang or a killed handshake is readable straight from the log

### Fixed

- Long post titles no longer crash the download with "File name too long" (#93, #88): folder and file names are cut to fit the filesystem limit, and the post date, the dedup id and the file extension always survive the cut
- If the full path is still too long for the OS (a deep destination folder on Windows), the error now says what to do: move the destination folder closer to the drive root
- Titles with dots keep them: a post named "v2.0" no longer turns into "v20"

### Changed

- Single-post downloads (`--post-url`) now name the folder the same way as the full run: `date - title (id)` - the id tail keeps same-titled posts apart
- Debug log now keeps query keys in logged URLs (`?sig=...&expire=...` instead of cutting the query off) - easier to match a failing request to an endpoint, values stay hidden
- Already downloaded posts are untouched: folders are never renamed, a new-style name appears only when an updated post is re-downloaded

## 3.3.0

### Added

- `--debug` flag writes `boosty-downloader-debug.log`: app version, platform, every request and full error tracebacks - attach it to bug reports; download links are logged without their signed keys, so the file is safe for public issues

### Fixed

- Network errors now say what actually broke instead of a generic connection message: a DNS failure names the host and suggests trying another DNS or a VPN that covers all apps (#109)

## 3.2.0

### Added

- `--version` / `-V` flag shows the installed version
- `--skip-all-failures` flag: skip failed posts without limit instead of stopping after 5 failures in a row

### Fixed

- Files and audio keep exactly the name the author uploaded - no more archive.zip turning into archive.bin (#75); images finally get an extension (.png/.jpg) instead of a bare uuid
- The app can no longer hang forever: a silent server connection now times out and goes through the usual retries, and an unreachable PyPI delays startup by 5 seconds at most
- A broken config.yaml is reported with exact fields and line numbers instead of being silently replaced - the saved token survives
- Multiple videos in one post no longer overwrite each other: filenames carry the video id, like `My stream (a2dd6942)` (#104)
- One broken post no longer kills the whole download: it is skipped into failed_downloads.log and the run summary, and 5 failures in a row stop the run early with a resume hint (#88)

## 3.1.0

### Added

- Survive unknown Boosty content: new types and values are kept, skipped where needed, and listed in a final summary with exact paths instead of crashing the whole download

### Fixed

- Crash on failed downloads: a readable error message instead of an AttributeError traceback (#105, #89)
- Running download/check without --username: clear "Missing option" error and exit code 2 instead of a crash
- Confusing "Unknown error" for a wrong username: clear "author not found" message and a hint about the blog name (#94)
- Broken posts no longer fail the whole page: they are skipped with a readable warning, and validation errors are shown as short lines instead of raw dumps
- clean-cache says when there was no cache to clean instead of reporting a false success

### Security

- Update yt-dlp to 2026.7.4: fixes external video downloading and closes a security advisory

## 3.0.0

- MAJOR: New way of calling commands (use subcommands for different scenario)
- Add `show-auth-script` subcommand for extracting auth credentials via browser console

## 2.2.0

- Add `--cache-dir` flag to store cache database separately from downloads (for network storage setups)

## 2.1.2

- Fix the empty title bug (the downloading process stopped because of validation error)

## 2.1.1

- Fix crash when processing unfinished uploads; they are now skipped gracefully

## 2.1.0

- Added support for audio downloading and html rendering 
- Added database migration support for painless application migrations/updates

## 2.0.1 

- 🐛 Fixed image data so posts download even when width/height is missing
- 🐛 Fixed download process to stop automatically after the chosen post

## 2.0.0

### ⛔ BREAKING CHANGES ⛔

- Because of the new caching system, the cache database changed.
  If you have an existing cache, you may need to clean it first to avoid issues.

  The utility will automatically detect cache inconsistencies and prompt you to clean it though.

  I tried to figgure some sort of db migration but it is too complex for the current state of the project, so I decided to just make it a breaking change yet.

  If you know how I can keep migrating the cache given the fact that dbs are 
  scattered across multiple author directories, and even possibly have different versions 
  please let me know with an issue!

- Some options were renamed but their functionality remains the same

### 🔔 New Features

- 🔔 **Automatic Update Checker**  
  You'll now be notified when a new version is available on PyPI.

- 📦 **Improved Caching Layer**
  - Only the requested parts are cached to avoid unnecessary re-downloads/skips (before this change the post was cached entirely not just the requested parts), so now partial updates are possible.
  - Cache is properly **invalidated** if a post is updated by its author (will be re-downloaded).
  - More **robust and accurate** caching system: better handling of missing post parts.

- **HTML Generation Enhancements**
  - New **HTML generator engine** with support for **Dark/Light modes**. 🦉
  - Added support for **headings and lists** in HTML output.
  - Added better support for styling (italic/bold/etc)
  - `post_content` now includes both **images AND videos** (offline only).

- **Improved CLI UX**
  - New destination option to allow override config values.
  - Better help descriptions with logical **option grouping**.
  - More informative **post counter**: displays both accessible and inaccessible posts, with names listed for all inaccessible posts.
  - Enhanced **logging and error handling** for a more readable and helpful output.

- **Retry Logic**
  - If post download fails, it will be retried up to 5 times with exponential backoff.
  - After 5 failed attempts, the post will be skipped and not cached.

### 🐛 Fixes

- Fixed duplication problem [#12](https://github.com/Glitchy-Sheep/boosty-downloader/issues/12) (now posts are cached by UUID and have it as part of the filename, so duplication is no longer an issue)
- Fixed external video downloading for unsupported formats (now format >=720p is preferred, less otherwise).
- Fixed HTML generation for posts with **no content**, now it won't be created.
- Resolved issues with **newline handling** in some HTML outputs.
- Fixed **Ctrl+C interruption** handling with proper cleanup and messaging.
- Prevented creation of **empty directories** for posts with no downloadable content.
  now the utility do the job only if there is one.
    
### 🧹 Miscellaneous

- Internal **project structure refactored** for better maintainability and scalability.

## 1.0.1
- Fix: 🐛 Support new boosty API response schema (as a placeholder)

## 1.0.0

- First stable release
- Main downloader functions such as video/post/external_video/files
- Added CLI interface with typer (with customizable options)
