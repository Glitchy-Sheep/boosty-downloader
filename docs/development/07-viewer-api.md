# Viewer API

Start `boosty-downloader view -o LIBRARY --no-open`. The server exposes the following read routes without Boosty credentials. The packaged UI remains a shell until its data screens are connected.

| GET route | Result |
| --- | --- |
| `/api/authors` | Authors with indexed counts and recorded media sizes |
| `/api/authors/{author}` | One author with the same totals |
| `/api/authors/{author}/posts` | Filtered rows, month counts and total |
| `/api/authors/{author}/tags` | Exact tags and distinct post counts |
| `/api/authors/{author}/media` | Filtered downloaded media, shared post metadata, view counts and missing pieces |
| `/api/opener` | Available local file actions and system; no local root for an ineligible request |
| `/api/authors/{author}/posts/{id}` | Current metadata/access, retained body, fresh marks and downloaded videos/audio/files |
| `/media/{author}/{path}` | Local media with Range, HEAD and conditional request support; confirmed generated pages use an adapted HTTP representation |

## Post filters

The posts route accepts `q`, `kind`, `unseen`, `fav`, `tag`, `locked`, `incomplete` and `order`. Filters combine. `kind` is `images`, `videos`, `files` or `audio`; `order` is `newest` (default) or `oldest`. Boolean flags accept only `0` and `1`, defaulting to false. A tag is exact and nonempty. An empty search is valid. Unknown parameters, repeated parameters and invalid values return 400 instead of silently weakening the selection.

Search matches are plain text runs with a `matched` flag. Render their text as text, including any literal HTML-looking source content. The post body is HTML from the same renderer as saved pages; it does not add search highlights itself. Unsafe link schemes are discarded in both representations while visible text is retained.

## Media filters

The media route accepts `view=all|images|videos|audio|files`, `order=newest|oldest`, `unseen=0|1` and `fav=0|1`. Defaults are All, newest first and no mark filters. Unknown or repeated parameters and other values return 400. All combines images, both video sources and audio; files have their own view.

Only recorded downloaded pieces are listed. Copies retained after the author removed a piece or locked its post remain available. Current pieces precede removed copies in either date order. Equal dates use the full post ID, then inventory position and media ID for stable ordering. `posts` contains each listed post's metadata once, keyed by its full ID.

Favorites filter the owning post. Unseen filters individual pieces: playback is unfinished, and the post has no seen mark or the piece was added after that mark. A new piece does not put older pieces from the same seen post back in Unseen. The shared post's `seen` flag reports its mark even when a new piece appears in Unseen.

Counts apply the same mark filters across every view, independently of the selected view. `counts.all` excludes files. `missing` counts current pending, failed, unavailable and locally deleted pieces in the selected view; removed pieces without a downloaded copy do not count. List and count queries share one index snapshot. An unfiltered kind view's recorded sizes sum to the author's storage total for that kind, without reading media files.

## Snapshots and paths

Lists, tags and author totals use the prepared index. A post detail reads its current canonical body, access overlay, marks and cover together through one reader operation. Canonical files are independent records, not a cross-file transaction. Lists may remain stale until the next preparation or writer update while a detail already reflects a changed or missing record. A read request never synchronizes the index or reconciles local media status.

Post and media paths in JSON are relative to the author. Author artwork URLs and HTML media URLs already point under `/media/`. Encode each stored path component once when building an address; literal percent signs, Cyrillic names, spaces, `#` and `?` must remain filenames. Media IDs are opaque values combining the full post ID and its media key, not disposable SQLite IDs.

Retained downloaded copies removed by the author remain in detail media. Missing files do not become downloads or record updates during reads; a later media request may return 404. `has_folder` reports whether the stored folder currently resolves within the author boundary. It grants no permission to open an application or folder on this computer.

## File responses and failures

Only listed authors can supply files. Resolved paths stay within their author directory, including contained symlinks. Raster images, audio, video, PDF and plain UTF-8 text may display inline. HTML, SVG, XML, MHTML and unknown types download with an inert sandbox. A confirmed generated `post.html`, requested by its exact canonical path, receives a scripted sandbox with an opaque origin. File bytes never come from a compressed sibling with a different name.

For a confirmed generated page, the HTTP response rewrites local image, audio, video and poster URLs with signatures for individual resources. Stored HTML and links to other pages stay unchanged. Each server instance uses a new signing key; a signature is bound to one author-relative path and remains valid for that instance so later seeking still works. The media route verifies the signature, containment and resolved file type before permitting cross-origin embedding of raster images, audio or video. Ordinary media URLs, errors, HTML/SVG and document downloads retain `Cross-Origin-Resource-Policy: same-origin`; no CORS access is granted. Adapted pages and signed media responses use `Cache-Control: no-store`.

The saved-page theme switcher tolerates unavailable browser storage. In a sandbox it changes only the current page; it does not read or write the viewer's theme preference.

Expected failures share `{ "error": { "code": "...", "message": "..." } }`: invalid filters return 400, absent resources return 404, and unreadable or corrupt library data return 409 with `library_unavailable`. HTTP errors disclose no absolute library paths. Host/write guards retain their 421/403 responses. Reader I/O, file resolution and body rendering run in worker threads with independent SQLite connections.

The Python models generate `viewer-ui/src/lib/api.gen.ts`; run `task ui:types` after changing a contract. Focused HTTP checks run with `uv run pytest test/unit/viewer/ test/e2e/viewer_startup_test.py`.

## User marks

Writes require `application/json`. When present, `Origin` and `Sec-Fetch-Site` must identify a same-origin request. Writes change viewing marks, preserving downloaded content and media. The packaged shell does not yet expose these controls.

| Route | Body and result |
| --- | --- |
| `PUT /api/authors/{author}/posts/{id}/marks` | Exactly one of `{ "seen": true }` or `{ "favorite": true }`; returns the fresh post row and author totals. Use false to clear a mark. |
| `POST /api/authors/{author}/marks` | `{ "seen": true, "filters": {} }`; applies the same normalized filters as the post list and returns `{ "count": N }` for actual changes. |
| `GET /api/authors/{author}/marks/progress` | Active bulk state with `active`, nullable `total`, `completed` and `changed`; accepts no query parameters or body. |
| `PUT /api/authors/{author}/media/{id}/position` | `{ "seconds": 120, "duration": 1800 }`; returns the media item with its saved position and finished state. |

Mark values are strict booleans. Playback values are finite, nonnegative numbers; booleans, strings, NaN and Infinity are invalid. Invalid bodies and malformed media identities return 400. An unknown resource returns 404. Locked posts reject seen/favorite changes with 409 and are excluded from bulk marking. Previously saved marks remain intact. Playback still works for downloaded video/audio retained after a post became locked or the author removed the piece.

Opening a post never marks it seen. New pieces make a previously seen post Updated; a text-only edit or a returning piece with its original addition time does not. Marking it seen again acknowledges the newest observed content. If imported addition times are ahead of the local clock, this watermark is no earlier than those times. Favorite and playback changes preserve the seen mark.

A position in the last 10 seconds, or last 5 percent when shorter, is finished. A 24-second clip therefore finishes at 22.8 seconds. Finished playback stores a zero position for the next play; saving an earlier position clears the finished state. Zero duration means unknown duration and does not mark completion. Finishing media does not mark the entire post seen.

## Bulk progress and failure recovery

Bulk selection captures the filtered identities before changing their marks. Progress reports handled identities and actual changes separately, including no-ops in `completed`. During selection `total` is null. Poll progress while the POST is pending; its final response determines success. An idle progress response has `active=false`, null total and zero counts, and is not evidence of a successful POST.

Only one bulk per author runs in a viewer instance. Another returns 409 with `marks_busy`. Disconnecting the browser does not cancel writes or release the active operation early; shutdown waits for its worker. Progress state exists only during that operation.

Each mark is saved to canonical storage before its index projection. If an index update fails, the request returns 409 and already saved marks remain. Repeating the same request repairs the projection even when the canonical value is already correct. Bulk failure keeps the successfully saved prefix; refresh list/author data after an error. Request mutations serialize within the shared reader instance; separate viewer processes have no shared mutation lock.

## Local file actions

`GET /api/opener` reports `open`, `reveal`, `folders`, `system`, `root` and the system path separator `sep`. It is not cached. Ineligible requests receive disabled capabilities and no root path. The packaged shell does not yet show the action buttons.

| POST route | Required JSON body |
| --- | --- |
| `/api/authors/{author}/media/{id}/open` | `{ "reveal": false }` to open; `{ "reveal": true }` to reveal in the file manager |
| `/api/authors/{author}/posts/{id}/open` | `{}` to open the saved post folder |

The media ID is the opaque ID from a media response. Both routes return 204 on success. The server obtains the recorded path from the index and checks it within the author's directory; clients supply no paths. Retained downloaded files remain eligible after removal or loss of post access. A missing file returns 404. A symlink whose target has a different file type can be revealed but cannot be opened. Post-folder symlinks cannot be opened.

Opening uses the system's default application, as a double-click does, including programs and scripts. Reveal selects the file where the file manager supports it. macOS uses Finder, Windows uses Explorer, Linux uses the desktop file manager with a folder fallback, and Termux supports opening files without reveal or folder actions. A reported OS failure returns 409 with its reason; a successful handoff does not prove the target application has finished loading.

These actions require a matching `Origin`, JSON and a browser on the viewer's own computer: loopback or the local address of the accepted connection. The Host must be localhost or an IP literal. Machine-name URLs, forwarded/proxy headers and other devices receive no local actions. When supplied on the capabilities GET, Origin and fetch metadata must also be valid; that GET does not require Origin. SSH disables real openers. Linux additionally requires a graphical session and `xdg-open`. Ordinary browsing remains available in these environments.

For local development, set `BOOSTY_VIEWER_OPEN_LOG` to a temporary JSONL path before starting `view`. The CLI announces recording mode; actions append their name and absolute resolved path without opening anything. This explicit hook works without a desktop and over SSH, while HTTP request guards still apply. Use it to check file actions on synthetic libraries. The ordinary application factory defaults to no opener; the CLI injects the detected system opener.
