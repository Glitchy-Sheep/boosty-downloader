# How downloading works

Boosty Downloader walks an author's blog page by page and saves every post to disk: media files plus a styled `post.html` snapshot.

## The pipeline

```
CLI (typer)
  └► use case (download all / single post)
        └► BoostyAPIClient - paginated fetch, rate limited
              └► PostDTO (pydantic models of the raw API answer)
                    └► post_mapper - DTO to domain Post
                          ├► downloads by content filters
                          ├► post.html render (Jinja)
                          └► cache update (SQLite)
```

1. **Fetch.** `BoostyAPIClient.iterate_over_posts` pages through `blog/{name}/post/` with a rate limiter. Each page turns into validated `PostDTO` objects.
2. **Cache check.** A SQLite cache keeps per-post flags by content type (files, videos, audio, ...). The run skips parts it already has.
3. **Map.** `map_post_dto_to_domain` turns API DTOs into domain chunks (text, image, video, file, audio, list). The domain layer knows nothing about Boosty shapes.
4. **Download.** Images, files and Boosty videos go through the aiohttp downloader; external videos (YouTube, Vimeo) go through yt-dlp.
5. **Render.** Chunks processed in this run become `post.html` via Jinja templates.
6. **Remember.** The cache records which content types finished, so the next run downloads only what is missing.

## Layers

- `cli/` - typer commands and console output
- `application/` - use cases and mappers, orchestration
- `domain/` - pure post model, stdlib only
- `infrastructure/` - Boosty API client, downloaders, cache, HTML generator

The API contract changes without notice, so the API layer must survive unknown data - see [tolerant-reader.md](./tolerant-reader.md).
