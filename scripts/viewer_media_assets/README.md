# Media browser fixture previews

These three self-generated JPEGs are 480 pixels wide. They sample images 0, 1 and 2 from `library_sample.assets.create_assets(seed=57, backend=AssetBackend.fallback)`. The browser corpus keeps the matching PNG originals at 2400x1350, 1600x2400 and 2000x2000 (3.7-4.7 MB each), and gives every media item its own thumbnail path. The previews have the same aspect ratios as their originals; they are not placeholder pixels.

The JPEG files are committed so fixture generation needs no image library or ffmpeg in CI. Regenerate them from the repository root with ffmpeg installed:

```bash
PYTHONPATH=scripts uv run python - <<'PY'
from pathlib import Path
from subprocess import run
from tempfile import TemporaryDirectory

from library_sample.asset_models import AssetBackend
from library_sample.assets import create_assets

with TemporaryDirectory() as directory:
    assets = create_assets(Path(directory) / 'assets', seed=57, backend=AssetBackend.fallback)
    for index, image in enumerate(assets.images[:3]):
        destination = Path('scripts/viewer_media_assets') / f'preview-{index}.jpg'
        run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-i', str(image.path), '-vf', 'scale=480:-2', '-frames:v', '1',
            '-q:v', '4', str(destination),
        ], check=True)
PY
```

The first-screen transfer check applies to this representative JPEG corpus. The original noisy 480px PNG previews transferred about 11.4 MB for 35 tiles. The viewer serves stored thumbnails unchanged, and accepts formats and sizes beyond this fixture, so the 5 MB check is not a guarantee for every valid library.
