# Library viewer

Browse downloaded posts, photos, videos, audio and files in your browser. The viewer reads the saved library and needs no Boosty credentials or Internet connection. Keep its local server running while browsing or reloading the page; links to unsaved posts and external sites still need their usual network access.

## Start the viewer

```bash
boosty-downloader view -o ./v5-downloads
boosty-downloader view -o ./v5-downloads --no-open --port 8314
```

The first command opens the browser at the printed localhost address. It tries port 8314, then the next free port. An explicit `--port` must be available. `--no-open` prints the address without launching a browser; Ctrl+C stops the server. If a fixed port remains busy just after shutdown, wait for connections to close or choose another port.

The destination and index location can come from your YAML settings. Global `--config PATH` selects that file, and `view --cache-dir PATH` puts the disposable index at `PATH/index.db`. The command loads only path settings and does not authenticate with Boosty. An empty library shows a download hint. Older, unmarked downloads show an explanation without being adopted or modified; use a separate v5 destination and keep the old library. See [library storage](library-storage.md#moving-from-v4).

## Posts and media

The authors page shows saved artwork, post counts and recorded downloaded-media sizes. These sizes include retained downloaded copies, but exclude pages, records and auxiliary images. They come from saved records rather than a fresh scan of every file.

Open an author to read its newest post. Search titles and text, combine media-kind, unseen, favorite, tag, locked and incomplete filters, and change the order. The address preserves these choices across reload, Back and Forward. Filters affect the timeline; an already selected post remains readable even when it is outside the filtered results. **Jump to month** moves the timeline without changing that post. Its choices follow the filtered results and manual scrolling; **Jump to month start** returns to the first post of the current month.

Posts contain the complete saved body, downloaded media and placeholders for missing pieces. Previously saved content remains available after remote access closes. Links to other saved posts open their local copies. The **Media** tab groups downloaded items into All, Photos, Videos, Audio and Files; All contains photos, videos and audio. Each tab keeps its own filters and scroll position. Media offers oldest/newest order and Unseen and Favorites filters in the address. Unseen excludes finished pieces and media of seen posts while keeping newly added content. Missing pieces are counted, and retained files removed by the author appear in a separate section.

In Media, open a photo or video tile for fullscreen viewing. Arrow keys browse the list, Escape or Back closes it, and a focused video keeps its native seeking keys. The heart uses the post's favorite mark; the post link opens that post with its filters cleared.

## Marks and playback

Opening or playing a post does not mark it seen. Use **Mark as seen** deliberately. New media added later makes the post unseen again and shows **Updated**; marking it seen acknowledges that update. Favorites are shared between post rows, pages and media. **Mark posts** applies seen or unseen to the current filtered list after confirming the count. It reports progress, preserves completed changes on failure and continues when you close the dialog. Locked posts retain their marks.

Audio and video resume from saved positions and offer **Start over**. Progress is saved every five seconds while playing, on pause, after seeking while paused and when leaving the page. A position within the last ten seconds or five percent, whichever is shorter, counts as finished and starts from the beginning next time. Final page-close saves are best effort and require the server to remain available.

Starting audio from All or Audio creates a queue from that filtered list. The bottom player keeps playing across posts, tabs and authors, with previous/next, 15-second jumps, speed and seeking. It advances at the end of a track or after an unplayable track. Starting another player pauses the current one. Inline media in a hidden tab pauses; the bottom player can continue across tabs.

## Sidebar and keyboard

On desktop, drag the sidebar between 260 and 640 pixels or double-click its edge to reset to 360. The focused edge supports arrow keys, Home/End and Enter. The header button collapses or expands it; the browser remembers its chosen width and collapse state. Temporary window compression preserves the preferred width. The open post and its players stay mounted while the layout changes. Reduced motion disables the glide.

On phones, the header button opens the sidebar over the post without focusing search or requesting the on-screen keyboard. Selecting a post or switching to Media closes it. `/` opens it and focuses search. Tab remains within the active panel or its nested dialog; Escape clears or leaves search before closing the panel. Draft search text and the timeline position survive closing and reopening it and switching between phone and desktop layouts.

| Key | Action in Posts |
| --- | --- |
| `j` / `k` | Next / previous post in the filtered timeline |
| `/` | Open the sidebar, focus search and select its text |
| `[` | Open or close the sidebar |
| `s` | Toggle the selected post's seen mark |
| `f` | Toggle the selected post's favorite mark |

These shortcuts use physical key positions, including with a Russian keyboard layout. Text fields, native media controls, dialogs and menus retain their own keys. The open phone sidebar handles only its `/` and `[` shortcuts outside text fields; post navigation and mark shortcuts remain inactive behind it. Modified shortcuts are ignored. Sidebar controls and post shortcuts are inactive in Media. Escape in search clears nonempty text, then removes focus when search is empty.

## Files on this computer

File rows and post attachments show the saved filename, type and size. Clicking a row or filename does not open it. Available actions appear as buttons or in **More** on narrow and touch views; files, audio and media tiles also support right-click or long press.

| Action | Result |
| --- | --- |
| **Open in default app** | Hand the saved file to its registered application on the server's computer |
| **Show in Finder/Explorer** | Reveal the file; Linux may open its containing folder |
| **Copy path** | Copy the local path, or leave it visible for manual copying |
| **Download a copy** | Download through the browser |
| Post folder button | Open the saved post's folder when the system supports it |

Opening audio or video in another app pauses its viewer player. Reveal, Copy and Download preserve playback. System errors remain visible until dismissed, including inside fullscreen viewing.

Local actions require a supported desktop opener and a connection from the same computer through localhost or an IP address. Opening the viewer by the computer's hostname does not enable these actions. They are unavailable for SSH sessions and Linux without a desktop opener. Termux can open files when `termux-open` is available, but does not offer Reveal or post-folder actions. Remote browsers retain Download and **View in a new tab** for supported formats; actual playback or display depends on their browser.

**Open acts like opening the file in the system's file manager. A program can start, and a script may execute according to its file association.** Known program and script extensions are labelled, but those labels are not a content scan or a guarantee that other files are safe.

The downloader does not itself add macOS quarantine metadata or Windows Mark of the Web to transferred files. Do not rely on an Internet-download warning or Office Protected View when using either Open or Finder/Explorer. Quarantine and origin marks participate in those protections, but other operating-system, application and organization policies may still warn or block a file. Microsoft also documents Protected View triggers such as unsafe locations and file-validation failures. See [Apple's quarantine settings](https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/LaunchServicesKeys.html), [Microsoft's Mark of the Web guidance](https://learn.microsoft.com/en-us/deployoffice/security/internet-macros-blocked) and [Protected View](https://support.microsoft.com/en-us/office/collab-files/what-is-protected-view).

## Access from another device

```bash
boosty-downloader view -o ./v5-downloads --lan
```

Open the printed network address from a device on your trusted local network. The computer and viewer server must stay running, and the firewall must permit the connection. The server uses plain HTTP and has no login or separate user accounts. Anyone who can reach it can browse and download the served library and change its viewing marks. Use `--lan` only on a network whose connected users you trust.

Open and Reveal are restricted to the server's own computer. This is a browser/request boundary, not authentication of a person or operating-system account. A process, or another user on a shared computer, that can connect locally can request that indexed library files be opened as the user running the viewer. Run it only where that local trust is acceptable.

Do not expose the viewer through port forwarding, a reverse proxy or a public tunnel. A proxy can also make remote requests appear local and invalidate the desktop-action trust boundary. The viewer's host and origin checks do not turn it into an authenticated public file service.

## Saved data and recovery

| Data | Location and purpose |
| --- | --- |
| Complete posts and media | Each post's `post.json` and media directories; the authoritative library content |
| Seen, favorite and playback marks | `viewer.json` beside `post.json`; shared by browsers using this library |
| Author details and access observations | The author's `.boosty-downloader/author.json` and `locked.json` |
| Image thumbnails | The author's `.boosty-downloader/thumbs/`; video covers reuse saved previews |
| Search index | `.boosty-downloader/index.db` at the library root, or `PATH/index.db` with `--cache-dir PATH` |

Starting the viewer synchronizes the disposable index. Marks are saved separately from downloaded content and survive downloads, index rebuilds and library moves when the library's internal layout is kept. Back up the whole library, including `viewer.json`; the index alone is not a backup. Sidebar preferences belong to the browser, not to these marks.

The viewer uses saved thumbnails and falls back to local originals. It does not fetch missing images or media from Boosty. Later download runs can fill missing thumbnails; see [library storage](library-storage.md). Supported local media can seek without downloading the whole file first. HTML and SVG attachments are offered as downloads, while verified generated post pages served by the viewer use a sandbox. These browser restrictions do not sandbox a file opened in an external application.

If the index needs rebuilding, run `boosty-downloader reindex -o LIBRARY`. To rebuild standalone `post.html` pages from saved records and current files, use `boosty-downloader render -o LIBRARY`. Both work without Boosty credentials; see [the index](library-index.md) and [library storage](library-storage.md).
