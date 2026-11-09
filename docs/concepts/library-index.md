# The library index

The JSON records and downloaded files are the source of truth. `LibraryIndex` builds a disposable SQLite database for library browsing and search. Losing this database does not lose downloaded content or viewing marks: it can be rebuilt from `post.json`, `viewer.json`, `author.json` and `locked.json`.

## What it stores

The index contains authors, posts, tags, media and full-text search rows. Post identity includes the author and full post ID. Media identity also includes the post ID, because the same media ID can occur in different posts. Saved viewing marks and playback positions belong to the corresponding post.

A locked observation updates the displayed metadata and access state while keeping any saved body, media and marks. Media counts describe pieces in the current body. Retained downloaded pieces that the author removed remain indexed for storage accounting. Cover paths are derived from available saved images, video previews and locked teasers.

Search keeps original plain text for display and folded text for matching, including `ё` to `е`. It indexes user content, without page-template labels. File modification times and sizes are recorded alongside each canonical source for later synchronization.

## Reads and rebuilds

The scanner reads recognized author and post records directly, with their existing schema validation. It does not search the author directory again for each post or walk every media file. Only candidate cover files are inspected; recorded sizes support storage accounting. Contained source aliases are allowed, but sources escaping the library and conflicting full post identities are rejected.

`LibraryIndex` construction performs no I/O. `status()` checks the schema and data pages; `ensure()` rebuilds a missing, incompatible or corrupt index. Call `ensure()` when preparing a run. The database records its schema version and resolved library root, so an index from another location is rebuilt. Each operation uses a scoped connection. Reads and writes check the schema version and library root inside their transaction, so a shared cache cannot silently return another library's rows. A read with incompatible metadata raises `IndexNotPreparedError`. Incremental writes avoid scanning every database page and refresh counts only for the affected author. Newly encountered corruption during a write remains an error until the next explicit preparation rebuilds the index. Rebuilding a readable database is transactional, and concurrent readers keep their previous complete snapshot. A failed rebuild preserves the previous index. A corrupt database is replaced only after its replacement has been built successfully.

Rebuilding writes only index files. Canonical records, marks, pages and media stay unchanged. Database and SQLite sidecar paths must be ordinary unshared files. Library compatibility is checked before index operations.

Offline `render` reads canonical post records directly and never opens the index. A damaged or unwritable index cannot prevent page generation. Rendering refreshes local file observations and the successful page-template version; the next index synchronization picks up changed records.

## Rebuild from the command line

Run `boosty-downloader reindex -o /path/to/library` to rebuild all authors and posts. Add `--cache-dir /path/to/local/cache` to keep `index.db` off a network share. CLI paths override the YAML download settings; the global `--config` option chooses the settings file. The command reads only path settings, requires no credentials and makes no network requests.

Compatibility is checked before opening diagnostic logs or creating index files. An unmarked folder containing older post folders is rejected without adopting its contents. The command reports its index path and counts on success; source or index failures return a nonzero exit status. A readable index is replaced transactionally, so an invalid source leaves its previous projection available. Canonical records, viewing marks, pages and media are preserved.

## Integration status

Actual downloads prepare the index once and update it after successful canonical saves. The adapter indexes post records, author information and access observations, preserving saved body and viewing marks across access changes. An index or projection failure warns once and disables further index attempts for the run. Canonical saves continue; their own errors still fail normally. Dry-run and `check` do not open the index.

The index defaults to `.boosty-downloader/index.db` under the library root. The CLI `--cache-dir` value overrides `downloading_settings.cache_directory` from YAML and places it at `<cache-directory>/index.db`, without an author subdirectory. The `JsonLibraryReader` adapter prepares the index and synchronizes canonical changes when opened by its caller. `reindex` rebuilds the complete index explicitly. `view` prepares and synchronizes the index on startup and serves the packaged shell and compatibility or empty-library pages. Its `/api` and `/media` routes currently return 404, so browsing, search, playback and mark editing are not connected yet. See the [viewer server foundation](library-storage.md#viewer-server-foundation).

## Reading a library

`JsonLibraryReader` implements the storage-neutral library queries. Constructing it performs no I/O; `prepare()` checks the index and synchronizes source changes. Author and post lists read indexed metadata, without loading complete post bodies. Post details read the known canonical folder and verify its full identity. A post list contains rows, month counts and a total for the same filtered selection. Filters combine text, content kind, unseen, favorites, exact tag, locked access and incomplete current media. Newest-first and oldest-first ordering use the full post ID to break date ties. Rows preserve original tag order, include recorded cover paths and viewing marks, and count only current media. Removed pieces do not make a post incomplete; locked-only observations have no saved missing-media inventory.

Search tokenizes input with the same SQLite `unicode61` tokenizer as the index and joins quoted prefix terms with AND. Quotes, asterisks and operator-looking text cannot become query syntax. The text folding makes `все` and `всё` match alike, without conflating `мои` and `мой`. Search results include original title text and a body snippet around the first hit as plain and matched text runs, never rendered HTML. Search projections replace marker controls and NUL with spaces to keep highlight offsets reliable; canonical content remains unchanged. A title-only match has no body snippet. An unseen filter includes accessible posts that have no seen time or have newer saved pieces. A text-only edit does not make a seen post unseen.

Author summaries use grouped index queries for post, locked, unseen and favorite totals and recorded media bytes. Storage includes downloaded pieces with a recorded size, including retained copies removed by the author; platform and external videos share one total. Pending, failed, unavailable and deleted pieces add no bytes. Summaries never walk media files or decode canonical records. `author(name)` scopes the same aggregates to one author; `has_author(name)` checks only the author identity. Tag counts count distinct posts carrying each exact tag.

Synchronization compares file sizes and modification times for post records, marks and author/access metadata. Unchanged records are not decoded, and media directories are not traversed. New or changed records update only their projections. Removed sources remove or adjust their index rows, including full-text rows; retained locked observations can keep a locked-only entry. A moved post folder keeps its full identity, while duplicate folders for the same post are an error. Invalid source data rolls back the whole synchronization and leaves canonical files untouched.

Viewing marks are read fresh from `viewer.json`. Saving marks writes canonical data before refreshing its index projection and preserves the timestamps supplied by the caller. Reader errors are reported to its caller; if the index update fails after a successful marks save, the canonical marks remain durable and a later synchronization can recover the projection.

## Measuring complete viewer queries

Create the deterministic sample with `uv run python scripts/sample_library.py --posts 5912 --out .sample/viewer-queries`, then run `uv run python scripts/benchmark_viewer_queries.py`. The sample has exactly 5,000 posts for its primary author. The benchmark validates that workload, including a search matching almost every post, before timing fully materialized lists, search snippets and canonical post details. It reports the first measured call and every warm sample, plus the warm median and range. The workload check already reads these queries, so the first measured call is not a cold-cache measurement.

The command fails if a warm median reaches 300 ms for either list or 150 ms for detail. Use `--root` for another copy of the same sample and `--samples` to change the number of warm measurements. Preparation may rebuild the disposable index; canonical content stays unchanged. These end-to-end budgets differ from the SQL-only timings in `scripts/benchmark_library.py`. The script is a local acceptance benchmark, not a machine-independent timing assertion in the unit suite.
