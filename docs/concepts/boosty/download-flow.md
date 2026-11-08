# How downloading works

Boosty Downloader saves each accessible post as a complete `post.json` record, its media files and a styled `post.html` page. The record preserves the whole post and the state of each media piece across runs. `--post-url` uses the same workflow for one post.

## The pipeline

```text
CLI: validate arguments and check library compatibility without writes
  -> config, initialize new library marker, filters, JsonPostStore
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
```

1. **Fetch.** Each real run refreshes blog details once and updates the author's avatar and cover. Optional metadata/image failures warn and preserve saved data. `BoostyAPIClient` validates listing and single-post responses as `PostDTO` objects. The API session carries credentials; a separate session downloads media without account tokens or cookies.
2. **Observe access and select posts.** Locked overviews are saved before tag filtering, without creating post folders. Confirmed access clears the stale locked observation. `--exclude-tag TAG` matches whole tag names, ignoring case and surrounding whitespace. Repeated options exclude multiple tags. Exclusions happen before post-record lookup, content preparation or downloading; they leave saved post content unchanged. Posts without access retain any saved content, page and viewing marks.
3. **Prepare.** `PostPreparer` maps the complete live body, locates the saved record and observes actual local file names and sizes. `reconcile` computes the updated record and individual media IDs eligible under the filters. Preparation also identifies missing video previews independently of those filters. `--restore-missing` also selects locally deleted pieces that are still in the current post and match the content filters. The preparation step only reads. A post's existing folder remains stable when its title changes.
4. **Persist.** `PostDownloadState` owns the record during an attempt. It saves the updated content, reserves each destination before transfer, and saves each success or failure separately. Finished peers cannot lose their state when another piece fails.
5. **Download.** `PostMediaDownloader` uses aiohttp for images, attachments, audio and Boosty videos, and yt-dlp for external videos. At most four pieces of a post transfer concurrently. Media is published under its final name only after completion; existing files are not overwritten.
6. **Retry and render.** Each retry prepares against saved progress and current files. After the final attempt outcome, `build_post_page` assembles a complete page from the saved record. Successful rendering records the current page template version. An unchanged post with a current page needs neither media transfers nor a page rewrite.

## One post, two runs

Suppose the first run uses `-f post_content`: it saves the text and images, while video and attachment entries remain in `post.json`. The HTML page contains the complete body, with placeholders at the positions of media not downloaded yet.

A week later, a run with all content types selects the video and attachment. It reuses the saved images and rebuilds the page from the record containing both runs' results. A failed attachment does not erase the text, images or a video that has already finished. Filters choose media transfers; they do not remove content from the stored body or page.

A saved media file that the user deletes is observed as deleted and stays deleted during ordinary runs. Media removed from the live post stays in the saved history, together with any local copy. The downloader does not read or change viewer marks.

## Previews, teasers and library covers

Missing Boosty video previews are fetched after the initial record save and stored in the post's `previews/` directory. Successful preview paths are saved immediately without changing the main video's state. A preview may be available before the video itself is ready. Locked-post observations keep their previous teaser paths while metadata changes; a missing teaser is fetched into the author's `.boosty-downloader/teasers/` directory. Tag exclusions prevent both preview and teaser requests.

Existing safe, nonempty image files are reused, including when the live URL changes or disappears. A missing image with an available URL is retried on a later run. Image request failures warn without failing primary content downloads; record-write failures remain post failures. Auxiliary image transfers are excluded from primary media totals and the deleted-content count.

The pure cover selector reads the saved body order and a filesystem snapshot. It prefers the first current downloaded image, then the preview of the first current Boosty video. It returns no cover when that video's preview is unavailable; it does not choose a later video's preview. Locked-only posts use their saved teaser when the file is present. Cover choice is derived, not duplicated in the post record. The index/reader will consume this projection in its later stage.

## Dry-run uses the same preparation

`download --dry-run` walks the full blog and calls the same `PostPreparer` as the downloader. It counts unique planned primary media IDs and their current API sizes. A missing preview can make a post need an update without adding a video transfer to those counts. It does not execute transfers, persist records or render pages. `--dry-run` with `--post-url` is a usage error.

| Post category | Meaning |
| --- | --- |
| New records | No saved record exists, including a new text-only post |
| Existing posts to update | Selected media needs downloading, meaningful content or local state changed, or the page is missing or uses an older template |
| Existing posts unchanged | None of those changes is needed under the selected filters; this does not imply that every media item is present |
| Excluded by tag | The post matches an excluded tag and is not prepared |

The overview reports inaccessible posts separately. Unfinished uploads and author-removed pieces are not counted as downloads. Unknown video sizes remain explicit rather than being guessed from older local files. After an unchanged successful download, the next preview reports no media work for that post.

Preview startup also stays read-only: it does not create a library, SQLite cache, metadata, media, failure log or sample config. A missing config produces an error without creating its parent folder. `--debug` shows preview diagnostics on the console and does not create or truncate a debug log. Ordinary `download` retains sample-config setup and file diagnostics after the library compatibility check. `check` retains its existing setup behavior.

## Failures and interruption

Transport errors such as connection loss, HTTP 5xx and 429 use five attempts with increasing delays. `PostDownloadRetrier` separately allows up to five post attempts and one API refresh for expired signed media links. Every retry uses the record and local files to retain completed individual pieces, including peers of the same media kind.

A selected external video reported as unavailable is checked once during that run. Other temporarily failing media can still retry, and a later run checks the unavailable video again. A post whose only remaining problem is unavailable media does not count toward the failure streak. Other unsuccessful posts count toward the five-consecutive-failures stop; `--skip-all-failures` disables that stop.

Media transfers use private temporary directories. An incomplete transfer never appears under a final media name. If a transfer finished and published its file before interruption prevented the record update, the next preparation can recover it after matching its reserved or expected path and any known size. Empty, wrong-size or unrelated files are preserved rather than accepted as completed media. Filename collisions take a free destination instead of replacing another file. This recovers completed pieces; it does not promise resuming a partial byte stream.

At the terminal post outcome, the page shows the full saved body and the current state of downloaded, failed, unavailable or missing media, including attachments. A rendering failure leaves completed media durable and makes the post unsuccessful. If transfer and rendering both fail, both causes are reported. Cancellation may leave the previous page until a later run rebuilds it.

The summary counts remaining deleted media still present in the accessible, non-excluded posts processed by the run. Content filters restrict restoration, while the count includes deleted pieces of other kinds. Retries replace the post's contribution instead of counting it again.

## Page size and signed links

Media links from listing responses expire after 24 hours. The download walk uses pages of five posts to limit the time between fetching a signed URL and using it. Metadata-only walks for `check` and dry-run use pages of 100 because no media downloads occur between pages. If links expire during a long post download, the retrier fetches fresh post metadata once and preserves already completed media.

## Storage boundary and remaining v5 work

Download state lives in `<destination>/<author>/<post folder>/post.json`. Author information, avatar/cover images and locked-post observations live under `<destination>/<author>/.boosty-downloader/`. `author.json` uses author-relative image paths; `locked.json` retains observations of posts not encountered during a partial run. Dry-run and `check` do not update these files. The downloader no longer opens SQLite. `--cache-dir` is only relevant to the legacy `clean-cache` command, which removes an old database without resetting records or removing media.

The first actual download creates the immutable `<destination>/.boosty-downloader/library.json` marker with `format_version: 5`. Dry-run checks compatibility without creating it. Before sample-config creation, debug-file setup or any network request, every download form checks an unmarked destination for recognized post folders under every author. If it finds one, the command names the destination, asks for another folder and explains why older downloads should be kept. It never reads the old post contents or SQLite cache. A malformed, unsupported or unsafe marker is an error rather than an invitation to overwrite it.

There is no automatic migration or adoption of older downloads. Library indexing, standalone page rebuilding and the library viewer belong to later stages; each will use the same compatibility boundary when connected to the CLI.

## Layers

- `cli/`: Typer commands, concrete dependency composition and console output.
- `application/`: use cases, mapping, shared preparation, reconciliation and post execution.
- `domain/`: persistent post and filesystem snapshot values, using the standard library.
- `infrastructure/`: API clients, filesystem observations, JSON storage, media transfers and HTML rendering.

Reconciliation decides what is needed without doing filesystem I/O. Infrastructure observes or writes files; the application coordinates those operations through explicit dependencies. The API remains a tolerant reader of changing Boosty responses; see [tolerant-reader.md](./tolerant-reader.md).
