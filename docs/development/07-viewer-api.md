# Viewer read API

Start `boosty-downloader view -o LIBRARY --no-open`. The server exposes the following read routes without Boosty credentials. The packaged UI remains a shell until its data screens are connected.

| GET route | Result |
| --- | --- |
| `/api/authors` | Authors with indexed counts and recorded media sizes |
| `/api/authors/{author}` | One author with the same totals |
| `/api/authors/{author}/posts` | Filtered rows, month counts and total |
| `/api/authors/{author}/tags` | Exact tags and distinct post counts |
| `/api/authors/{author}/posts/{id}` | Current metadata/access, retained body, fresh marks and downloaded videos/audio/files |
| `/media/{author}/{path}` | An exact local file with Range, HEAD and conditional request support |

## Post filters

The posts route accepts `q`, `kind`, `unseen`, `fav`, `tag`, `locked`, `incomplete` and `order`. Filters combine. `kind` is `images`, `videos`, `files` or `audio`; `order` is `newest` (default) or `oldest`. Boolean flags accept only `0` and `1`, defaulting to false. A tag is exact and nonempty. An empty search is valid. Unknown parameters, repeated parameters and invalid values return 400 instead of silently weakening the selection.

Search matches are plain text runs with a `matched` flag. Render their text as text, including any literal HTML-looking source content. The post body is HTML from the same renderer as saved pages; it does not add search highlights itself. Unsafe link schemes are discarded in both representations while visible text is retained.

## Snapshots and paths

Lists, tags and author totals use the prepared index. A post detail reads its current canonical body, access overlay, marks and cover together through one reader operation. Canonical files are independent records, not a cross-file transaction. Lists may remain stale until the next preparation or writer update while a detail already reflects a changed or missing record. A read request never synchronizes the index or reconciles local media status.

Post and media paths in JSON are relative to the author. Author artwork URLs and HTML media URLs already point under `/media/`. Encode each stored path component once when building an address; literal percent signs, Cyrillic names, spaces, `#` and `?` must remain filenames. Media IDs are opaque values combining the full post ID and its media key, not disposable SQLite IDs.

Retained downloaded copies removed by the author remain in detail media. Missing files do not become downloads or record updates during reads; a later media request may return 404. `has_folder` reports whether the stored folder currently resolves within the author boundary. It grants no permission to open an application or folder on this computer.

## File responses and failures

Only listed authors can supply files. Resolved paths stay within their author directory, including contained symlinks. Raster images, audio, video, PDF and plain UTF-8 text may display inline. HTML, SVG, XML, MHTML and unknown types download with an inert sandbox. A confirmed generated `post.html`, requested by its exact canonical path, receives a scripted sandbox with an opaque origin. File bytes never come from a compressed sibling with a different name.

Expected failures share `{ "error": { "code": "...", "message": "..." } }`: invalid filters return 400, absent resources return 404, and unreadable or corrupt library data return 409 with `library_unavailable`. HTTP errors disclose no absolute library paths. Host/write guards retain their 421/403 responses. Reader I/O, file resolution and body rendering run in worker threads with independent SQLite connections.

The Python models generate `viewer-ui/src/lib/api.gen.ts`; run `task ui:types` after changing a contract. Focused HTTP checks run with `uv run pytest test/unit/viewer/ test/e2e/viewer_startup_test.py`.
