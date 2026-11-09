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

## Integration status

Actual downloads prepare the index once and update it after successful canonical saves. The adapter indexes post records, author information and access observations, preserving saved body and viewing marks across access changes. An index or projection failure warns once and disables further index attempts for the run. Canonical saves continue; their own errors still fail normally. Dry-run and `check` do not open the index.

The index defaults to `.boosty-downloader/index.db` under the library root. The CLI `--cache-dir` value overrides `downloading_settings.cache_directory` from YAML and places it at `<cache-directory>/index.db`, without an author subdirectory. Query APIs, synchronization on viewer open and the `reindex` command remain subsequent integration steps.
