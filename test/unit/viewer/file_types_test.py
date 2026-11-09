from __future__ import annotations

import pytest

from boosty_downloader.viewer.file_types import file_type, suffix


@pytest.mark.parametrize(
    ('name', 'kind'),
    [
        ('notes.PDF', 'pdf'),
        ('lecture.docm', 'document'),
        ('book.epub', 'book'),
        ('numbers.xlsm', 'sheet'),
        ('slides.pptm', 'slides'),
        ('picture.svg', 'image'),
        ('song.flac', 'audio'),
        ('movie.mkv', 'video'),
        ('archive.tar.gz', 'archive'),
        ('figure.blend', 'model'),
        ('page.html', 'code'),
        ('symbols.woff2', 'font'),
        ('invoice.pdf.exe', 'program'),
        ('setup.exe.', 'program'),
        ('setup.EXE  . ', 'program'),
        ('.exe', 'program'),
        ('..exe', 'program'),
        ('shortcut.desktop', 'program'),
        ('profile.mobileconfig', 'program'),
        ('file.settingcontent-ms', 'program'),
        ('script.py', 'script'),
        ('manual.chm', 'script'),
        ('привет, мир.command', 'script'),
        ('unknown', 'other'),
        ('unknown.strange', 'other'),
        ('photo.png::$DATA', 'other'),
    ],
)
def test_stored_names_use_the_system_suffix(name: str, kind: str):
    assert file_type(name) == kind


@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('folder.with.dot/README', ''),
        ('folder\\SETUP.exe.', '.exe'),
        ('cafe\u0301.exE', '.exe'),
        ('file.e\u0301', '.é'),
        ('... ', ''),
        ('', ''),
    ],
)
def test_suffix_normalizes_name_without_filesystem_access(name: str, expected: str):
    assert suffix(name) == expected
