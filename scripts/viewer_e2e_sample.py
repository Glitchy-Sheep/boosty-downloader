"""Build a portable browser-test corpus without requiring ffmpeg."""

import sys
from pathlib import Path

from library_sample.asset_models import AssetBackend
from library_sample.generator import prepare_sample
from library_sample.models import SampleConfig

prepare_sample(Path(sys.argv[1]), SampleConfig(posts=24), backend=AssetBackend.fallback)
