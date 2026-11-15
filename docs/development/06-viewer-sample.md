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

When ffmpeg is installed, it creates playable local media in several shapes and lengths. Without ffmpeg, the generator uses solid-colour images, WAV audio and bundled self-generated MP4 files. No extra runtime dependency is required. Media are generated once and reused within the sample, keeping disk usage small.

Recorded media sizes deliberately resemble real libraries, so storage charts show useful differences between authors. They are larger than the physical sample files. The sample uses the production JSON store and builds the disposable search index from those records.

## Reusing an output directory

The generator creates a new output directory and records its ownership and file fingerprints in `.sample-library.json`. An identical, unchanged sample can be reused with the same arguments. An arbitrary existing directory, changed files, different arguments or an incomplete previous generation cause an error. Choose a fresh `--out` in that case. There is no destructive reset option.

Viewing marks are user-owned data. Changing them while trying the viewer also changes the sample, so rerunning the generator does not silently reset them. The default `.sample/` directory is ignored by Git.

## Rebuilding pages

The sample contains canonical records; the offline renderer can build their pages. Render a normal independent copy when you want to preserve the original sample's realistic recorded sizes:

```bash
uv run python -c "import shutil; shutil.copytree('.sample/library', '.sample/render-copy')"
uv run python -m boosty_downloader.main render -o .sample/render-copy
```

`render` observes actual local files and records their physical sizes on the copy. It leaves media and viewing marks intact, and requires neither credentials nor a search index. Do not use hard links to copy canonical JSON files for this check.
