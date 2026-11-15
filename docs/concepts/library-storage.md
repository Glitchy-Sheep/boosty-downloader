# Library storage

Each saved post has a `post.json` record, called `StoredPost` in the code. It keeps the complete current body, metadata and media history across download runs. A first run with `-f post_content` saves text and images while retaining the references to videos, audio and attachments. A later run can download those missing pieces and rebuild one complete page using both runs' results. Content filters choose transfers; they do not remove anything from the stored body.

## Files and ownership

The destination passed with `-o` is the library root. A typical library has this layout; optional records, viewing marks and assets appear only when available:

```text
<library>/
  .boosty-downloader/
    library.json
    index.db
  <author>/
    .boosty-downloader/
      author.json
      locked.json
      avatar.<ext>
      cover.<ext>
      teasers/
      thumbs/
    YYYY-MM-DD - Title (id8)/
      post.json
      viewer.json
      post.html
      images/
      files/
      audio/
      boosty_videos/
      external_videos/
      previews/
```

| File or directory | Purpose and recovery |
| --- | --- |
| Root `.boosty-downloader/library.json` | Immutable format marker containing `format_version: 5`. Keep it with the library; it is not the disposable index. |
| `post.json` and media directories | Authoritative saved post content and local files. The record contains the complete current body, metadata, current media and retained entries removed by the author. The index cannot replace them. |
| `viewer.json` | Independent user data: seen time, favorite flag and per-media playback seconds and finish times. Downloads do not overwrite it. Back it up with the post. |
| Author `.boosty-downloader/author.json`, `locked.json` and images | Saved blog details, access observations, avatar, cover and teasers. These records and files belong with the author's library data. |
| `post.html` | A complete derived page. `render` rebuilds it from the saved record and current local files. |
| Root `.boosty-downloader/index.db` | A disposable SQLite projection for library queries and search. `reindex` rebuilds it from the canonical JSON records, including viewing marks. |

Post folders remain stable when a title changes. Media and video preview paths in `post.json` are relative to that post's folder. Avatar, cover and teaser paths are relative to the author's folder, so an avatar path includes `.boosty-downloader/`. All stored paths use portable relative strings. Keep the library's internal layout when moving or backing it up.

Image `thumbnail_path` and locked-post `teaser_thumbnail_path` are also author-relative. They point directly under `.boosty-downloader/thumbs/`; original images stay in their existing locations. Post and locked records use schema version 2 for these fields. Version 1 records remain readable without rewriting them, and ordinary saves write version 2. Earlier v5 binaries reject version 2 records instead of silently discarding the new fields. This protects the individual record; it is not a library-wide startup compatibility check. The library format marker remains 5.

Downloads request a copy at most 480 px wide from Boosty's image resizer after saving an image, and backfill missing thumbnails for current saved images whose originals still exist. Locked teasers receive the same treatment. Video covers reuse their existing previews. Thumbnail requests share a one-per-second limit, use the media session without account credentials and accept bounded raster responses up to 2 MiB. PNG responses retain PNG encoding, so their small copies can still be larger than JPEG copies. Unsupported or failed responses leave the original usable and produce one thumbnail warning per run; cancellation and record-write failures still propagate. Auxiliary bytes do not count toward primary-media transfer totals.

A missing thumbnail is retried on a later ordinary download. Dry-run reports such a post as needing an update but performs no thumbnail request or write. Removed images retain their saved thumbnail reference, but no longer have a current remote source for backfill. Deleting an original does not remove its retained thumbnail; post-cover selection still excludes media removed from the author's current body.

`author.json` and `locked.json` live in the author's service folder, not directly in the author root. A locked observation records an inaccessible post's overview without creating a new post folder. If access is lost after a post was saved, its existing body, media, page and viewing marks are preserved. Observations survive a partial scan and are cleared individually when access to that post is confirmed again.

The index is the only disposable database. `--cache-dir PATH` puts the whole library's index at `PATH/index.db`, with no per-author subdirectory; it does not move download state. Index failures during a download warn once and leave canonical saves intact. See [the library index](library-index.md) for rebuilding, synchronization and failure handling. Back up the records and media, not just the index.

## Media states and retained history

Each media entry has one local state:

| State | Meaning |
| --- | --- |
| `pending` | No completed local copy has been recorded. The piece may be outside the selected filters, not ready on Boosty, or awaiting a transfer. |
| `downloaded` | A local copy is recorded. Preparation and offline rendering observe whether that copy still exists. |
| `failed` | A transfer failed. A later eligible attempt can retry it while preserving completed peers. |
| `unavailable` | A selected external video was reported unavailable. It is checked at most once during that run and can be checked again on a later run. |
| `deleted` | A previously saved copy is missing locally. Its recorded path and last observed size are retained; ordinary downloads leave it deleted. |

Removal from the author's post is tracked separately with `removed_at`. The current body stops referencing the piece, but its inventory entry, history and any local copy remain. Retained downloaded copies appear in the page's removed-content section. An item that returns with the same media identity keeps its history and clears `removed_at`; a new identity creates a distinct entry and does not overwrite the previous file.

A file restored at its recorded path is observed as `downloaded` again. Existing recorded copies, including files modified by the user, are kept and their current sizes are recorded. `--restore-missing` permits downloading locally deleted media only when it is still in the current accessible post, matches the content filters and is available for transfer. It does not restore an attachment that is still absent from the author's post.

JSON records are replaced atomically, so readers see a complete old or new record. Download progress is saved per piece: its destination is reserved before transfer, and its success or failure is saved separately. Transfers use private temporary directories and publish a final filename only after completion, without replacing an existing file. A later run can recover a completed file published just before an interruption prevented the record update. These are individual file operations, not a whole-library transaction or a promise to resume a partial byte stream. See [how downloading works](boosty/download-flow.md#failures-and-interruption) for retry and recovery details.

## Common commands

Replace `AUTHOR` with the Boosty blog name and `LIBRARY` with the destination folder. Quote paths containing spaces. Download commands use your configured Boosty credentials.

Save text and images first, then add the remaining media on a later run:

```bash
boosty-downloader download AUTHOR -o LIBRARY -f post_content
boosty-downloader download AUTHOR -o LIBRARY
```

The second command enables all content types by default. It reuses saved files, downloads eligible missing pieces and rebuilds the complete page. Media deliberately deleted locally remains deleted.

Preview selected work or restore locally deleted media:

```bash
boosty-downloader download AUTHOR -o LIBRARY --dry-run
boosty-downloader download AUTHOR -o LIBRARY --restore-missing
```

Dry-run contacts Boosty and uses the same preparation as a real download, but creates or changes no local files. That includes records, media, pages, index, sample config and diagnostic logs. It reports new records, existing posts to update, unchanged posts, tag exclusions and selected primary media work. You can combine `--restore-missing` with `--dry-run` and content filters to preview a restoration. See [dry-run preparation](boosty/download-flow.md#dry-run-uses-the-same-preparation) for the counts and limits.

Rebuild every saved page, or only one author's pages:

```bash
boosty-downloader render -o LIBRARY
boosty-downloader render AUTHOR -o LIBRARY
```

Rendering needs no credentials or Boosty network access and never uses the index. It refreshes observations of recorded local media, rebuilds HTML and saves the successful template version in `post.json`. It preserves media files and viewing marks. A later index synchronization picks up changed records.

Authored links to other saved posts use relative `post.html` paths, including posts by another author. A local target needs its full saved record and a regular page in its own folder. Missing or unreadable targets keep their Boosty links. After a normal download completes, links to pages saved later in that run are resolved. A later `render` or download that processes the source also picks up newly saved targets; it never downloads a post merely because a link mentions it. Identical HTML keeps its modification time.

Rebuild the index on a local disk, for example when the library itself is on network storage:

```bash
boosty-downloader reindex -o LIBRARY --cache-dir LOCAL_INDEX_DIRECTORY
```

Reindexing needs no credentials or network access. It changes only the disposable index and its SQLite sidecar files; canonical records, viewing marks, pages and media are preserved. Omit `--cache-dir` to use the configured index location or, by default, `LIBRARY/.boosty-downloader/index.db`.

## Viewer server foundation

```bash
boosty-downloader view -o LIBRARY
```

`view` prepares the library reader and serves the packaged application shell, with pages for an empty or incompatible library. It needs no Boosty credentials. By default it binds to the local machine on port 8314, tries the next free port if needed and opens the browser. `--port` chooses an exact port, `--no-open` suppresses the browser launch, and `--lan` enables the local-network listener.

Read APIs provide authors, filtered post lists, tags and complete post bodies. Local media support seeking, while author-supplied HTML and SVG download and generated post pages run in an opaque sandbox. The packaged UI still shows the shell; data screens and mark controls follow. Saved `post.html` pages can also be opened directly. See the [read API contract](../development/07-viewer-api.md).

## Moving from v4

Choose a separate destination for v5, download into it and keep the old folder for posts that Boosty no longer serves. There is no automatic migration or adoption, and v5 never reads the old SQLite download cache. Do not copy v4 post folders into a marked v5 library or add a format marker by hand.

Before a download creates startup files or makes network requests, it checks the entire destination for compatibility. An unmarked destination containing recognized post folders under any author is refused. A malformed, unsupported or unsafe marker also causes an error. The first actual download initializes the format-5 marker in an accepted destination; dry-run never creates it. `render` and `reindex` check the same compatibility boundary before startup writes.

To roll back, point v4 at its original download folder again. If both versions share a configuration file, restore its destination and cache settings for v4 as well. Keep the separate v5 library intact while using the older folder.
