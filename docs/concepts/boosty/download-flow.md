# How downloading works

Boosty Downloader saves each accessible post as a complete `post.json` record, its media files and a styled `post.html` page. The record preserves the whole post and the state of each media piece across runs. `--post-url` uses the same workflow for one post.

## The pipeline

```text
CLI: config, filters, JsonPostStore, separate API and media sessions
  -> DownloadAllPostUseCase / DownloadPostByIdUseCase
  -> BoostyAPIClient: paginated listing / one post by ID
  -> PostDTO
  -> PostDownloadRetrier: attempts, backoff, one expired-link refresh
     -> DownloadSinglePostUseCase
        -> PostPreparer: saved record + live post + local file snapshot
        -> reconcile: refreshed record + selected media IDs to download
        -> PostDownloadState: reserve paths and persist each result
        -> PostMediaDownloader: up to four concurrent media transfers
     -> final page: build_post_page(StoredPost), then render HTML
```

1. **Fetch.** `BoostyAPIClient` validates listing and single-post responses as `PostDTO` objects. The API session carries credentials; a separate session downloads media without account tokens or cookies.
2. **Select posts.** `--exclude-tag TAG` matches whole tag names, ignoring case and surrounding whitespace. Repeated options exclude multiple tags. Exclusions happen before record lookup, content preparation or downloading; they leave saved files unchanged. Posts without access are skipped without replacing their saved content or page.
3. **Prepare.** `PostPreparer` maps the complete live body, locates the saved record and observes actual local file names and sizes. `reconcile` computes the updated record and individual media IDs eligible under the filters. The preparation step only reads. A post's existing folder remains stable when its title changes.
4. **Persist.** `PostDownloadState` owns the record during an attempt. It saves the updated content, reserves each destination before transfer, and saves each success or failure separately. Finished peers cannot lose their state when another piece fails.
5. **Download.** `PostMediaDownloader` uses aiohttp for images, attachments, audio and Boosty videos, and yt-dlp for external videos. At most four pieces of a post transfer concurrently. Media is published under its final name only after completion; existing files are not overwritten.
6. **Retry and render.** Each retry prepares against saved progress and current files. After the final attempt outcome, `build_post_page` assembles a complete page from the saved record. Successful rendering records the current page template version. An unchanged post with a current page needs neither media transfers nor a page rewrite.

## One post, two runs

Suppose the first run uses `-f post_content`: it saves the text and images, while video and attachment entries remain in `post.json`. The HTML page contains the complete body, with placeholders at the positions of media not downloaded yet.

A week later, a run with all content types selects the video and attachment. It reuses the saved images and rebuilds the page from the record containing both runs' results. A failed attachment does not erase the text, images or a video that has already finished. Filters choose media transfers; they do not remove content from the stored body or page.

A saved media file that the user deletes is observed as deleted and stays deleted during ordinary runs. Media removed from the live post stays in the saved history, together with any local copy. The downloader does not read or change viewer marks.

## Dry-run uses the same preparation

`download --dry-run` walks the full blog and calls the same `PostPreparer` as the downloader. It counts unique planned media IDs and their current API sizes. It does not execute transfers, persist records or render pages. `--dry-run` with `--post-url` is a usage error.

| Post category | Meaning |
| --- | --- |
| New records | No saved record exists, including a new text-only post |
| Existing posts to update | Selected media needs downloading, meaningful content or local state changed, or the page is missing or uses an older template |
| Existing posts unchanged | None of those changes is needed under the selected filters; this does not imply that every media item is present |
| Excluded by tag | The post matches an excluded tag and is not prepared |

The overview reports inaccessible posts separately. Unfinished uploads and author-removed pieces are not counted as downloads. Unknown video sizes remain explicit rather than being guessed from older local files. After an unchanged successful download, the next preview reports no media work for that post.

Preview startup also stays read-only: it does not create a library, SQLite cache, metadata, media, failure log or sample config. A missing config produces an error without creating its parent folder. `--debug` shows preview diagnostics on the console and does not create or truncate a debug log. Ordinary `download` and `check` commands retain sample-config setup and file diagnostics.

## Failures and interruption

Transport errors such as connection loss, HTTP 5xx and 429 use five attempts with increasing delays. `PostDownloadRetrier` separately allows up to five post attempts and one API refresh for expired signed media links. Every retry uses the record and local files to retain completed individual pieces, including peers of the same media kind.

A selected external video reported as unavailable is checked once during that run. Other temporarily failing media can still retry, and a later run checks the unavailable video again. A post whose only remaining problem is unavailable media does not count toward the failure streak. Other unsuccessful posts count toward the five-consecutive-failures stop; `--skip-all-failures` disables that stop.

Media transfers use private temporary directories. An incomplete transfer never appears under a final media name. If a transfer finished and published its file before interruption prevented the record update, the next preparation can recover it after matching its reserved or expected path and any known size. Empty, wrong-size or unrelated files are preserved rather than accepted as completed media. Filename collisions take a free destination instead of replacing another file. This recovers completed pieces; it does not promise resuming a partial byte stream.

At the terminal post outcome, the page shows the full saved body and the current state of downloaded, failed, unavailable or missing media, including attachments. A rendering failure leaves completed media durable and makes the post unsuccessful. If transfer and rendering both fail, both causes are reported. Cancellation may leave the previous page until a later run rebuilds it.

## Page size and signed links

Media links from listing responses expire after 24 hours. The download walk uses pages of five posts to limit the time between fetching a signed URL and using it. Metadata-only walks for `check` and dry-run use pages of 100 because no media downloads occur between pages. If links expire during a long post download, the retrier fetches fresh post metadata once and preserves already completed media.

## Storage boundary and remaining v5 work

Download state lives in `<destination>/<author>/<post folder>/post.json`. The downloader no longer opens SQLite. `--cache-dir` is only relevant to the legacy `clean-cache` command, which removes an old database without resetting records or removing media.

Use a fresh destination for development checks. Migration from the v4 cache and a guard against selecting a v4 library are not implemented. Author information and image updates, complete locked-post observations, the `--restore-missing` CLI option, downloaded previews/teasers, library indexing, standalone page rebuilding and the library viewer belong to later stages. Existing storage or rendering components do not mean those workflows are connected to the CLI yet.

## Layers

- `cli/`: Typer commands, concrete dependency composition and console output.
- `application/`: use cases, mapping, shared preparation, reconciliation and post execution.
- `domain/`: persistent post and filesystem snapshot values, using the standard library.
- `infrastructure/`: API clients, filesystem observations, JSON storage, media transfers and HTML rendering.

Reconciliation decides what is needed without doing filesystem I/O. Infrastructure observes or writes files; the application coordinates those operations through explicit dependencies. The API remains a tolerant reader of changing Boosty responses; see [tolerant-reader.md](./tolerant-reader.md).
