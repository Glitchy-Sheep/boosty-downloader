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
