"""The file-action corpus uses every category and preserves portable file bytes."""

import json
from pathlib import Path

import pytest
from viewer_file_actions_e2e_sample import AUTHOR, MANIFEST, prepare

from boosty_downloader.domain.library_media import LibraryMediaView, MediaFilters
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader
from boosty_downloader.viewer.file_types import file_type


def test_file_action_corpus_has_real_sources_for_every_category(tmp_path: Path) -> None:
    root = tmp_path / 'files'
    prepare(root)
    reader = JsonLibraryReader(root)
    page = reader.list_media(AUTHOR, LibraryMediaView.file, MediaFilters())
    types = {file_type(item.entry.path or '') for item in page.items}
    assert types == {
        'pdf',
        'document',
        'book',
        'slides',
        'sheet',
        'image',
        'audio',
        'video',
        'archive',
        'model',
        'code',
        'font',
        'program',
        'script',
        'other',
    }
    assert any(item.entry.removed_at for item in page.items)
    sources: dict[str, str] = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    assert len(sources) == 27
    for destination, source in sources.items():
        assert (root / destination).read_bytes() == (root / source).read_bytes()
        name = Path(destination).name
        assert not set('<>:"/\\|?*').intersection(name)
        assert all(ord(char) >= 32 for char in name)
        assert name == name.rstrip(' .')
    assert any('  ' in name and ',' in name and '100%25' in name for name in sources)


def test_file_action_corpus_refuses_an_existing_directory(tmp_path: Path) -> None:
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'user.txt'
    sentinel.write_text('Preserve this library', encoding='utf-8')
    with pytest.raises(FileExistsError):
        prepare(existing)
    assert sentinel.read_text(encoding='utf-8') == 'Preserve this library'
