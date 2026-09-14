# How downloading works

Boosty Downloader walks an author's blog page by page and saves every post to disk: media files plus a styled `post.html` snapshot. `--post-url` takes the same road for one post.

## The pipeline

```
CLI (typer)
  └► use case: download all posts / download one post by id
        └► BoostyAPIClient - paginated fetch or one post by id, rate limited
              └► PostDTO (pydantic models of the raw API answer)
                    └► PostDownloadRetrier - attempts, backoff, one refresh of expired links
                          └► DownloadSinglePostUseCase - one post
                                ├► post_mapper - DTO to domain Post
                                ├► cache check - which content types are still missing
                                ├► PostMediaDownloader - media files, 4 at a time
                                ├► post.html render (Jinja)
                                └► cache update (SQLite) - the content types that finished
```

1. **Fetch.** `BoostyAPIClient.iterate_over_posts` pages through `blog/{name}/post/` with a rate limiter; `--post-url` asks for one post by id. Each answer turns into validated `PostDTO` objects.
2. **Cache check.** A SQLite cache keeps per-post flags by content type (files, videos, audio, ...). The run skips the parts it already has.
3. **Map.** `map_post_dto_to_domain` turns API DTOs into domain chunks (text, image, video, file, audio, list). The domain layer knows nothing about Boosty shapes.
4. **Download.** `PostMediaDownloader` saves images, files and Boosty videos through the aiohttp downloader and external videos (YouTube, Vimeo) through yt-dlp, up to 4 files of a post at once.
5. **Render.** Chunks processed in this run become `post.html` via Jinja templates.
6. **Remember.** The cache records which content types finished, so the next run downloads only what is missing.

## When a piece fails

- Transport errors (connection lost, 5xx, 429) are retried by the HTTP client with growing pauses, 5 attempts.
- One dead link does not stop the post: the other chunks finish, the content types without a failure are cached at once, and only the failed type is fetched again. `post.html` is written when every chunk that belongs on the page made it; a failed attachment does not hold it back, the page links only the attachments that landed.
- `PostDownloadRetrier` gives a post 5 attempts with a growing pause. A 400 or 403 from the CDN means the signed links expired: the post is fetched again once, with fresh links.
- Unexpected errors (a path too long for the OS, a broken JSON in a chunk) skip the post and let the run continue; 5 failed posts in a row stop the run, since a streak like that points at the disk, the permissions or the network.

## Page size and the 24-hour links

Media links in a listing answer are signed and live 24 hours from the fetch.

- The download walk uses small pages (5 posts) on purpose. Posts download one after another, and a small page means every link is still fresh when its post's turn comes.
- Metadata-only walks use pages of 100: counting posts in `check` and the `--dry-run` plan download nothing between pages, so nothing can get old - and the walk makes 20x fewer requests.
- If a link still expires mid-post (a huge video on a slow connection), the retrier fetches the post again with fresh links and continues from the content types that already finished.

## Layers

- `cli/` - typer commands, the composition root and console output
- `application/` - use cases, ports and mappers, orchestration
- `domain/` - pure post model, stdlib only
- `infrastructure/` - Boosty API client, downloaders, cache, HTML generator

The API contract changes without notice, so the API layer must survive unknown data - see [tolerant-reader.md](./tolerant-reader.md).
