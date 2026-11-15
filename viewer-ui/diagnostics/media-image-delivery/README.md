# Linux original-image delivery diagnostic

This branch is a disposable experiment based on `260f011`, not part of the product PR stack. A successful diagnostic workflow is not product acceptance. Any failed original assertion or invalid cell makes the final step fail, while `summary.json` keeps observation validity separate from the original test result.

The workflow runs only on pushes to `test/diagnose-media-transition`, with read-only repository permissions. One Ubuntu job uses the ordinary CI setup, locked dependencies, clean viewer build, Chromium version and virtual audio sink. Do not rerun this workflow to obtain a passing result.

## Four fixed cells

The order is `01-normal`, `02-held`, `03-held`, `04-normal`. Each step starts a separate Playwright CLI process with one worker and zero retries. The inherited worker-scoped browser therefore has a fresh lifecycle in each cell. The attachment records the actual worker PID and index; aggregation requires four distinct PIDs and identical collected browser/runtime metadata. Every step continues after an assertion failure so all four observations are retained. Missing or interrupted cells remain invalid.

Each cell runs the complete existing slow-Media test body byte for byte. Its actions and assertions, 650 ms API delay, 1100 ms capture, 260 ms animation, exact opacity/transform settling under 400 ms, 99% pane coverage, 30-second test timeout and 1200-second suite timeout are unchanged. The diagnostic config inherits the ordinary config. It changes only test discovery, output paths, Chromium selection, one worker and zero retries. The global sample setup is unused because the original media corpus owns its server. No browser flags, CPU throttling, source samplers or application files change. The job retains the ordinary 25-minute outer limit.

The reused image-delivery helper installs the same handler in both conditions. Normal immediately continues requests. Held delays only the five original Photo 02-06 B PNG requests until the first capture completes, then releases the original requests unchanged. The current post, APIs, thumbnails, video and audio are unaffected. Release runs in `finally`; a 5-second watchdog invalidates the cell. This isolates the contribution of the five-original delivery/processing path as a whole, not the browser decoder alone.

## Evidence and validity

`provenance.json` pins the untouched original case, sampler, runtime CSS, fixture generators, dependency lock and ordinary CI, plus the previously approved six packaged asset hashes. These hashes are not generated from or adjusted to the experimental CI output. Each clean build must reproduce the raw and Brotli bytes before its browser cell runs. For the two gzip assets, comparison copies the complete stream and normalizes only header byte 9 (the operating-system marker) to 255; every other byte remains pinned. The canonical pins come from the previously approved Mac streams, whose original full hashes remain in the manifest. Decompression must also match the existing raw asset hash. Served files are never modified. The original five synthetic images must each be 4,532,573 bytes with the fixed approved SHA-256. No real library, credentials, environment dump or user media is checked in.

Frame and performance attachments use the original sampler. The helper records route timings, bounded passive load events and post-capture decode completion. Node and page performance clocks remain separate. Aggregation requires exactly one request and one decoded image for each target, no watchdog, correct release ordering and, for held images, response completion strictly after the page capture ends. The post-capture decode wait does not measure pure decoder CPU cost.

Per-cell `results.json` preserves all original results and error details. `artifacts/` contains actual worker browser metadata, failure screenshots and server output. `raw/` contains decoded frame, performance, image-delivery, image-manifest and worker-identity attachments. Each snapshot retains the actual full gzip hash and OS byte as well as the canonical and decoded-payload hashes. All four before snapshots must exactly match the final snapshot, including actual full hashes and OS markers; no performance or validity failure is retried or converted into a pass.

If normal cells fail while held cells consistently lose the late endpoint gap, that supports an image-delivery-path contribution on this host. If normal cells do not reproduce the CI failure, the experiment is inconclusive for that failure. Stop after these four cells in either case; additional profiling or preservation of suite history needs a separate proposal.

The initial run `43733777638` stopped all four cells in preflight because gzip's OS marker differed between Mac (19) and Unix (3). Zero browser cases ran, so it supplied no performance observations. The platform-independent check above addresses that preflight defect; it does not change the four-cell experiment or its acceptance gates.

## Commands

Browserless validation:

```sh
npx tsc -p diagnostics/media-image-delivery/tsconfig.json
npx oxlint --deny-warnings diagnostics/media-image-delivery
npx oxfmt --check diagnostics/media-image-delivery
node --test diagnostics/media-image-delivery/protocol.test.mjs
```

One cell, only after execution approval:

```sh
BOOSTY_MEDIA_CELL=01-normal node diagnostics/media-image-delivery/protocol.mjs verify
BOOSTY_MEDIA_CELL=01-normal npx playwright test -c diagnostics/media-image-delivery/playwright.config.ts
```

Summarize the fixed four-cell set:

```sh
node diagnostics/media-image-delivery/protocol.mjs summarize
```
