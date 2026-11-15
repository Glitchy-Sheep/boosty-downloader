"""Check that built distributions contain the renderer and offline viewer assets."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from tarfile import open as open_tar
from zipfile import ZipFile

PACKAGE = 'boosty_downloader/'
VIEWER = f'{PACKAGE}viewer/static/app/'
TEMPLATES = f'{PACKAGE}infrastructure/html_generator/templates/'
MINIMUM_TEMPLATE_COUNT = 7
COMPRESSED_SUFFIXES = ('.br', '.gz')


def check_distribution(path: Path) -> None:
    """Reject a wheel or source distribution missing required runtime assets."""
    names = _member_names(path)
    _require(names, f'{VIEWER}index.html', path)
    templates = {
        name for name in names if name.startswith(TEMPLATES) and name.endswith('.html')
    }
    if len(templates) < MINIMUM_TEMPLATE_COUNT:
        message = f'{path}: Jinja templates are missing from the distribution'
        raise ValueError(message)
    _check_viewer_assets(names, path)


def _check_viewer_assets(names: set[str], path: Path) -> None:
    for extension in ('.js', '.css'):
        assets = {
            name
            for name in names
            if name.startswith(VIEWER) and name.endswith(extension)
        }
        if not assets:
            message = f'{path}: no viewer {extension} assets in the distribution'
            raise ValueError(message)
        for asset in assets:
            for suffix in COMPRESSED_SUFFIXES:
                _require(names, asset + suffix, path)


def _member_names(path: Path) -> set[str]:
    if path.suffix == '.whl':
        with ZipFile(path) as archive:
            return {item.filename for item in archive.infolist() if not item.is_dir()}
    if path.name.endswith('.tar.gz'):
        with open_tar(path, 'r:gz') as archive:
            return {
                PurePosixPath(*PurePosixPath(item.name).parts[1:]).as_posix()
                for item in archive.getmembers()
                if item.isfile()
            }
    message = f'Unsupported distribution: {path}'
    raise ValueError(message)


def _require(names: set[str], name: str, archive: Path) -> None:
    if name not in names:
        message = f'{archive}: missing {name}'
        raise ValueError(message)


def main() -> None:
    """Verify every wheel and sdist in the requested output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist-dir', type=Path, default=Path('dist'))
    directory = parser.parse_args().dist_dir
    wheels = sorted(directory.glob('*.whl'))
    sources = sorted(directory.glob('*.tar.gz'))
    if not wheels or not sources:
        parser.error(f'Expected a wheel and a source distribution in {directory}')
    for archive in [*wheels, *sources]:
        check_distribution(archive)
        print(f'Runtime assets verified: {archive}')


if __name__ == '__main__':
    main()
