# How downloading works

Boosty Downloader saves each accessible post as a complete `post.json` record, its media files and a styled `post.html` page. The record preserves the whole post and the state of each media piece across runs. `--post-url` uses the same workflow for one post.

## The pipeline

```text
CLI: validate arguments and check library compatibility without writes
  -> config, initialize new library marker, filters, indexed JSON store
  -> separate API and media sessions
  -> DownloadAllPostUseCase / DownloadPostByIdUseCase
  -> refresh_author: blog details and owned avatar/cover images
  -> BoostyAPIClient: paginated listing / one post by ID
  -> PostDTO
  -> access observation: save locked overview or clear confirmed access
  -> PostDownloadRetrier: attempts, backoff, one expired-link refresh
     -> DownloadSinglePostUseCase
        -> PostPreparer: saved record + live post + local file snapshot
        -> reconcile: refreshed record + selected media IDs to download
        -> PostDownloadState: reserve paths and persist each result
        -> ensure_post_previews: save missing video preview paths
        -> PostMediaDownloader: up to four concurrent media transfers
     -> final page: build_post_page(StoredPost), then render HTML
  -> normal completion: refresh deferred pages and links to later saved posts
```

1. **Fetch.** Each real run refreshes blog details once and updates the author's avatar and cover. Optional metadata/image failures warn and preserve saved data. `BoostyAPIClient` validates listing and single-post responses as `PostDTO` objects. The API session carries credentials; a separate session downloads media without account tokens or cookies.
2. **Observe access and select posts.** Locked overviews are saved before tag filtering, without creating post folders. Confirmed access clears the stale locked observation. `--exclude-tag TAG` matches whole tag names, ignoring case and surrounding whitespace. Repeated options exclude multiple tags. Exclusions prevent content preparation and downloading, leaving saved post content unchanged. Access observations may still read the saved record to refresh its index row before filtering. Posts without access retain any saved content, page and viewing marks.
3. **Prepare.** `PostPreparer` maps the complete live body, locates the saved record and observes actual local file names and sizes. `reconcile` computes the updated record and individual media IDs eligible under the filters. Preparation also identifies missing video previews independently of those filters. `--restore-missing` also selects locally deleted pieces that are still in the current post and match the content filters. The preparation step only reads. A post's existing folder remains stable when its title changes.
4. **Persist.** `PostDownloadState` owns the record during an attempt. It saves the updated content, reserves each destination before transfer, and saves each success or failure separately. Finished peers cannot lose their state when another piece fails. After each canonical save, the storage adapter updates the disposable library index. An index failure warns once and disables indexing for the rest of that run; it does not undo the JSON save or fail the download.
5. **Download.** `PostMediaDownloader` uses aiohttp for images, attachments, audio and Boosty videos, and yt-dlp for external videos. At most four pieces of a post transfer concurrently. Media is published under its final name only after completion; existing files are not overwritten.
6. **Retry and render.** Each retry prepares against saved progress and current files. After the final attempt outcome, `build_post_page` assembles a complete page from the saved record. Successful rendering records the current page template version. Otherwise unchanged posts with authored Boosty post links defer their page comparison until normal run completion, when later downloaded targets are available. Identical HTML needs no rewrite.
7. **Resolve local links.** After normal completion, affected pages are rebuilt from fresh saved records. Links to usable saved pages become relative local links; missing targets remain on Boosty. A previously unchanged post counts as updated only when its final HTML bytes change. Deferred pages remain pending until their final comparison succeeds. This pass runs before the success summary and never runs after cancellation, a listing error or a systemic failure stop. If completion fails, the CLI shows partial results and any pending page checks instead of a normal success summary.

## One post, two runs

Suppose the first run uses `-f post_content`: it saves the text and images, while video and attachment entries remain in `post.json`. The HTML page contains the complete body, with placeholders at the positions of media not downloaded yet.

A week later, a run with all content types selects the video and attachment. It reuses the saved images and rebuilds the page from the record containing both runs' results. A failed attachment does not erase the text, images or a video that has already finished. Filters choose media transfers; they do not remove content from the stored body or page.

A saved media file that the user deletes is observed as deleted and stays deleted during ordinary runs. Media removed from the live post stays in the saved history, together with any local copy. The downloader does not read or change viewer marks.

## Previews, teasers and library covers

Missing Boosty video previews are fetched after the initial record save and stored in the post's `previews/` directory. Successful preview paths are saved immediately without changing the main video's state. A preview may be available before the video itself is ready. Locked-post observations keep their previous teaser paths while metadata changes; a missing teaser is fetched into the author's `.boosty-downloader/teasers/` directory. Tag exclusions prevent both preview and teaser requests.

Existing safe, nonempty image files are reused, including when the live URL changes or disappears. A missing image with an available URL is retried on a later run. Image request failures warn without failing primary content downloads; record-write failures remain post failures. Auxiliary image transfers are excluded from primary media totals and the deleted-content count.

The pure cover selector reads the saved body order and a filesystem snapshot. It prefers the first current downloaded image, then the preview of the first current Boosty video. It returns no cover when that video's preview is unavailable; it does not choose a later video's preview. Locked-only posts use their saved teaser when the file is present. Cover choice is derived, not duplicated in the post record. The index and reader use this projection for library covers.

## Dry-run uses the same preparation

`download --dry-run` walks the full blog and calls the same `PostPreparer` as the downloader. It counts unique planned primary media IDs and their current API sizes. A missing preview can make a post need an update without adding a video transfer to those counts. It does not execute transfers, persist records or write pages. `--dry-run` with `--post-url` is a usage error.

| Post category | Meaning |
| --- | --- |
| New records | No saved record exists, including a new text-only post |
| Existing posts to update | Selected media needs downloading, meaningful content or local state changed, the page is missing or uses an older template, or its final local post links change |
| Existing posts unchanged | None of those changes is needed under the selected filters; this does not imply that every media item is present |
| Excluded by tag | The post matches an excluded tag and is not prepared |

The overview reports inaccessible posts separately. Unfinished uploads and author-removed pieces are not counted as downloads. Unknown video sizes remain explicit rather than being guessed from older local files. After an unchanged successful download, the next preview reports no media work for that post.

For otherwise unchanged posts with authored Boosty links, the preview prepares final HTML in memory and compares its bytes with the saved page. It includes the pages that accessible, non-excluded posts would publish, using the same folder-choice rules with temporary reservations in memory. This predicts normal completion; later transfer or write failures can prevent planned work from finishing. A target whose page is restored later in the run does not cause a needless update when the source already has the correct local link.

Both modes reserve new post folders for the duration of the run. Names differing only by case or Unicode normalization use separate collision suffixes, so the forecast remains portable across filesystems. Existing saved posts retain their recorded folders.

If pagination repeats a full post ID, both modes process only its first occurrence in that listing. Repeated entries do not allocate another folder, download media again or increase post counts. Media retries still use the same post's retry workflow.

Preview startup also stays read-only: it does not create a library, search index, metadata, media, failure log or sample config. A missing config produces an error without creating its parent folder. `--debug` shows preview diagnostics on the console and does not create or truncate a debug log. Ordinary `download` retains sample-config setup and file diagnostics after the library compatibility check. `check` retains its existing setup behavior.

## Failures and interruption

Transport errors such as connection loss, HTTP 5xx and 429 use five attempts with increasing delays. `PostDownloadRetrier` separately allows up to five post attempts and one API refresh for expired signed media links. Every retry uses the record and local files to retain completed individual pieces, including peers of the same media kind.

A selected external video reported as unavailable is checked once during that run. Other temporarily failing media can still retry, and a later run checks the unavailable video again. A post whose only remaining problem is unavailable media does not count toward the failure streak. Other unsuccessful posts count toward the five-consecutive-failures stop; `--skip-all-failures` disables that stop.

Media transfers use private temporary directories. An incomplete transfer never appears under a final media name. If a transfer finished and published its file before interruption prevented the record update, the next preparation can recover it after matching its reserved or expected path and any known size. Empty, wrong-size or unrelated files are preserved rather than accepted as completed media. Filename collisions take a free destination instead of replacing another file. This recovers completed pieces; it does not promise resuming a partial byte stream.

At the terminal post outcome, the page shows the full saved body and the current state of downloaded, failed, unavailable or missing media, including attachments. A rendering failure leaves completed media durable and makes the post unsuccessful. If transfer and rendering both fail, both causes are reported. Cancellation may leave the previous page until a later run rebuilds it.

A failure while refreshing deferred links stops run finalization without a normal success summary. Completed media and previously published pages remain saved. This is a page-finalization error, not another media retry.

The summary counts remaining deleted media still present in the accessible, non-excluded posts processed by the run. Content filters restrict restoration, while the count includes deleted pieces of other kinds. Retries replace the post's contribution instead of counting it again.

## Page size and signed links

Media links from listing responses expire after 24 hours. The download walk uses pages of five posts to limit the time between fetching a signed URL and using it. Metadata-only walks for `check` and dry-run use pages of 100 because no media downloads occur between pages. If links expire during a long post download, the retrier fetches fresh post metadata once and preserves already completed media.

## Storage and offline commands

Download state lives in `<destination>/<author>/<post folder>/post.json`. Author information, avatar/cover images and locked-post observations live under `<destination>/<author>/.boosty-downloader/`. `author.json` uses author-relative image paths; `locked.json` retains observations of posts not encountered during a partial run. Dry-run and `check` do not update these files. Downloads update a disposable SQLite search index, separate from canonical download state. Its default location is `<destination>/.boosty-downloader/index.db`; `--cache-dir PATH` moves only the index to `PATH/index.db`. `reindex` rebuilds the index from saved records without credentials or network access. The legacy `clean-cache` command has been removed; index maintenance preserves canonical records, viewing marks, pages and media. See [library storage](../library-storage.md) for the file layout, ownership, media states and common commands, and [the library index](../library-index.md) for rebuild and failure behavior.

The first actual download creates the immutable `<destination>/.boosty-downloader/library.json` marker with `format_version: 5`. Dry-run checks compatibility without creating it. Before sample-config creation, debug-file setup or any network request, every download form checks an unmarked destination for recognized post folders under every author. If it finds one, the command names the destination, asks for another folder and explains why older downloads should be kept. It never reads the old post contents or SQLite cache. A malformed, unsupported or unsafe marker is an error rather than an invitation to overwrite it.

There is no automatic migration or adoption of older downloads. `render` and `reindex` use the same compatibility boundary before startup writes. `render` rebuilds complete pages from canonical records and current local files without using the index or contacting Boosty. The `view` command prepares the reader and serves the packaged viewer shell and compatibility or empty-library pages. Its APIs provide library queries, media and viewing marks; the shell's data screens and controls remain future work. See the [viewer server foundation](../library-storage.md#viewer-server-foundation) for its command options.

## Download layers

These layers describe the download workflow:

- `cli/`: Typer commands, concrete dependency composition and console output.
- `application/`: use cases, mapping, shared preparation, reconciliation and post execution.
- `domain/`: persistent post and filesystem snapshot values, using the standard library.
- `infrastructure/`: API clients, filesystem observations, JSON storage, media transfers and HTML rendering.

Reconciliation decides what is needed without doing filesystem I/O. Infrastructure observes or writes files; the application coordinates those operations through explicit dependencies. The API remains a tolerant reader of changing Boosty responses; see [tolerant-reader.md](./tolerant-reader.md).
