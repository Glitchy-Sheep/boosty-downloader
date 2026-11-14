# Viewer sample library

Generate local development data without a Boosty account or network access:

```bash
task viewer:sample
# Equivalent command, with the default values made explicit:
uv run python scripts/sample_library.py --out .sample/library --seed 7 --posts 1430
```

The default sample has three themed authors with 1,200, 160 and 70 posts. It includes saved and locked posts, links, favorites, playback positions, incomplete downloads and retained files that an author removed. Attachments cover the viewer's file categories, including a harmless program and script. The generator never executes these attachments.

Use a smaller sample for a quick check or a larger one for performance work:

```bash
task viewer:sample -- --out .sample/small --posts 24
task viewer:sample -- --out .sample/large --posts 5000 --seed 7
```

`--posts` is the exact total number of distinct post identities, including locked-only posts. The compact 24-post corpus covers the planned scenarios; smaller samples contain only a subset. IDs and content are deterministic for a given seed. Increasing the count preserves existing identities.

## Media and recorded sizes

When ffmpeg is installed, it creates playable local media in several shapes and lengths, including textured multi-MB JPEG photos with small 480 px copies. Without ffmpeg, photos are deterministic textured PNGs with thumbnails sampled from those same pixels; author artwork stays solid-colour, audio uses WAV and videos use bundled self-generated MP4 files. Both modes include landscape, portrait and square photos with actual originals larger than 2 MB. No extra runtime dependency is required. Assets are generated once and reused through hardlinks where supported, with a copying fallback.

Recorded media sizes deliberately resemble real libraries, so storage charts show useful differences between authors. They remain independent of physical file sizes. Measure HTTP response bytes or actual files when checking transfer budgets. Photos have separate author-relative thumbnails, locked teasers have their own thumbnail reference and videos reuse their previews. The sample uses the production JSON store and builds the disposable search index from those records.

## Reusing an output directory

The generator creates a new output directory and records its ownership and file fingerprints in `.sample-library.json`. An identical, unchanged sample can be reused with the same arguments. An arbitrary existing directory, changed files, different arguments or an incomplete previous generation cause an error. Choose a fresh `--out` in that case. There is no destructive reset option.

The thumbnail corpus uses sample-manifest version 2. Samples generated with version 1 are rejected without replacement; choose a fresh output directory to obtain the larger photos and thumbnails. This sample version is separate from the production library marker and canonical record schemas.

Viewing marks are user-owned data. Changing them while trying the viewer also changes the sample, so rerunning the generator does not silently reset them. The default `.sample/` directory is ignored by Git.

## Rebuilding pages

The sample contains canonical records; the offline renderer can build their pages. Render a normal independent copy when you want to preserve the original sample's realistic recorded sizes:

```bash
uv run python -c "import shutil; shutil.copytree('.sample/library', '.sample/render-copy')"
uv run python -m boosty_downloader.main render -o .sample/render-copy
```

`render` observes actual local files and records their physical sizes on the copy. It leaves media and viewing marks intact, and requires neither credentials nor a search index. Do not use hard links to copy canonical JSON files for this check.

## Measuring viewer queries

Generate the larger acceptance sample with 5,912 identities across its three authors, then measure with other tests and builds stopped:

```bash
task viewer:sample -- --out .sample/viewer-queries --posts 5912 --seed 7
uv run python scripts/benchmark_viewer_queries.py --root .sample/viewer-queries --samples 5 > /tmp/viewer-query-results.json
```

The benchmark validates the primary author's 5,000 posts and complete downloaded inventory: 10,532 items in All and 5,125 in Files, including 654 retained removed copies across these views. It measures fully materialized post, search and media queries. Each list's warm median must be below 300 ms; post detail must be below 150 ms. Invalid workloads or failed budgets produce a nonzero exit status.

The JSON report includes environment, first and warm timings, current mark-dependent selection sizes, uncompressed bytes and gzip bytes. Response mapping, mapping plus JSON, and mapping plus JSON plus gzip are measured separately from reader calls. They exclude HTTP transport; measure the running CLI separately when checking browser response time. Preparation and workload validation run before timings, so the first reported operation is not a cold-cache measurement. Changing viewing marks is allowed for measurements and is reported; the benchmark never resets them.
