"""File discovery and name reservation respect retained ownership and disk evidence."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import PurePosixPath

import pytest

from boosty_downloader.application.media_paths import (
    DiskSnapshot,
    FileMatch,
    MediaPathHint,
    find_media_file,
    find_recorded_file,
    reserve_media_path,
)
from boosty_downloader.infrastructure.path_sanitizer import MAX_NAME_BYTES

MEDIA_ID = 'file:abcdefgh-first'
OTHER_ID = 'file:abcdefgh-second'


def test_allocator_keeps_the_directory_and_sanitizes_the_basename():
    assert (
        reserve_media_path('files/a:b?.zi?p', MEDIA_ID, DiskSnapshot({}), {})
        == 'files/ab.zip'
    )


def test_allocator_avoids_files_occupied_paths_and_retained_reservations():
    disk = DiskSnapshot(
        files={'files/archive.zip': 20},
        occupied=frozenset({'files/archive (abcdefgh).zip'}),
    )
    reservations = {'file:removed': 'files/archive (abcdefgh-2).zip'}

    assert (
        reserve_media_path('files/archive.zip', MEDIA_ID, disk, reservations)
        == 'files/archive (abcdefgh-3).zip'
    )


def test_different_ids_with_the_same_prefix_get_distinct_reserved_names():
    disk = DiskSnapshot({'files/archive.zip': 20})
    first = reserve_media_path('files/archive.zip', MEDIA_ID, disk, {})
    second = reserve_media_path('files/archive.zip', OTHER_ID, disk, {MEDIA_ID: first})

    assert first == 'files/archive (abcdefgh).zip'
    assert second == 'files/archive (abcdefgh-2).zip'


@pytest.mark.parametrize('source', ['file', 'occupied', 'reservation'])
def test_case_and_unicode_equivalent_paths_are_occupied(source: str):
    equivalent = 'files/Cafe\u0301.ZIP'
    disk = DiskSnapshot(
        files={equivalent: 20} if source == 'file' else {},
        occupied=frozenset({equivalent}) if source == 'occupied' else frozenset(),
    )
    reservations = {OTHER_ID: equivalent} if source == 'reservation' else {}

    assert (
        reserve_media_path('files/Café.zip', MEDIA_ID, disk, reservations)
        == 'files/Café (abcdefgh).zip'
    )


def test_allocator_preserves_extension_and_collision_marker_after_unicode_truncation():
    preferred = f'files/{"я" * 300}.zip'
    first = reserve_media_path(preferred, MEDIA_ID, DiskSnapshot({}), {})
    second = reserve_media_path(preferred, MEDIA_ID, DiskSnapshot({first: 20}), {})

    assert first != second
    assert first.endswith('.zip')
    assert second.endswith(' (abcdefgh).zip')
    for path in (first, second):
        assert len(PurePosixPath(path).name.encode('utf-8')) <= MAX_NAME_BYTES


def test_external_collision_token_uses_the_complete_url():
    url = 'https://video.example/watch?v=lesson&part=2'
    disk = DiskSnapshot({'videos/lesson.mp4': 20})
    token = sha256(url.encode()).hexdigest()[:8]

    assert (
        reserve_media_path('videos/lesson.mp4', f'external_video:{url}', disk, {})
        == f'videos/lesson ({token}).mp4'
    )


def test_recorded_file_is_preferred_over_other_matching_names():
    disk = DiskSnapshot({'files/previous.zip': 12, 'files/archive.zip': 12})

    assert find_media_file(
        MEDIA_ID,
        disk,
        {},
        recorded_path='files/previous.zip',
        preferred=MediaPathHint('files/archive.zip'),
        expected_size=12,
    ) == FileMatch(path='files/previous.zip', size=12)


def test_invalid_recorded_candidate_does_not_hide_a_valid_preferred_file():
    disk = DiskSnapshot({'files/previous.zip': 11, 'files/archive.zip': 12})

    assert find_media_file(
        MEDIA_ID,
        disk,
        {},
        recorded_path='files/previous.zip',
        preferred=MediaPathHint('files/archive.zip'),
        expected_size=12,
    ) == FileMatch(path='files/archive.zip', size=12)


@pytest.mark.parametrize(
    ('actual_size', 'expected_size', 'expected'),
    [
        (0, None, None),
        (0, 0, None),
        (11, 12, None),
        (12, 12, FileMatch(path='file.zip', size=12)),
        (12, None, FileMatch(path='file.zip', size=12)),
    ],
    ids=['empty', 'known-empty', 'wrong-size', 'matching-size', 'unknown-size'],
)
def test_initial_discovery_requires_a_nonempty_plausible_file(
    actual_size: int,
    expected_size: int | None,
    expected: FileMatch | None,
):
    assert (
        find_media_file(
            MEDIA_ID,
            DiskSnapshot({'file.zip': actual_size}),
            {},
            preferred=MediaPathHint('file.zip'),
            expected_size=expected_size,
        )
        == expected
    )


def test_another_retained_owner_blocks_adoption_with_equivalent_spelling():
    disk = DiskSnapshot({'files/Café.zip': 12})
    reservations = {OTHER_ID: 'files/Cafe\u0301.ZIP'}

    assert (
        find_media_file(
            MEDIA_ID,
            disk,
            reservations,
            recorded_path='files/Café.zip',
            preferred=MediaPathHint('files/Café.zip'),
            expected_size=12,
        )
        is None
    )


def test_current_owner_can_discover_its_recorded_reserved_file():
    path = 'files/archive.zip'

    assert find_media_file(
        MEDIA_ID,
        DiskSnapshot({path: 12}),
        {MEDIA_ID: path},
        recorded_path=path,
        expected_size=12,
    ) == FileMatch(path=path, size=12)


def test_numbered_family_is_scanned_numerically_even_when_earlier_names_are_missing():
    disk = DiskSnapshot(
        {
            'files/archive (abcdefgh-10).zip': 12,
            'files/archive (abcdefgh-2).zip': 12,
            'files/archive (other-id).zip': 12,
        }
    )

    assert find_media_file(
        MEDIA_ID,
        disk,
        {},
        preferred=MediaPathHint('files/archive.zip'),
        expected_size=12,
    ) == FileMatch(path='files/archive (abcdefgh-2).zip', size=12)


@pytest.mark.parametrize(
    ('observed', 'expected'),
    [
        ('videos/lecture.v1', FileMatch(path='videos/lecture.v1', size=12)),
        ('videos/lecture.v1.mp4', FileMatch(path='videos/lecture.v1.mp4', size=12)),
        ('videos/lecture.v1.mp4.backup', None),
        ('videos/lecture.mp4', None),
    ],
    ids=['no-suffix', 'observed-suffix', 'extra-suffix', 'lost-title-segment'],
)
def test_response_suffix_matching_preserves_the_complete_dotted_title(
    observed: str,
    expected: FileMatch | None,
):
    assert (
        find_media_file(
            'boosty_video:abcdefgh-first',
            DiskSnapshot({observed: 12}),
            {},
            preferred=MediaPathHint('videos/lecture.v1', suffix_from_response=True),
        )
        == expected
    )


def test_response_suffix_matching_finds_a_numbered_existing_file():
    observed = 'videos/lecture.v1 (abcdefgh-3).webm'

    assert find_media_file(
        'boosty_video:abcdefgh-first',
        DiskSnapshot({observed: 12}),
        {},
        preferred=MediaPathHint('videos/lecture.v1', suffix_from_response=True),
    ) == FileMatch(path=observed, size=12)


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        ('.file.part', None),
        ('file.part', FileMatch(path='file.part', size=12)),
        ('.cover', FileMatch(path='.cover', size=12)),
    ],
    ids=['download-temporary', 'ordinary-part-attachment', 'ordinary-dotfile'],
)
def test_only_hidden_part_files_are_temporary(
    path: str,
    expected: FileMatch | None,
):
    disk = DiskSnapshot({path: 12})

    assert find_recorded_file(path, disk) == expected
    assert (
        find_media_file(
            MEDIA_ID, disk, {}, recorded_path=path, preferred=MediaPathHint(path)
        )
        == expected
    )


@pytest.mark.parametrize('actual_size', [0, 999])
def test_recorded_downloaded_files_keep_actual_size_even_after_user_edits(
    actual_size: int,
):
    assert find_recorded_file(
        'files/archive.zip', DiskSnapshot({'files/archive.zip': actual_size})
    ) == FileMatch(path='files/archive.zip', size=actual_size)


def test_recorded_file_discovery_reports_absence_without_guessing():
    assert (
        find_recorded_file(
            'files/archive.zip', DiskSnapshot({'files/archive.zip.backup': 12})
        )
        is None
    )


def test_external_files_are_adopted_only_from_their_recorded_path():
    path = 'videos/lesson.mp4'
    media_id = 'external_video:https://video.example/watch?v=lesson'
    disk = DiskSnapshot({path: 12})
    hint = MediaPathHint(path)

    assert find_media_file(media_id, disk, {}, preferred=hint) is None
    assert find_media_file(
        media_id, disk, {}, recorded_path=path, preferred=hint
    ) == FileMatch(path=path, size=12)


def test_discovery_returns_the_actual_case_and_unicode_spelling_from_disk():
    observed = 'files/Cafe\u0301.ZIP'
    disk = DiskSnapshot({observed: 12}, aliases={'files/Café.zip': observed})

    assert find_recorded_file('files/Café.zip', disk) == FileMatch(
        path=observed, size=12
    )
    assert find_media_file(
        MEDIA_ID, disk, {}, preferred=MediaPathHint('files/Café.zip')
    ) == FileMatch(path=observed, size=12)


def test_path_operations_do_not_mutate_snapshot_or_reservations():
    files = {'files/archive.zip': 12}
    occupied = {'files/unrelated'}
    reservations = {OTHER_ID: 'files/removed.zip'}
    aliases = {'files/Archive.zip': 'files/archive.zip'}
    disk = DiskSnapshot(files, occupied, aliases=aliases)
    original = deepcopy((files, occupied, aliases, reservations))

    reserve_media_path('files/archive.zip', MEDIA_ID, disk, reservations)
    find_media_file(
        MEDIA_ID, disk, reservations, preferred=MediaPathHint('files/archive.zip')
    )
    find_recorded_file('files/archive.zip', disk)

    assert (files, occupied, aliases, reservations) == original


@pytest.mark.parametrize('file_exists', [False, True])
def test_own_reservation_allows_absent_path_but_never_overwrites_a_file(
    *,
    file_exists: bool,
):
    path = 'files/archive.zip'
    disk = DiskSnapshot({path: 12} if file_exists else {})
    expected = 'files/archive (abcdefgh).zip' if file_exists else path

    assert reserve_media_path(path, MEDIA_ID, disk, {MEDIA_ID: path}) == expected


@pytest.mark.parametrize(
    ('recorded', 'observed'),
    [
        ('files/archive.zip', 'files/Archive.zip'),
        ('files/Café.zip', 'files/Cafe\u0301.zip'),
        ('files/strasse.zip', 'files/straße.zip'),
    ],
    ids=['case-alias', 'unicode-alias', 'casefold-expansion'],
)
def test_discovery_does_not_infer_unconfirmed_filesystem_aliases(
    recorded: str,
    observed: str,
):
    disk = DiskSnapshot({observed: 12})

    assert find_recorded_file(recorded, disk) is None
    assert (
        find_media_file(
            MEDIA_ID,
            disk,
            {},
            recorded_path=recorded,
            preferred=MediaPathHint(recorded),
        )
        is None
    )


def test_long_unicode_extension_fits_each_collision_name_and_can_be_rediscovered():
    preferred = f'files/report.{"я" * 150}'
    first = reserve_media_path(preferred, MEDIA_ID, DiskSnapshot({}), {})
    second = reserve_media_path(preferred, MEDIA_ID, DiskSnapshot({first: 12}), {})
    third = reserve_media_path(
        preferred, MEDIA_ID, DiskSnapshot({first: 12, second: 12}), {}
    )

    assert len({first, second, third}) == 3
    for path in (first, second, third):
        assert len(PurePosixPath(path).name.encode('utf-8')) <= MAX_NAME_BYTES
    assert ' (abcdefgh)' in PurePosixPath(second).name
    assert ' (abcdefgh-2)' in PurePosixPath(third).name
    assert find_media_file(
        MEDIA_ID,
        DiskSnapshot({second: 12}),
        {},
        preferred=MediaPathHint(preferred),
        expected_size=12,
    ) == FileMatch(path=second, size=12)


def test_observer_alias_with_response_suffix_keeps_the_actual_disk_path():
    observed = 'videos/TITLE.mp4'
    disk = DiskSnapshot({observed: 12}, aliases={'videos/Title.mp4': observed})

    assert find_media_file(
        'boosty_video:abcdefgh-first',
        disk,
        {},
        preferred=MediaPathHint('videos/Title', suffix_from_response=True),
    ) == FileMatch(path=observed, size=12)


@pytest.mark.parametrize('preferred', ['files/report.v1.', 'files/report.???'])
def test_sanitized_names_are_rediscovered_from_the_original_hint(preferred: str):
    first = reserve_media_path(preferred, MEDIA_ID, DiskSnapshot({}), {})
    second = reserve_media_path(preferred, MEDIA_ID, DiskSnapshot({first: 12}), {})

    assert first != second
    for path in (first, second):
        assert find_media_file(
            MEDIA_ID,
            DiskSnapshot({path: 12}),
            {},
            preferred=MediaPathHint(preferred),
            expected_size=12,
        ) == FileMatch(path=path, size=12)


def test_an_existing_identity_marker_in_the_title_does_not_confuse_collision_family():
    preferred = 'files/report (abcdefgh).zip'
    second = reserve_media_path(preferred, MEDIA_ID, DiskSnapshot({preferred: 12}), {})
    third = reserve_media_path(
        preferred, MEDIA_ID, DiskSnapshot({preferred: 12, second: 12}), {}
    )

    assert second == 'files/report (abcdefgh) (abcdefgh).zip'
    assert third == 'files/report (abcdefgh) (abcdefgh-2).zip'
    assert find_media_file(
        MEDIA_ID,
        DiskSnapshot({'files/report (abcdefgh-2).zip': 12, third: 12}),
        {},
        preferred=MediaPathHint(preferred),
        expected_size=12,
    ) == FileMatch(path=third, size=12)


def test_an_observer_alias_cannot_adopt_another_owners_file():
    actual = 'files/archive.zip'
    alias = 'files/alternate-name.zip'
    disk = DiskSnapshot({actual: 12}, aliases={alias: actual})

    assert (
        find_media_file(
            MEDIA_ID,
            disk,
            {OTHER_ID: actual},
            recorded_path=alias,
            preferred=MediaPathHint(alias),
            expected_size=12,
        )
        is None
    )
