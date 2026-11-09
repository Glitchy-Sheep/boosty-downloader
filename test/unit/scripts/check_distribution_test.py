"""Distribution checks protect both installation formats from missing assets."""

from __future__ import annotations

from io import BytesIO
from tarfile import TarInfo
from tarfile import open as open_tar
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest
from check_distribution import check_distribution

if TYPE_CHECKING:
    from pathlib import Path

VIEWER = 'boosty_downloader/viewer/static/app/'
TEMPLATES = 'boosty_downloader/infrastructure/html_generator/templates/'


def _members() -> set[str]:
    return {
        f'{VIEWER}index.html',
        f'{VIEWER}assets/app.js',
        f'{VIEWER}assets/app.js.br',
        f'{VIEWER}assets/app.js.gz',
        f'{VIEWER}assets/app.css',
        f'{VIEWER}assets/app.css.br',
        f'{VIEWER}assets/app.css.gz',
        *(f'{TEMPLATES}{number}.html' for number in range(7)),
    }


def _archive(tmp_path: Path, extension: str, members: set[str]) -> Path:
    path = tmp_path / f'package-1.0{extension}'
    if extension == '.whl':
        with ZipFile(path, 'w') as archive:
            for name in members:
                archive.writestr(name, b'asset')
    else:
        with open_tar(path, 'w:gz') as archive:
            for name in members:
                info = TarInfo(f'package-1.0/{name}')
                info.size = len(b'asset')
                archive.addfile(info, BytesIO(b'asset'))
    return path


@pytest.mark.parametrize('extension', ['.whl', '.tar.gz'])
def test_accepts_complete_runtime_assets(tmp_path: Path, extension: str):
    check_distribution(_archive(tmp_path, extension, _members()))


@pytest.mark.parametrize('extension', ['.whl', '.tar.gz'])
@pytest.mark.parametrize(
    'missing',
    [
        f'{VIEWER}index.html',
        f'{VIEWER}assets/app.js.br',
        f'{VIEWER}assets/app.css.gz',
        f'{TEMPLATES}0.html',
    ],
)
def test_rejects_missing_runtime_asset(tmp_path: Path, extension: str, missing: str):
    path = _archive(tmp_path, extension, _members() - {missing})
    with pytest.raises(ValueError, match='missing'):
        check_distribution(path)


@pytest.mark.parametrize('extension', ['.whl', '.tar.gz'])
@pytest.mark.parametrize('asset_extension', ['.js', '.css'])
def test_requires_script_and_style_assets(
    tmp_path: Path, extension: str, asset_extension: str
):
    members = {name for name in _members() if not name.endswith(asset_extension)}
    with pytest.raises(ValueError, match='no viewer'):
        check_distribution(_archive(tmp_path, extension, members))


def test_rejects_unsupported_archive_type(tmp_path: Path):
    with pytest.raises(ValueError, match='Unsupported distribution'):
        check_distribution(tmp_path / 'package.zip')
